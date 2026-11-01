// Round 2 wording: plurals, numbers and file names in the person's language.
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";

import { i18n, mergeModuleMessages } from "@/i18n";
import { json } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

import LogTimeDialog from "../components/LogTimeDialog.vue";
import en from "../i18n/en.json";
import ru from "../i18n/ru.json";
import uz from "../i18n/uz.json";
import type { ProjectDetail } from "../types";

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

describe("projects wording", () => {
  it("says Limit: 1 card in English", async () => {
    await testApp("/c/1/projects", "en");
    mergeModuleMessages("projects", { en, ru, uz });
    expect(i18n.global.t("projects.list.wipNow", { n: 1 }, 1)).toBe("Limit: 1 card");
    expect(i18n.global.t("projects.list.wipNow", { n: 3 }, 3)).toBe("Limit: 3 cards");
  });

  it("names the cards file in the person's language", async () => {
    await testApp("/c/1/projects", "uz");
    mergeModuleMessages("projects", { en, ru, uz });
    expect(i18n.global.t("projects.list.csvName", { key: "OPEN" })).toBe("OPEN kartalari");
  });

  it("writes an hour and a half with the decimal comma in Uzbek", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json([])));
    const app = await testApp("/c/1/projects/1/time", "uz");
    mergeModuleMessages("projects", { en, ru, uz });
    const project = { id: 1, key: "OPEN", lists: [], labels: [], milestones: [], members: [], capabilities: { see_all_time: true } } as unknown as ProjectDetail;
    const { wrapper } = mountWithProviders(LogTimeDialog, { props: { project, open: true }, plugins: app.plugins });
    await flushPromises();
    expect(document.body.textContent).toContain("1,5 soat");
    expect(document.body.textContent).not.toContain("1.5 soat");
    wrapper.unmount();
  });
});
