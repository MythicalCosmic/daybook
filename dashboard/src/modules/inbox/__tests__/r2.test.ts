// Round 2: the inbox's Enter shortcut leaves focused controls alone.
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";

import { mergeModuleMessages } from "@/i18n";
import { json } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

import NotificationsPanel from "../components/NotificationsPanel.vue";
import en from "../i18n/en.json";
import type { Notification } from "../types";

const note = (id: number): Notification => ({
  id,
  kind: "sales.cash_difference",
  severity: "critical",
  title: `Note ${id}`,
  body: "Body",
  url: "/c/1/sales/shifts/1042",
  app_screen: "",
  target_type: "shift",
  target_id: 1042,
  created_at: "2026-10-20T09:00:00Z",
  read_at: "2026-10-20T10:00:00Z",
  acted_at: null,
  acted_by: null,
  actor: null,
  actions: [],
  data: {},
});

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

describe("NotificationsPanel Enter", () => {
  it("opens the selected note's page, but not when Enter presses a focused button", async () => {
    mergeModuleMessages("inbox", { en, ru: en, uz: en });
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string) => (String(input).includes("/inbox/") ? json({ count: 1, next: null, previous: null, results: [note(5)] }) : json({}))),
    );
    const app = await testApp("/c/1/inbox?note=5&show=all");
    const { wrapper } = mountWithProviders(NotificationsPanel, { plugins: app.plugins });
    await flushPromises();
    await flushPromises();
    const button = document.body.querySelector<HTMLButtonElement>("button")!;
    button.focus();
    button.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    await flushPromises();
    expect(app.router.currentRoute.value.path).toBe("/c/1/inbox");
    button.blur();
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter" }));
    await flushPromises();
    expect(app.router.currentRoute.value.path).toBe("/c/1/sales/shifts/1042");
    wrapper.unmount();
  });
});
