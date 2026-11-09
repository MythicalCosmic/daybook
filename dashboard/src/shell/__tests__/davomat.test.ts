/**
 * The shell in the Davomat edition: the organization's brand instead of the company switcher, no
 * group headings, Davomat's own phone tabs, and breadcrumbs that follow the sidebar row a page is
 * in (one module brings Overview, Team and Settings).
 */
// The registry first, as in the app.
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { DAYBOOK_INFO, normalizeEdition, setEditionInfo } from "@/core/edition";
import { applyEdition, modules } from "@/core/modules";
import { buildNav } from "@/core/nav";
import { ensureAllModuleMessages } from "@/i18n";
import { company } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

import MobileTabBar from "../MobileTabBar.vue";
import SideNav from "../SideNav.vue";

const owner = company({ name: "Namuna MChJ", features: ["attendance", "face_id"] });

beforeEach(async () => {
  setEditionInfo(normalizeEdition({ edition: "davomat", product: "Davomat", organization: { name: "Namuna MChJ", logo_url: null }, needs_setup: false }));
  applyEdition("davomat");
  await ensureAllModuleMessages(modules, "en");
});

afterEach(() => {
  setEditionInfo(DAYBOOK_INFO);
  applyEdition("daybook");
  document.body.innerHTML = "";
});

describe("Davomat's shell", () => {
  it("puts Overview, Team and Settings in their own rows, Face ID beside them", () => {
    const nav = buildNav(modules, owner);
    const rows = nav.flatMap((group) => group.modules.map((row) => row.key));
    expect(rows[0]).toBe("davomat");
    expect(rows).toContain("faceid");
    expect(rows).toContain("davomat.team");
    expect(rows[rows.length - 1]).toBe("davomat.settings");
    const team = nav.flatMap((group) => group.modules).find((row) => row.key === "davomat.team")!;
    expect(team.children.map((child) => child.to)).toEqual(["team", "team/departments", "team/positions", "team/branches"]);
  });

  it("shows the organization instead of a company switcher, and no group headings", async () => {
    const app = await testApp("/c/1");
    const groups = buildNav(modules, owner);
    const { wrapper } = mountWithProviders(SideNav, { plugins: app.plugins, props: { groups, rail: false, ready: true, canCollapse: true } });
    await flushPromises();
    // The company the person is in (the one organization), with the product under it.
    expect(wrapper.find("[data-testid=edition-brand]").text()).toContain(company().name);
    expect(wrapper.find("[data-testid=edition-brand]").text()).toContain("Davomat");
    expect(wrapper.findAll("nav h2")).toHaveLength(0);
    wrapper.unmount();
  });

  it("gives phones Davomat's own tabs and marks the one a page belongs to", async () => {
    const app = await testApp("/c/1/team/departments");
    const groups = buildNav(modules, owner);
    const { wrapper } = mountWithProviders(MobileTabBar, { plugins: app.plugins, props: { groups, moreOpen: false } });
    await flushPromises();
    const tabs = wrapper.findAll("a").map((link) => link.attributes("href"));
    expect(tabs[0]).toBe("/c/1");
    expect(tabs).toContain("/c/1/team");
    expect(tabs).toContain("/c/1/faceid");
    expect(wrapper.find('a[aria-current="page"]').attributes("href")).toBe("/c/1/team");
    wrapper.unmount();
  });
});
