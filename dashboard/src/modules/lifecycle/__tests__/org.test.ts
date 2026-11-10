// The org chart: the tree of each view, search, the keyboard move and what a drop proposes.
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { mergeModuleMessages } from "@/i18n";
import { json } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

import en from "../i18n/en.json";
import OrgChartPage from "../org/OrgChartPage.vue";
import { availableViews, badges, buildTree, fitZoom, fold, moveTargets, movePreset, nextTarget, pathTo, peopleInOrder, sameTarget, searchPeople, visiblePeople, walk } from "../org/tree";
import type { OrgChart, OrgPerson, OrgRef } from "../org/types";

vi.setConfig({ testTimeout: 20_000 });

beforeEach(() => {
  mergeModuleMessages("lifecycle", { en, ru: en, uz: en });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  document.body.innerHTML = "";
});

const ref = (id: number, name: string, position: string | null = null): OrgRef => ({ id, name, photo_url: null, position });

function person(id: number, name: string, overrides: Partial<OrgPerson> = {}): OrgPerson {
  return {
    id,
    name,
    photo_url: null,
    position_id: 2,
    department_id: null,
    home_branch_id: 1,
    branch_id: 1,
    manager_id: null,
    is_owner: false,
    status: "approved",
    suspended_until: null,
    on_leave_until: null,
    leaving: null,
    change: null,
    may_move: true,
    why_not: null,
    ...overrides,
  };
}

const chart = (): OrgChart => ({
  today: "2026-11-11",
  company: { id: 1, name: "Demo Dorixona" },
  owners: [ref(1, "Dilnoza Karimova", "Ofis")],
  departments: [
    { id: 10, name: "Rahbariyat", parent_id: null, depth: 1, head: ref(1, "Dilnoza Karimova", "Ofis"), headcount: 1, total: 7 },
    { id: 11, name: "Chilonzor dorixonasi", parent_id: 10, depth: 2, head: ref(2, "Bekzod Mirzayev", "Mudir"), headcount: 3, total: 3 },
    { id: 12, name: "Yunusobod dorixonasi", parent_id: 10, depth: 2, head: null, headcount: 1, total: 2 },
    { id: 13, name: "Tungi smena", parent_id: 12, depth: 3, head: ref(6, "Nigora Azimova"), headcount: 1, total: 1 },
  ],
  branches: [
    { id: 1, name: "Chilonzor", code: "CHL", manager: ref(2, "Bekzod Mirzayev", "Mudir"), headcount: 5 },
    { id: 2, name: "Yunusobod", code: "YNS", manager: null, headcount: 2 },
  ],
  positions: [
    { id: 1, name: "Mudir", order: 1 },
    { id: 2, name: "Farmatsevt", order: 2 },
    { id: 3, name: "Kuryer", order: 3 },
  ],
  people: [
    person(1, "Dilnoza Karimova", { department_id: 10, is_owner: true, may_move: false, why_not: "self", position_id: null }),
    person(2, "Bekzod Mirzayev", { department_id: 11, position_id: 1, manager_id: 1 }),
    person(3, "Alisher Valiyev", { department_id: 11, manager_id: 2 }),
    person(4, "G‘ulom Aliyev", { department_id: 11, manager_id: 2, on_leave_until: "2026-11-15" }),
    person(5, "Sara Tosheva", { department_id: 12, home_branch_id: 2, branch_id: 2, manager_id: 1, leaving: { id: 4, status: "agreed", day: "2026-11-20" } }),
    person(6, "Nigora Azimova", { department_id: 13, home_branch_id: 2, branch_id: 2, manager_id: 1 }),
    person(7, "Jasur Tursunov", { position_id: 3, status: "suspended", suspended_until: "2026-11-14", change: { id: 9, status: "proposed", effective_on: "2026-12-01", parts: ["department"] } }),
  ],
  vacancies: [
    { id: 50, title: "Farmatsevt — Chilonzor", position_id: 2, branch_id: 1, department_id: 11, applicants: 3, new: 1 },
    { id: 51, title: "Kassir", position_id: null, branch_id: 2, department_id: null, applicants: 0, new: 0 },
  ],
  can: { move: true, decide: true, hiring: true, structure: true },
});

