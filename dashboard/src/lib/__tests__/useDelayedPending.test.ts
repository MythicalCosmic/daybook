import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { effectScope, nextTick, ref } from "vue";

import { useDelayedPending } from "@/lib/useDelayedPending";

describe("useDelayedPending", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("never shows a skeleton for fast responses", async () => {
    const scope = effectScope();
    const pending = ref(true);
    const visible = scope.run(() => useDelayedPending(pending))!;
    vi.advanceTimersByTime(100);
    pending.value = false;
    await nextTick();
    vi.advanceTimersByTime(500);
    expect(visible.value).toBe(false);
    scope.stop();
  });

  it("shows after 150 ms and stays at least 300 ms", async () => {
    const scope = effectScope();
    const pending = ref(true);
    const visible = scope.run(() => useDelayedPending(pending))!;
    vi.advanceTimersByTime(150);
    expect(visible.value).toBe(true);
    vi.advanceTimersByTime(50);
    pending.value = false;
    await nextTick();
    expect(visible.value).toBe(true);
    vi.advanceTimersByTime(249);
    expect(visible.value).toBe(true);
    vi.advanceTimersByTime(1);
    expect(visible.value).toBe(false);
    scope.stop();
  });

  it("honours custom timings and keeps showing when loading resumes", async () => {
    const scope = effectScope();
    const pending = ref(true);
    const visible = scope.run(() => useDelayedPending(pending, { delay: 10, minVisible: 0 }))!;
    vi.advanceTimersByTime(10);
    expect(visible.value).toBe(true);
    pending.value = false;
    await nextTick();
    expect(visible.value).toBe(false);
    pending.value = true;
    await nextTick();
    vi.advanceTimersByTime(10);
    expect(visible.value).toBe(true);
    scope.stop();
  });
});
