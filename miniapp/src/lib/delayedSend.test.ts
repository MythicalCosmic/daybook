/** Requests that wait for Undo: cancelled in time, sent after the wait, sent at once when the app hides. */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { flushDelayed, sendLater, UNDO_MS } from "./delayedSend";

beforeEach(() => vi.useFakeTimers());
afterEach(() => {
  flushDelayed();
  vi.useRealTimers();
});

describe("a delayed send", () => {
  it("goes out after the wait unless cancelled, and says when it's too late to cancel", () => {
    const send = vi.fn();
    const job = sendLater(send);
    vi.advanceTimersByTime(UNDO_MS - 1);
    expect(send).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    expect(send).toHaveBeenCalledOnce();
    expect(job.cancel()).toBe(false);
  });

  it("never goes out once cancelled", () => {
    const send = vi.fn();
    expect(sendLater(send).cancel()).toBe(true);
    vi.advanceTimersByTime(UNDO_MS * 2);
    expect(send).not.toHaveBeenCalled();
  });

  it("holds its clock while its toast is held, and gives time again after", () => {
    const send = vi.fn();
    const job = sendLater(send);
    vi.advanceTimersByTime(4000);
    job.pause();
    vi.advanceTimersByTime(60_000);
    expect(send).not.toHaveBeenCalled();
    job.resume();
    // Longer than the 2.5 s the toast lingers once let go.
    vi.advanceTimersByTime(2500);
    expect(send).not.toHaveBeenCalled();
    vi.advanceTimersByTime(200);
    expect(send).toHaveBeenCalledOnce();
  });

  it("waits for the connection rather than failing offline", () => {
    const send = vi.fn();
    Object.defineProperty(navigator, "onLine", { configurable: true, get: () => false });
    sendLater(send);
    vi.advanceTimersByTime(UNDO_MS);
    expect(send).not.toHaveBeenCalled();
    Object.defineProperty(navigator, "onLine", { configurable: true, get: () => true });
    window.dispatchEvent(new Event("online"));
    expect(send).toHaveBeenCalledOnce();
  });

  it("goes out at once when the app is hidden or closed", () => {
    const send = vi.fn();
    sendLater(send);
    Object.defineProperty(document, "visibilityState", { configurable: true, get: () => "hidden" });
    document.dispatchEvent(new Event("visibilitychange"));
    expect(send).toHaveBeenCalledOnce();
    Object.defineProperty(document, "visibilityState", { configurable: true, get: () => "visible" });
    const later = vi.fn();
    sendLater(later);
    window.dispatchEvent(new Event("pagehide"));
    expect(later).toHaveBeenCalledOnce();
  });
});