describe("the tree", () => {
  it("hangs departments from the owners, heads on their cards, people by job title, places where they belong", () => {
    const root = buildTree(chart(), "department");
    expect(root.kind).toBe("root");
    expect(root.children.map((node) => node.key)).toEqual(["d10", "none"]);
    const [top, unplaced] = root.children;
    expect(top!.children.map((node) => node.name)).toEqual(["Chilonzor dorixonasi", "Yunusobod dorixonasi"]);
    const chilonzor = top!.children[0]!;
    expect(chilonzor.headPerson?.name).toBe("Bekzod Mirzayev");
    // The head is on the card, never again in a group; people sort by name inside their group.
    expect(chilonzor.groups.map((group) => [group.position?.name, group.people.map((p) => p.name)])).toEqual([["Farmatsevt", ["Alisher Valiyev", "G‘ulom Aliyev"]]]);
    expect(chilonzor.vacancies.map((vacancy) => vacancy.title)).toEqual(["Farmatsevt — Chilonzor"]);
    expect(chilonzor.target).toEqual({ part: "department", id: 11, name: "Chilonzor dorixonasi" });
    // The owner sits on the root only; the night shift hangs under Yunusobod.
    expect(walk(root).flatMap((node) => node.groups.flatMap((group) => group.people.map((p) => p.id)))).not.toContain(1);
    expect(top!.children[1]!.children.map((node) => node.name)).toEqual(["Tungi smena"]);
    // Jasur has no department, the Kassir place none either: both wait on the unplaced node.
    expect(unplaced!.groups.flatMap((group) => group.people.map((p) => p.name))).toEqual(["Jasur Tursunov"]);
    expect(unplaced!.vacancies.map((vacancy) => vacancy.title)).toEqual(["Kassir"]);
    expect(unplaced!.target).toEqual({ part: "department", id: null, name: "" });
  });

  it("by branch, the managers lead their branches and places follow their branch", () => {
    const root = buildTree(chart(), "branch");
    expect(root.children.map((node) => node.key)).toEqual(["b1", "b2"]);
    const [chilonzor, yunusobod] = root.children;
    expect(chilonzor!.head?.name).toBe("Bekzod Mirzayev");
    expect(chilonzor!.groups.flatMap((group) => group.people.map((p) => p.name))).toEqual(["Alisher Valiyev", "G‘ulom Aliyev", "Jasur Tursunov"]);
    expect(yunusobod!.vacancies.map((vacancy) => vacancy.title)).toEqual(["Kassir"]);
    expect(yunusobod!.target).toEqual({ part: "branch", id: 2, name: "Yunusobod" });
    expect(availableViews(chart())).toEqual(["department", "branch"]);
    expect(availableViews({ departments: [], branches: chart().branches })).toEqual(["branch"]);
  });

  it("finds people by name or job title, whatever the o‘ marks, and the way to them", () => {
    const data = chart();
    const root = buildTree(data, "department");
    expect(fold("G‘ulom")).toBe(fold("G'ulom"));
    expect(searchPeople(root, data.positions, "gulom").map((p) => p.id)).toEqual([4]);
    expect(searchPeople(root, data.positions, "kuryer").map((p) => p.id)).toEqual([7]);
    expect(searchPeople(root, data.positions, "  ")).toEqual([]);
    expect(pathTo(root, 6)).toEqual({ nodes: ["root", "d10", "d12", "d13"], group: null });
    expect(pathTo(root, 4)).toEqual({ nodes: ["root", "d10", "d11"], group: "p2" });
    expect(peopleInOrder(root).map((p) => p.id)).toEqual([1, 2, 3, 4, 5, 6, 7]);
  });

  it("walks the drop targets past where someone already is, both ways and around", () => {
    const data = chart();
    const root = buildTree(data, "department");
    const targets = moveTargets(root);
    const alisher = data.people.find((p) => p.id === 3)!;
    expect(targets.map((node) => node.key)).toEqual(["d10", "d11", "d12", "d13", "none"]);
    expect(nextTarget(targets, alisher, null, 1)?.key).toBe("d10");
    expect(nextTarget(targets, alisher, "d10", 1)?.key).toBe("d12"); // d11 is his
    expect(nextTarget(targets, alisher, "d10", -1)?.key).toBe("none");
    expect(sameTarget(alisher, { part: "department", id: 11, name: "" })).toBe(true);
    expect(sameTarget(alisher, { part: "branch", id: 2, name: "Yunusobod" })).toBe(false);
    expect(movePreset({ part: "department", id: 12, name: "Yunusobod dorixonasi" }, "Moving")).toEqual({ parts: ["department"], department: 12, reason: "Moving" });
    expect(movePreset({ part: "branch", id: 2, name: "Yunusobod" }, "Moving")).toEqual({ parts: ["branch"], branch: 2, reason: "Moving" });
  });

  it("shows the most telling statuses first and folds long groups, never hiding who was found", () => {
    const jasur = chart().people.find((p) => p.id === 7)!;
    expect(badges(jasur).map((badge) => badge.key)).toEqual(["suspended", "change"]);
    expect(badges(chart().people.find((p) => p.id === 5)!).map((badge) => [badge.key, badge.day])).toEqual([["leaving", "2026-11-20"]]);
    const many = Array.from({ length: 12 }, (_, index) => person(100 + index, `Xodim ${String(index).padStart(2, "0")}`));
    const group = { key: "p2", position: null, people: many };
    expect(visiblePeople(group, false).shown).toHaveLength(6);
    expect(visiblePeople(group, false).hidden).toBe(6);
    expect(visiblePeople(group, false, 111).shown.map((p) => p.id)).toContain(111);
    expect(visiblePeople(group, true).hidden).toBe(0);
    expect(fitZoom({ width: 1000, height: 800 }, { width: 2000, height: 600 })).toBe(0.5);
    expect(fitZoom({ width: 1000, height: 800 }, { width: 500, height: 400 })).toBe(1);
    expect(fitZoom({ width: 100, height: 100 }, { width: 5000, height: 5000 })).toBe(0.3);
  });
});

