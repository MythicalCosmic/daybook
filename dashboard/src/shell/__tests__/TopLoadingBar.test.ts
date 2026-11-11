import { flushPromises } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { nextTick } from "vue";

import { mountWithProviders, testApp } from "@/test/plugins";

import TopLoadingBar from "../TopLoadingBar.vue";

function gate() {
  let release!: (value: unknown) => void;
  const promise = new Promise((resolve) => (release = resolve));
  return { promise, release };
}

describe("TopLoadingBar", () => {
  beforeEach(() => vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "requestAnimationFrame", "Date"] }));
  afterEach(() => vi.useRealTimers());

  it("shows after 150 ms for data that isn't on screen yet, then fills and fades", async () => {
    const app = await testApp("/c/1/tasks");
    const { wrapper } = mountWithProviders(TopLoadingBar, { plugins: app.plugins });
    const first = gate();
    void app.client.fetchQuery({ queryKey: ["first"], queryFn: () => first.promise });
    await nextTick();
    vi.advanceTimersByTime(100);
    await nextTick();
    expect(wrapper.find("[data-testid=top-loading-bar]").exists()).toBe(false);
    vi.advanceTimersByTime(60);
    await nextTick();
    expect(wrapper.find("[data-testid=top-loading-bar]").classes()).toContain("running");
    first.release("done");
    await flushPromises();
    expect(wrapper.find("[data-testid=top-loading-bar]").classes()).toContain("finishing");
    vi.advanceTimersByTime(450);
    await nextTick();
    expect(wrapper.find("[data-testid=top-loading-bar]").exists()).toBe(false);
  });

  it("never shows for a quick answer or for a refresh of data already shown", async () => {
    const app = await testApp("/c/1/tasks");
    const { wrapper } = mountWithProviders(TopLoadingBar, { plugins: app.plugins });
    const quick = gate();
    void app.client.fetchQuery({ queryKey: ["quick"], queryFn: () => quick.promise });
    vi.advanceTimersByTime(80);
    quick.release(1);
    await flushPromises();
    vi.advanceTimersByTime(500);
    await nextTick();
    expect(wrapper.find("[data-testid=top-loading-bar]").exists()).toBe(false);

    // The same query again (a live refresh): it has data, so it doesn't count.
    const refresh = gate();
    void app.client.fetchQuery({ queryKey: ["quick"], queryFn: () => refresh.promise, staleTime: 0 });
    vi.advanceTimersByTime(400);
    await nextTick();
    expect(wrapper.find("[data-testid=top-loading-bar]").exists()).toBe(false);
    refresh.release(2);
    await flushPromises();
  });
});
