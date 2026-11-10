// The org chart on a phone: the same tree as an indented outline, no canvas; "Move…" in a person's
// menu instead of dragging.
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { mergeModuleMessages } from "@/i18n";
import { json } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

import en from "../i18n/en.json";
import OrgChartPage from "../org/OrgChartPage.vue";
import type { OrgChart } from "../org/types";

vi.setConfig({ testTimeout: 20_000 });

beforeAll(() => {
  // Phone width before anything reads the shared breakpoints.
  vi.stubGlobal("matchMedia", (query: string) => ({ matches: query.includes("max-width: 767.98px"), media: query, addEventListener: () => undefined, removeEventListener: () => undefined }));
});

beforeEach(() => {
  mergeModuleMessages("lifecycle", { en, ru: en, uz: en });
});

afterEach(() => {
  document.body.innerHTML = "";
});

const someone = (id: number, name: string, department: number | null) => ({
  id,
  name,
  photo_url: null,
  position_id: 2,
  department_id: department,
  home_branch_id: 1,
  branch_id: 1,
  manager_id: null,
  is_owner: false,
  status: "approved" as const,
  suspended_until: null,
  on_leave_until: null,
  leaving: null,
  change: null,
  may_move: true,
  why_not: null,
});

const data: OrgChart = {
  today: "2026-11-11",
  company: { id: 1, name: "Demo Dorixona" },
  owners: [{ id: 1, name: "Dilnoza Karimova", photo_url: null, position: null }],
  departments: [
    { id: 10, name: "Rahbariyat", parent_id: null, depth: 1, head: null, headcount: 0, total: 2 },
    { id: 11, name: "Chilonzor dorixonasi", parent_id: 10, depth: 2, head: { id: 2, name: "Bekzod Mirzayev", photo_url: null, position: "Mudir" }, headcount: 2, total: 2 },
  ],
  branches: [{ id: 1, name: "Chilonzor", code: "CHL", manager: null, headcount: 2 }],
  positions: [{ id: 2, name: "Farmatsevt", order: 1 }],
  people: [someone(2, "Bekzod Mirzayev", 11), someone(3, "Alisher Valiyev", 11)],
  vacancies: [{ id: 50, title: "Farmatsevt — Chilonzor", position_id: 2, branch_id: 1, department_id: 11, applicants: 0, new: 0 }],
  can: { move: true, decide: true, hiring: true, structure: true },
};

describe("the org chart on a phone", () => {
  it("is an outline: parts fold open to their head, people and places", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => json(data)),
    );
    const app = await testApp("/c/1/lifecycle/org");
    const { wrapper } = mountWithProviders(OrgChartPage, { plugins: app.plugins });
    await flushPromises();
    await flushPromises();

    expect(wrapper.find("[data-org-outline]").exists()).toBe(true);
    expect(wrapper.find(".org-viewport").exists()).toBe(false);
    expect(wrapper.find("[data-org-zoom]").exists()).toBe(false);
    // The top part is open; the part under it starts folded.
    expect(wrapper.find('[data-node="d10"]').exists()).toBe(true);
    expect(wrapper.find('[data-node="d11"] [data-person-id="3"]').exists()).toBe(false);
    await wrapper.find('[data-node="d11"] [data-outline-toggle]').trigger("click");
    expect(wrapper.find('[data-node="d11"] [data-head]').text()).toContain("Bekzod Mirzayev");
    expect(wrapper.find('[data-node="d11"] [data-person-id="3"]').text()).toContain("Alisher Valiyev");
    expect(wrapper.find('[data-node="d11"] [data-vacancy]').text()).toContain("Farmatsevt — Chilonzor");
    expect(wrapper.find('[data-node="d11"] [data-person-menu]').exists()).toBe(true);
    expect(wrapper.text()).toContain(en["lifecycle.org.owner"]);
  });

  it("search opens the way to someone folded away", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => json(data)),
    );
    const app = await testApp("/c/1/lifecycle/org");
    const { wrapper } = mountWithProviders(OrgChartPage, { plugins: app.plugins });
    await flushPromises();
    await flushPromises();
    await wrapper.find("input[data-org-search]").setValue("alisher");
    await flushPromises();
    expect(wrapper.find('[data-node="d11"] [data-person-id="3"]').exists()).toBe(true);
  });
});
