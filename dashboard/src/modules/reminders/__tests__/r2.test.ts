// Round 2: the blocked list links a person's open tasks only for people who may open Tasks.
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";

import { mergeModuleMessages } from "@/i18n";
import { company, json, me } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";
import { useSessionStore } from "@/stores/session";

import BlockedList from "../components/BlockedList.vue";
import en from "../i18n/en.json";

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

describe("BlockedList", () => {
  it("shows open tasks as a plain number to someone without tasks.view_all", async () => {
    mergeModuleMessages("reminders", { en, ru: en, uz: en });
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        json([{ member: { id: 12, name: "Alisher Valiyev", position: "Farmatsevt", photo_url: null }, blocked_at: "2026-10-30T09:00:00Z", branch: "Chilonzor", open_tasks: 3, late_tasks: 1 }]),
      ),
    );
    const app = await testApp("/c/1/reminders?tab=blocked");
    useSessionStore().me = me([company({ is_owner: false, permissions: ["reminders.configure", "members.view"] })]);
    const { wrapper } = mountWithProviders(BlockedList, { plugins: app.plugins });
    await flushPromises();
    await flushPromises();
    expect(wrapper.text()).toContain("Alisher Valiyev");
    expect(wrapper.find("a[href*='/tasks?assignee=12']").exists()).toBe(false);
    wrapper.unmount();
  });
});
