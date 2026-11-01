import { createPinia, setActivePinia } from "pinia";
import { afterEach, describe, expect, it, vi } from "vitest";
import { effectScope } from "vue";

import { useCompanyToday } from "@/stores/company";

afterEach(() => vi.useRealTimers());

describe("useCompanyToday", () => {
  it("is the company's day and moves on at its midnight while the console stays open", () => {
    vi.useFakeTimers();
    // 23:59:50 in Tashkent (UTC+5) is 18:59:50 UTC.
    vi.setSystemTime(new Date("2026-11-02T18:59:50Z"));
    setActivePinia(createPinia());
    const scope = effectScope();
    const today = scope.run(() => useCompanyToday())!;
    expect(today.value).toBe("2026-11-02");
    vi.advanceTimersByTime(30_000);
    expect(today.value).toBe("2026-11-03");
    scope.stop();
  });
});
