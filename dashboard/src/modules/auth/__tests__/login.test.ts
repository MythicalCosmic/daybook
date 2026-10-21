// The registry first, as in the app (core/modules loads every module's index.ts).
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { effectScope } from "vue";

import { json } from "@/test/fixtures";

import { claimLoginLink, createLoginLink, pollLoginLink } from "../api";
import { LIFETIME_MS, POLL_MS, useLoginLink } from "../useLoginLink";

const LINK = {
  id: "5b2c6c1e-0d6a-4e33-9a43-6f8f6a3f0d11",
  poll_token: "poll-secret",
  deep_link: "https://t.me/owner_test_bot?start=login_abc",
  bot_username: "owner_test_bot",
  match_code: "47",
  expires_at: "2026-10-21T09:03:00Z",
};

interface Call {
  method: string;
  url: string;
  headers: Record<string, string>;
}

/** Answers the sign-in endpoints in order: `statuses` are what successive polls return. */
function stubAuth(options: { create?: Response; statuses?: Array<string | number>; claim?: Response } = {}): Call[] {
  const calls: Call[] = [];
  const statuses = [...(options.statuses ?? ["pending"])];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      calls.push({ method, url, headers: (init?.headers ?? {}) as Record<string, string> });
      if (method === "POST" && url.endsWith("/login-links/")) return options.create ?? json(LINK, 201);
      if (method === "POST" && url.endsWith("/claim/")) return options.claim ?? json({ access: "owner-access" });
      const next = statuses.length > 1 ? statuses.shift()! : statuses[0]!;
      return typeof next === "number" ? json({ detail: "x" }, next) : json({ status: next });
    }),
  );
  return calls;
}

function run(onSignedIn = vi.fn()) {
  const scope = effectScope();
  const login = scope.run(() => useLoginLink({ onSignedIn }))!;
  return { login, onSignedIn, scope };
}

async function advance(ms: number): Promise<void> {
  await vi.advanceTimersByTimeAsync(ms);
  await flushPromises();
}

beforeEach(() => vi.useFakeTimers());
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("api", () => {
  it("sends the poll token only in its header and never a Bearer token", async () => {
    const calls = stubAuth();
    await createLoginLink();
    await pollLoginLink(LINK);
    await claimLoginLink(LINK);

    expect(calls.map((c) => `${c.method} ${c.url}`)).toEqual([
      "POST /api/v1/owner/auth/login-links/",
      `GET /api/v1/owner/auth/login-links/${LINK.id}/`,
      `POST /api/v1/owner/auth/login-links/${LINK.id}/claim/`,
    ]);
    for (const call of calls.slice(1)) {
      expect(call.headers["X-Login-Poll"]).toBe("poll-secret");
      expect(call.headers.Authorization).toBeUndefined();
      expect(call.url).not.toContain("poll-secret");
    }
    expect(calls[0]!.headers["X-Requested-With"]).toBe("dashboard");
  });
});

describe("useLoginLink", () => {
  it("waits, then claims once when Telegram approves", async () => {
    const calls = stubAuth({ statuses: ["pending", "pending", "approved"] });
    const { login, onSignedIn } = run();

    await login.start();
    expect(login.phase.value).toBe("waiting");
    expect(login.link.value?.match_code).toBe("47");
    expect(login.remaining.value).toBe(180);

    await advance(POLL_MS);
    expect(login.phase.value).toBe("waiting");
    await advance(POLL_MS * 2);

    expect(onSignedIn).toHaveBeenCalledWith("owner-access");
    expect(login.phase.value).toBe("done");
    expect(calls.filter((c) => c.url.endsWith("/claim/"))).toHaveLength(1);
    // Polling stopped.
    const polls = calls.length;
    await advance(POLL_MS * 3);
    expect(calls).toHaveLength(polls);
  });

  it("shows the wrong-number state when Telegram denies", async () => {
    const calls = stubAuth({ statuses: ["pending", "denied"] });
    const { login, onSignedIn } = run();

    await login.start();
    await advance(POLL_MS * 2);

    expect(login.phase.value).toBe("denied");
    expect(onSignedIn).not.toHaveBeenCalled();
    expect(calls.some((c) => c.url.endsWith("/claim/"))).toBe(false);
  });

  it("expires after three minutes even if nobody answers", async () => {
    stubAuth({ statuses: ["pending"] });
    const { login } = run();

    await login.start();
    await advance(LIFETIME_MS - 1000);
    expect(login.phase.value).toBe("waiting");
    expect(login.remaining.value).toBe(1);
    await advance(1500);

    expect(login.phase.value).toBe("expired");
  });

  it("treats a vanished or used link as expired", async () => {
    stubAuth({ statuses: [404] });
    const { login } = run();
    await login.start();
    await advance(POLL_MS);
    expect(login.phase.value).toBe("expired");
  });

  it("keeps polling through network trouble and says it is reconnecting", async () => {
    stubAuth({ statuses: ["pending"] });
    const { login } = run();
    await login.start();
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("offline"))));

    await advance(POLL_MS);
    expect(login.phase.value).toBe("waiting");
    expect(login.reconnecting.value).toBe(true);

    stubAuth({ statuses: ["approved"] });
    await advance(POLL_MS * 2);
    expect(login.phase.value).toBe("done");
  });

  it("reports a lost access at claim time", async () => {
    stubAuth({ statuses: ["approved"], claim: json({ detail: "No access", code: "no_access" }, 403) });
    const { login } = run();
    await login.start();
    await advance(POLL_MS);
    expect(login.phase.value).toBe("no-access");
  });

  it("knows when Telegram sign-in isn't set up and when it is throttled", async () => {
    stubAuth({ create: json({ detail: "x", code: "signin_unavailable" }, 503) });
    const first = run();
    await first.login.start();
    expect(first.login.phase.value).toBe("unavailable");

    stubAuth({ create: json({ detail: "Slow down" }, 429) });
    const second = run();
    await second.login.start();
    expect(second.login.phase.value).toBe("throttled");
  });

  it("a new code starts over and the old poller stops", async () => {
    const calls = stubAuth({ statuses: ["pending"] });
    const { login } = run();
    await login.start();
    await login.start();
    await advance(POLL_MS);

    // One poll per tick, from the newest link only.
    expect(calls.filter((c) => c.method === "GET")).toHaveLength(1);
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(2);
  });

  it("stops when the page goes away", async () => {
    const calls = stubAuth({ statuses: ["pending"] });
    const { login, scope } = run();
    await login.start();
    scope.stop();
    await advance(POLL_MS * 4);
    expect(calls.filter((c) => c.method === "GET")).toHaveLength(0);
  });
});
