/**
 * The clip player's states (docs/KOZ.md §6.6): asked for → the box is fetching (polled every 2 s)
 * → ready or failed with its reason, a refusal (409 no_camera) said plainly, and polling that stops
 * when the player closes.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { effectScope, nextTick, ref } from "vue";

import { ApiError } from "@/api/http";
import { json } from "@/test/fixtures";
import { testApp } from "@/test/plugins";

import { CLIP_POLL_MS, clipPhase, failureKey, refusalKey, shouldPoll, waitingStep } from "../lib/clip";
import { useClip } from "../lib/useClip";
import type { Clip, ClipRequest } from "../types";

function clip(state: Clip["state"], extra: Partial<Clip> = {}): Clip {
  return {
    id: 55,
    state,
    reason: "sale",
    camera: { id: 11, name: "Kassa 1" },
    start: "2026-11-23T16:30:50Z",
    end: "2026-11-23T16:31:10Z",
    sale_id: 991,
    alert_id: null,
    video_url: state === "ready" ? "https://files.example/clip.mp4" : null,
    poster_url: null,
    duration_s: state === "ready" ? 20 : null,
    failure: null,
    failure_text: null,
    created_at: "2026-11-23T16:31:12Z",
    ...extra,
  };
}

async function flush(): Promise<void> {
  for (let i = 0; i < 6; i++) await Promise.resolve();
  await nextTick();
}

describe("the clip's phase", () => {
  it("follows the request and the clip's state", () => {
    expect(clipPhase(null, null)).toBe("requesting");
    expect(clipPhase(clip("pending"), null)).toBe("pending");
    expect(clipPhase(clip("fetching"), null)).toBe("fetching");
    expect(clipPhase(clip("ready"), null)).toBe("ready");
    // "ready" without a video yet is still on its way.
    expect(clipPhase(clip("ready", { video_url: null }), null)).toBe("fetching");
    expect(clipPhase(clip("failed"), null)).toBe("failed");
    expect(clipPhase(null, new ApiError(409, { code: "no_camera" }))).toBe("refused");
  });

  it("keeps asking only while the box works on it", () => {
    expect(shouldPoll("pending")).toBe(true);
    expect(shouldPoll("fetching")).toBe(true);
    expect(shouldPoll("ready")).toBe(false);
    expect(shouldPoll("failed")).toBe(false);
    expect(shouldPoll("refused")).toBe(false);
    expect([waitingStep("pending"), waitingStep("fetching"), waitingStep("ready")]).toEqual([0, 1, 2]);
  });

  it("explains every failure the box can send, and the refusals", () => {
    expect(failureKey("too_old")).toBe("vision.clip.failure.too_old");
    expect(failureKey("agent_timeout")).toBe("vision.clip.failure.agent_timeout");
    expect(failureKey("something_new")).toBe("vision.clip.failure.unknown");
    expect(failureKey(null)).toBe("vision.clip.failure.unknown");
    expect(refusalKey(new ApiError(409, { code: "no_camera" }))).toBe("vision.clip.refused.no_camera");
    expect(refusalKey(new ApiError(403, { detail: "No." }))).toBe("vision.clip.refused.forbidden");
    expect(refusalKey(new ApiError(0, null))).toBe("vision.clip.refused.offline");
    expect(refusalKey(new Error("x"))).toBe("vision.clip.refused.generic");
  });
});

describe("following a clip", () => {
  let states: Array<Clip | Response>;
  let calls: Array<{ url: string; method: string; body: unknown }>;

  beforeEach(async () => {
    vi.useFakeTimers();
    await testApp("/c/1/vision/review");
    calls = [];
    states = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string, init?: RequestInit) => {
        calls.push({ url: String(input), method: init?.method ?? "GET", body: init?.body ? JSON.parse(String(init.body)) : undefined });
        if ((init?.method ?? "GET") === "POST") return json(clip("pending"));
        const next = states.shift() ?? clip("fetching");
        return next instanceof Response ? next : json(next);
      }),
    );
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("asks once, polls every 2 s while the box fetches, and stops when it is ready", async () => {
    states = [clip("fetching"), clip("fetching"), clip("ready")];
    const scope = effectScope();
    const request = ref<ClipRequest | null>({ sale_id: 991 });
    const state = scope.run(() => useClip(request))!;
    await flush();
    expect(calls[0]).toMatchObject({ url: "/api/v1/owner/companies/1/vision/clips/", method: "POST", body: { sale_id: 991 } });
    expect(state.phase.value).toBe("pending");
    for (const expected of ["fetching", "fetching", "ready"]) {
      await vi.advanceTimersByTimeAsync(CLIP_POLL_MS);
      await flush();
      expect(state.phase.value).toBe(expected);
    }
    expect(calls.filter((c) => c.url.endsWith("/vision/clips/55/"))).toHaveLength(3);
    await vi.advanceTimersByTimeAsync(CLIP_POLL_MS * 3);
    expect(calls).toHaveLength(4);
    expect(state.clip.value?.video_url).toBe("https://files.example/clip.mp4");
    scope.stop();
  });

  it("asks an alert's clip on the alert, and shows a failure with its reason", async () => {
    states = [clip("failed", { failure: "not_recorded" })];
    const scope = effectScope();
    const state = scope.run(() => useClip(ref<ClipRequest | null>({ alert_id: 123 })))!;
    await flush();
    expect(calls[0]).toMatchObject({ url: "/api/v1/owner/companies/1/vision/alerts/123/clip/", method: "POST" });
    await vi.advanceTimersByTimeAsync(CLIP_POLL_MS);
    await flush();
    expect(state.phase.value).toBe("failed");
    expect(failureKey(state.clip.value?.failure)).toBe("vision.clip.failure.not_recorded");
    scope.stop();
  });

  it("says why when the request is refused (no counter camera for the till)", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json({ detail: "No camera for this till.", code: "no_camera" }, 409)));
    const scope = effectScope();
    const state = scope.run(() => useClip(ref<ClipRequest | null>({ sale_id: 7 })))!;
    await flush();
    expect(state.phase.value).toBe("refused");
    expect(refusalKey(state.error.value)).toBe("vision.clip.refused.no_camera");
    scope.stop();
  });

  it("stops polling when the player closes", async () => {
    const scope = effectScope();
    const request = ref<ClipRequest | null>({ sale_id: 991 });
    const state = scope.run(() => useClip(request))!;
    await flush();
    request.value = null;
    await flush();
    await vi.advanceTimersByTimeAsync(CLIP_POLL_MS * 4);
    expect(calls).toHaveLength(1);
    expect(state.clip.value).toBeNull();
    scope.stop();
  });

  it("rides out a poll that fails for a moment", async () => {
    states = [json({ detail: "Bad gateway" }, 502), clip("ready")];
    const scope = effectScope();
    const state = scope.run(() => useClip(ref<ClipRequest | null>({ camera_id: 11, at: "2026-11-23T16:31:00Z", before_s: 10, after_s: 5 })))!;
    await flush();
    expect(calls[0]!.body).toEqual({ camera_id: 11, at: "2026-11-23T16:31:00Z", before_s: 10, after_s: 5 });
    await vi.advanceTimersByTimeAsync(CLIP_POLL_MS);
    await flush();
    expect(state.phase.value).toBe("pending");
    await vi.advanceTimersByTimeAsync(CLIP_POLL_MS);
    await flush();
    expect(state.phase.value).toBe("ready");
    scope.stop();
  });
});
