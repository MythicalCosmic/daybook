/** The app's clock: one timer per pace, the same moment on every screen, awake on return. */
import { act, cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useNow } from "./useNow";

function Clock({ label, intervalMs }: { label: string; intervalMs?: number }) {
  const now = useNow(intervalMs);
  return <span data-testid={label}>{now.toISOString()}</span>;
}

const shown = (label: string) => document.querySelector(`[data-testid="${label}"]`)?.textContent;

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("useNow", () => {
  it("runs one timer for every screen on the same pace, and they all read the same moment", () => {
    vi.useFakeTimers({ now: new Date("2026-11-02T09:00:00Z") });
    const timers = vi.spyOn(window, "setInterval");
    render(
      <>
        <Clock label="home" />
        <Clock label="row" />
        <Clock label="card" />
      </>,
    );
    expect(timers).toHaveBeenCalledTimes(1);
    act(() => vi.advanceTimersByTime(30_000));
    expect(shown("home")).toBe("2026-11-02T09:00:30.000Z");
    expect(shown("row")).toBe(shown("home"));
    expect(shown("card")).toBe(shown("home"));
    // A faster pace (a running timer) has its own.
    render(<Clock label="timer" intervalMs={1000} />);
    expect(timers).toHaveBeenCalledTimes(2);
  });

  it("stops the timer once nobody shows the time, and starts from the time of day after", () => {
    vi.useFakeTimers({ now: new Date("2026-11-02T09:00:00Z") });
    const stop = vi.spyOn(window, "clearInterval");
    const first = render(<Clock label="a" />);
    first.unmount();
    expect(stop).toHaveBeenCalled();
    vi.setSystemTime(new Date("2026-11-02T14:00:00Z"));
    render(<Clock label="b" />);
    expect(shown("b")).toBe("2026-11-02T14:00:00.000Z");
  });

  it("reads the time again the moment the app is back in view (timers sleep in the background)", () => {
    vi.useFakeTimers({ now: new Date("2026-11-02T09:00:00Z") });
    render(<Clock label="home" />);
    // An hour in the chat: the half-minute timer hasn't fired yet when the app comes back.
    vi.setSystemTime(new Date("2026-11-02T10:00:00Z"));
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
    act(() => {
      document.dispatchEvent(new Event("visibilitychange"));
    });
    expect(shown("home")).toBe("2026-11-02T10:00:00.000Z");
  });
});
