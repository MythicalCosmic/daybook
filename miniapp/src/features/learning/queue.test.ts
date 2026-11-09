/**
 * The retry queue for progress reports, saved answers and page views: one request per key at a
 * time, what waits is merged, a lost signal keeps the report (and its ranges) for the next try,
 * a refusal is dropped, and a closed app's reports go out on the next start.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../../api/client";
import { initData } from "../../telegram";
import { drain, mergeJobs, queueState, resetQueue, restore, retryAll, send, storageKey, type QueueJob } from "./queue";
import type { ProgressReport } from "./types";

const api = vi.hoisted(() => vi.fn());
vi.mock("../../api/client", async (importOriginal) => ({ ...(await importOriginal<typeof import("../../api/client")>()), api }));
vi.mock("../../telegram", async (importOriginal) => ({ ...(await importOriginal<typeof import("../../telegram")>()), initData: vi.fn(() => "") }));

const progress = (report: Partial<ProgressReport> = {}): QueueJob => {
  const body: ProgressReport = { session: "s1", position: 10, duration: 120, ranges: [[0, 10]], playing: true, ...report };
  return { kind: "progress", key: `progress:3:${body.session}`, path: "/companies/1/learning/lessons/3/progress/", method: "POST", body };
};
const answer = (question: number, value: string): QueueJob => ({
  kind: "answer",
  key: `answer:9:${question}`,
  path: "/companies/1/learning/attempts/9/answers/",
  method: "PUT",
  body: { question, answer: { option: value } },
});

/** Requests as the server saw them. */
const bodies = () => api.mock.calls.map(([, options]) => (options as { json: unknown }).json);
const offline = () => Promise.reject(new TypeError("Failed to fetch"));
const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

beforeEach(() => {
  resetQueue();
  localStorage.clear();
  api.mockReset();
});

afterEach(() => {
  vi.useRealTimers();
  resetQueue();
});

