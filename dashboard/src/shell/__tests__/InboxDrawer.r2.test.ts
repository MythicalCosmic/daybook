// Round 2: "Open inbox page" only navigates; closing the drawer first could undo the push.
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";

import { json } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

import InboxDrawer from "../InboxDrawer.vue";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  document.body.innerHTML = "";
  window.history.replaceState(null, "");
});

describe("InboxDrawer page link", () => {
  it("goes to the inbox page without going Back first", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string) => (String(input).includes("/queue/counts/") ? json({ total: 0, kinds: [] }) : json({ items: [] }))),
    );
    const app = await testApp("/c/1/tasks?inbox=needs");
    // The drawer was pushed over /c/1/tasks: closing it would go Back.
    window.history.replaceState({ back: "/c/1/tasks" }, "");
    const back = vi.spyOn(app.router, "back");
    mountWithProviders(InboxDrawer, { plugins: app.plugins });
    await flushPromises();
    const link = [...document.body.querySelectorAll<HTMLAnchorElement>("a")].find((a) => a.getAttribute("href")?.endsWith("/c/1/inbox"))!;
    link.click();
    await flushPromises();
    expect(back).not.toHaveBeenCalled();
    expect(app.router.currentRoute.value.fullPath).toBe("/c/1/inbox");
  });
});
