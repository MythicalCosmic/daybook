/**
 * The console's Telegram session (TelegramBridge): the refresh token kept in memory and
 * sessionStorage, tried before initData, rotated, and given up only when both are refused.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { json } from "@/test/fixtures";

type Bridge = typeof import("@/shell/TelegramBridge");

const LOGIN = "/api/v1/owner/auth/telegram/";
const REFRESH = "/api/v1/owner/auth/telegram/refresh/";
const LOGOUT = "/api/v1/owner/auth/logout/";
const KEY = "daybook.console.telegramSession";
const now = () => Math.floor(Date.now() / 1000);

function webApp(authDate = now(), user = 77) {
  return {
    initData: `query_id=1&user=%7B%22id%22%3A${user}%7D&auth_date=${authDate}&hash=x`,
    initDataUnsafe: { auth_date: authDate, user: { id: user } },
    version: "8.0",
    platform: "ios",
    colorScheme: "light",
    themeParams: {},
    isVersionAtLeast: () => true,
    close: vi.fn(),
    ready: vi.fn(),
    expand: vi.fn(),
    setHeaderColor: vi.fn(),
    setBackgroundColor: vi.fn(),
    onEvent: vi.fn(),
    offEvent: vi.fn(),
    BackButton: { show: vi.fn(), hide: vi.fn(), onClick: vi.fn(), offClick: vi.fn() },
  };
}

/** The console as Telegram opens it: a fresh bridge (module state) each time. */
async function inside(app = webApp()): Promise<Bridge> {
  vi.resetModules();
  window.Telegram = { WebApp: app as never };
  window.location.hash = "#tgWebAppData=x&tgWebAppVersion=8.0";
  const bridge = await import("@/shell/TelegramBridge");
  await bridge.detectTelegram();
  return bridge;
}

interface Call {
  url: string;
  body: Record<string, unknown> | undefined;
}

function server(routes: Record<string, (body: Record<string, unknown>) => Response>): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const body = init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : undefined;
      calls.push({ url, body });
      const handler = routes[url];
      return handler ? handler(body ?? {}) : json({ detail: "Not found." }, 404);
    }),
  );
  return calls;
}

function keep(refresh: string, user: number | null = 77): void {
  sessionStorage.setItem(KEY, JSON.stringify({ user, refresh }));
}

function kept(): { user: number | null; refresh: string } | null {
  const raw = sessionStorage.getItem(KEY);
  return raw ? (JSON.parse(raw) as { user: number | null; refresh: string }) : null;
}

const ended = () => json({ detail: "Your session has ended. Sign in again.", code: "session_ended" }, 401);

beforeEach(() => sessionStorage.clear());

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  window.location.hash = "";
  delete window.Telegram;
  sessionStorage.clear();
});

describe("the Telegram session", () => {
  it("signs in with initData and keeps the refresh token it gets", async () => {
    const calls = server({ [LOGIN]: () => json({ access: "a1", refresh: "r1" }) });
    const bridge = await inside();

    await expect(bridge.telegramRelogin()).resolves.toBe("a1");

    expect(calls.map((call) => call.url)).toEqual([LOGIN]);
    expect(kept()).toEqual({ user: 77, refresh: "r1" });
  });

  it("refreshes with the kept token first and keeps the rotated one", async () => {
    keep("r1");
    const calls = server({ [REFRESH]: (body) => (body.refresh === "r1" ? json({ access: "a2", refresh: "r2" }) : ended()) });
    const bridge = await inside();

    await expect(bridge.telegramRelogin()).resolves.toBe("a2");

    expect(calls.map((call) => call.url)).toEqual([REFRESH]);
    expect(kept()?.refresh).toBe("r2");
  });

  it("keeps the token it has when the refresh answers none (another tab rotated it)", async () => {
    keep("r1");
    server({ [REFRESH]: () => json({ access: "a2", refresh: null }) });
    const bridge = await inside();

    await expect(bridge.telegramRelogin()).resolves.toBe("a2");

    expect(kept()?.refresh).toBe("r1");
  });

  it("falls back to initData when the session was ended", async () => {
    keep("r1");
    const calls = server({ [REFRESH]: ended, [LOGIN]: () => json({ access: "a3", refresh: "r3" }) });
    const bridge = await inside();

    await expect(bridge.telegramRelogin()).resolves.toBe("a3");

    expect(calls.map((call) => call.url)).toEqual([REFRESH, LOGIN]);
    expect(kept()?.refresh).toBe("r3");
  });

  it("gives up only when both are refused", async () => {
    keep("r1");
    server({ [REFRESH]: ended, [LOGIN]: () => json({ detail: "Session ended.", code: "init_data_invalid" }, 401) });
    const bridge = await inside();

    await expect(bridge.telegramRelogin()).resolves.toBeNull();

    expect(kept()).toBeNull();
    expect(bridge.telegramProblem()).toBe("ended");
  });

  it("doesn't post launch data older than the hour it is good for", async () => {
    const calls = server({});
    const bridge = await inside(webApp(now() - 2 * 3600));

    await expect(bridge.telegramRelogin()).resolves.toBeNull();

    expect(calls).toEqual([]);
  });

  it("says when this Telegram has no access", async () => {
    server({ [LOGIN]: () => json({ detail: "No access.", code: "no_access" }, 403) });
    const bridge = await inside();

    await expect(bridge.telegramRelogin()).resolves.toBeNull();

    expect(bridge.telegramProblem()).toBe("no_access");
  });

  it("keeps the session when the server can't be reached", async () => {
    keep("r1");
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => Promise.reject(new TypeError("Failed to fetch"))),
    );
    const bridge = await inside();

    await expect(bridge.telegramRelogin()).rejects.toBeInstanceOf(bridge.TelegramUnreachable);

    expect(kept()?.refresh).toBe("r1");
    expect(bridge.telegramProblem()).toBe("offline");
  });

  it("never uses the token another Telegram account left in this tab", async () => {
    keep("theirs", 99);
    const calls = server({ [LOGIN]: () => json({ access: "a1", refresh: "r1" }) });
    const bridge = await inside();

    await expect(bridge.telegramRelogin()).resolves.toBe("a1");

    expect(calls.map((call) => call.url)).toEqual([LOGIN]);
  });

  it("works in memory when sessionStorage is blocked", async () => {
    const blocked = () => {
      throw new DOMException("Blocked", "SecurityError");
    };
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(blocked);
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(blocked);
    vi.spyOn(Storage.prototype, "removeItem").mockImplementation(blocked);
    const calls = server({
      [LOGIN]: () => json({ access: "a1", refresh: "r1" }),
      [REFRESH]: (body) => (body.refresh === "r1" ? json({ access: "a2", refresh: "r2" }) : ended()),
    });
    const bridge = await inside();

    await expect(bridge.telegramRelogin()).resolves.toBe("a1");
    await expect(bridge.telegramRelogin()).resolves.toBe("a2");

    expect(calls.map((call) => call.url)).toEqual([LOGIN, REFRESH]);
  });

  it("signing out ends the session on the server and stays signed out", async () => {
    keep("r1");
    const calls = server({ [LOGOUT]: () => new Response(null, { status: 204 }), [LOGIN]: () => json({ access: "a1", refresh: "r9" }) });
    const bridge = await inside();

    await bridge.endTelegramSession();

    expect(calls).toEqual([{ url: LOGOUT, body: { refresh: "r1" } }]);
    expect(kept()).toBeNull();
    // A late 401 doesn't sign back in with the still-fresh launch data.
    await expect(bridge.telegramRelogin()).resolves.toBeNull();
    expect(calls).toHaveLength(1);
  });
});