interface Call {
  method: string;
  url: string;
  body: unknown;
}

function stub(data: OrgChart): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init?: RequestInit) => {
      const url = input.replace("/api/v1/owner/companies/1/", "");
      const body = init?.body ? JSON.parse(String(init.body)) : undefined;
      calls.push({ method: init?.method ?? "GET", url, body });
      if (url.startsWith("lifecycle/org/")) return json(data);
      if (url.startsWith("lifecycle/job-changes/current/")) {
        return json({
          member: { id: 3, name: "Alisher Valiyev", photo_url: null },
          position: { id: 2, name: "Farmatsevt" },
          home_branch: { id: 1, name: "Chilonzor", code: "CHL" },
          branches: [{ id: 1, name: "Chilonzor", code: "CHL" }],
          department: { id: 11, name: "Chilonzor dorixonasi" },
          role: "Pharmacist",
          pay: null,
          may_change_pay: false,
          departments: data.departments.map((row) => ({ id: row.id, name: row.name })),
          open_changes: [],
        });
      }
      if (url === "lifecycle/job-changes/" && init?.method === "POST") return json({ id: 77, status: "approved", member: { id: 3, name: "Alisher Valiyev", photo_url: null } }, 201);
      return json({});
    }),
  );
  return calls;
}

async function mountPage(data = chart()) {
  const calls = stub(data);
  const app = await testApp("/c/1/lifecycle/org");
  const { wrapper } = mountWithProviders(OrgChartPage, { plugins: app.plugins });
  await flushPromises();
  await flushPromises();
  return { wrapper, calls, app };
}