describe("the retry queue", () => {
  it("sends a report with keepalive and hands back the server's answer", async () => {
    api.mockResolvedValue({ percent: 8, position: 10, completed: false, completed_now: false, points: null });
    await expect(send(progress())).resolves.toMatchObject({ percent: 8 });
    expect(api).toHaveBeenCalledWith("/companies/1/learning/lessons/3/progress/", { method: "POST", json: progress().body, keepalive: true });
    expect(queueState("progress:").pending).toBe(0);
  });

  it("keeps a report the signal lost, adds the next one's ranges to it, and sends it when back online", async () => {
    api.mockImplementation(offline);
    const first = send(progress({ ranges: [[0, 10]], position: 10 }));
    await flush();
    expect(queueState("progress:3:")).toEqual({ pending: 1, failing: true });
    expect(localStorage.getItem("daybook.learning.queue.v1")).toContain("progress:3:s1");

    const second = send(progress({ ranges: [[10, 20]], position: 20 }));
    await flush();
    api.mockReset();
    api.mockResolvedValue({ percent: 16, position: 20, completed: false, completed_now: false, points: null });
    window.dispatchEvent(new Event("online"));
    await expect(first).resolves.toMatchObject({ percent: 16 });
    await expect(second).resolves.toMatchObject({ percent: 16 });
    // One request with everything played, the newest position on top.
    expect(bodies()).toEqual([{ session: "s1", position: 20, duration: 120, ranges: [[0, 20]], playing: true }]);
    expect(localStorage.getItem("daybook.learning.queue.v1")).toBeNull();
  });

  it("sends one request per key at a time; the newest answer wins what waited", async () => {
    let release!: () => void;
    api.mockImplementationOnce(() => new Promise((resolve) => (release = () => resolve(undefined))));
    api.mockResolvedValue(undefined);
    const a = send(answer(12, "a"));
    const b = send(answer(12, "b"));
    const c = send(answer(12, "c"));
    const other = send(answer(13, "x"));
    await flush();
    // Question 13 didn't wait for 12.
    expect(bodies()).toEqual([
      { question: 12, answer: { option: "a" } },
      { question: 13, answer: { option: "x" } },
    ]);
    release();
    await Promise.all([a, b, c, other]);
    expect(bodies().slice(2)).toEqual([{ question: 12, answer: { option: "c" } }]);
  });

  it("drops what the server refused and says so", async () => {
    api.mockRejectedValue(new ApiError(400, { detail: "The time is up." }));
    await expect(send(answer(12, "a"))).rejects.toBeInstanceOf(ApiError);
    expect(queueState("answer:9:").pending).toBe(0);
    expect(localStorage.getItem("daybook.learning.queue.v1")).toBeNull();
  });

  it("tries again on its own after a server hiccup", async () => {
    vi.useFakeTimers();
    api.mockRejectedValueOnce(new ApiError(502, null)).mockResolvedValue(undefined);
    const done = send(answer(12, "a"));
    await vi.advanceTimersByTimeAsync(0);
    expect(api).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(2_000);
    await done;
    expect(api).toHaveBeenCalledTimes(2);
  });

  it("sends what a closed app left behind, once it starts again", async () => {
    api.mockImplementation(offline);
    void send(answer(12, "b"));
    await flush();
    const saved = localStorage.getItem("daybook.learning.queue.v1");
    resetQueue();
    localStorage.setItem("daybook.learning.queue.v1", saved!);
    api.mockReset();
    api.mockResolvedValue(undefined);
    restore();
    await flush();
    expect(bodies()).toEqual([{ question: 12, answer: { option: "b" } }]);
  });

  it("lets a quiz wait for its answers before finishing, and says when they didn't go", async () => {
    vi.useFakeTimers();
    api.mockImplementation(offline);
    void send(answer(12, "a"));
    await vi.advanceTimersByTimeAsync(0);
    const waiting = drain("answer:9:", 3_000);
    await vi.advanceTimersByTimeAsync(3_000);
    await expect(waiting).resolves.toBe(false);

    api.mockReset();
    api.mockResolvedValue(undefined);
    const again = drain("answer:9:", 3_000);
    retryAll();
    await vi.advanceTimersByTimeAsync(0);
    await expect(again).resolves.toBe(true);
    await expect(drain("answer:9:")).resolves.toBe(true);
  });

  it("keeps each Telegram account's reports apart (a phone may hold two)", async () => {
    const as = (id: number) => vi.mocked(initData).mockReturnValue(`user=${encodeURIComponent(JSON.stringify({ id, first_name: "A" }))}&hash=x`);
    as(4242);
    expect(storageKey()).toBe("daybook.learning.queue.v1:4242");
    api.mockImplementation(offline);
    void send(answer(12, "a"));
    await flush();
    expect(localStorage.getItem("daybook.learning.queue.v1:4242")).toContain("answer:9:12");
    resetQueue();
    localStorage.setItem("daybook.learning.queue.v1:4242", JSON.stringify([{ job: answer(12, "a"), at: Date.now() }]));
    api.mockReset();
    api.mockResolvedValue(undefined);
    // Someone else opens the app on this phone: Alisher's report stays for Alisher.
    as(1004);
    restore();
    await flush();
    expect(api).not.toHaveBeenCalled();
    as(4242);
    restore();
    await flush();
    expect(bodies()).toEqual([{ question: 12, answer: { option: "a" } }]);
    vi.mocked(initData).mockReturnValue("");
  });

  it("merges reading time and keeps the furthest scroll", () => {
    const view = (seconds: number, scrolled: number): QueueJob => ({ kind: "view", key: "view:5:s", path: "/x/", method: "POST", body: { session: "s", seconds, scrolled } });
    expect(mergeJobs(view(15, 60), view(10, 40)).body).toEqual({ session: "s", seconds: 25, scrolled: 60 });
  });
});