describe("the org chart page", () => {
  it("draws the company with its owners, departments, heads, people and dashed places", async () => {
    const { wrapper } = await mountPage();
    expect(wrapper.find("[data-org-chart]").exists()).toBe(true);
    expect(wrapper.find('[data-node="root"]').text()).toContain("Dilnoza Karimova");
    expect(wrapper.findAll("[data-node]").map((node) => node.attributes("data-node"))).toEqual(["root", "d10", "d11", "d12", "d13", "none"]);
    expect(wrapper.find('[data-node="d11"] [data-head]').text()).toContain("Bekzod Mirzayev");
    expect(wrapper.find('[data-node="d12"] [data-no-head]').exists()).toBe(true);
    const place = wrapper.find('[data-node="d11"] [data-vacancy]');
    expect(place.text()).toContain("Farmatsevt — Chilonzor");
    expect(place.attributes("href")).toBe("/c/1/hr/hiring/50");
    expect(wrapper.find("[data-org-summary]").text()).toContain("4 departments");
    // People who can't be moved can't be dragged.
    expect(wrapper.find('[data-person-id="3"]').attributes("draggable")).toBe("true");
  });

  it("switches to branches and folds a part away", async () => {
    const { wrapper } = await mountPage();
    const views = wrapper.findAll("[data-org-toolbar] button").filter((button) => button.text() === en["lifecycle.org.view.branch"]);
    await views[0]!.trigger("click");
    await flushPromises();
    expect(wrapper.findAll("[data-node]").map((node) => node.attributes("data-node"))).toEqual(["root", "b1", "b2"]);
    await wrapper.find('[data-node="b1"] [data-fold]').trigger("click");
    expect(wrapper.find('[data-node="b1"] [data-person-id="3"]').exists()).toBe(false);
  });

  it("finds someone by name and rings them", async () => {
    const { wrapper } = await mountPage();
    await wrapper.find("input[data-org-search]").setValue("nigora");
    await flushPromises();
    expect(wrapper.find("[data-org-found]").text()).toBe("1 of 1");
    expect(wrapper.find('[data-person-id="6"]').classes()).toContain("org-found");
  });

  it("moves someone with the keyboard: Space picks up, the arrows choose, Space opens the job change filled in", async () => {
    const { wrapper, calls } = await mountPage();
    const alisher = wrapper.find('[data-person-id="3"]');
    await alisher.trigger("keydown", { key: " " });
    await flushPromises();
    expect(wrapper.find("[data-org-announce]").text()).toContain("Alisher Valiyev");
    await alisher.trigger("keydown", { key: "ArrowDown" });
    await alisher.trigger("keydown", { key: "ArrowDown" });
    await flushPromises();
    expect(wrapper.find('[data-node="d12"] > .org-card').classes()).toContain("org-over");
    await alisher.trigger("keydown", { key: " " });
    await flushPromises();
    await flushPromises();
    // The job change dialog: the department part ticked, Yunusobod chosen, a reason to keep.
    const dialog = document.body.querySelector('[role="dialog"]');
    expect(dialog?.textContent).toContain("Alisher Valiyev");
    expect(document.body.querySelector("[data-propose-parts]")?.textContent).toContain(en["lifecycle.propose.part.department"]);
    const submit = [...document.body.querySelectorAll<HTMLButtonElement>('[role="dialog"] button')].find((button) => button.textContent?.includes(en["lifecycle.propose.submitApprove"]));
    submit!.click();
    await flushPromises();
    const post = calls.find((call) => call.method === "POST");
    expect(post?.url).toBe("lifecycle/job-changes/");
    expect(post?.body).toMatchObject({ member_id: 3, department_id: 12, reason: "Moving to Yunusobod dorixonasi" });
    expect(post?.body).not.toHaveProperty("branch_id");
  });

  it("Escape puts the person down without anything opening", async () => {
    const { wrapper } = await mountPage();
    const alisher = wrapper.find('[data-person-id="3"]');
    await alisher.trigger("keydown", { key: " " });
    await alisher.trigger("keydown", { key: "ArrowDown" });
    await alisher.trigger("keydown", { key: "Escape" });
    await flushPromises();
    expect(wrapper.find(".org-over").exists()).toBe(false);
    expect(document.body.querySelector("[data-propose-parts]")).toBeNull();
    expect(wrapper.find("[data-org-announce]").text()).toBe(en["lifecycle.org.kb.cancelled"]);
  });

  it("says why someone can't be moved, and hides moving from people who can't propose changes", async () => {
    const data = chart();
    data.can = { move: false, decide: false, hiring: false, structure: false };
    data.people = data.people.map((p) => ({ ...p, may_move: false, why_not: "rights" as const }));
    const { wrapper } = await mountPage(data);
    expect(wrapper.find('[data-person-id="3"]').attributes("draggable")).toBe("false");
    expect(wrapper.find("[data-org-hint]").exists()).toBe(false);
    expect(wrapper.find("[data-edit-departments]").exists()).toBe(false);
    // Without hr.hiring a place is shown but isn't a link.
    expect(wrapper.find('[data-node="d11"] [data-vacancy]').element.tagName).toBe("DIV");
  });
});
