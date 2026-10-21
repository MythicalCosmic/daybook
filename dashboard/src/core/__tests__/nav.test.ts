import { describe, expect, it } from "vitest";
import { defineComponent, h } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";

import { canAccessRecords, isModuleVisible } from "@/core/access";
import { extensionsFor, hasExtension } from "@/core/extensions";
import { byGroupThenOrder, defineModule, type DashboardModule } from "@/core/modules";
import { activeEntryKey, buildNav, companyPath, isActivePath, moduleNavItems } from "@/core/nav";
import { hasPerm, isPerm, permArea } from "@/core/perms";
import { changedKeys, changedVersions, counter, keyMatches, modulesToRefresh, pulseCount } from "@/core/pulse";
import { company, manager } from "@/test/fixtures";

const Icon = defineComponent({ render: () => h("svg") });
const Page = defineComponent({ render: () => h("div") });
const Slot = defineComponent({ render: () => h("span") });
const messages = () => Promise.resolve({});

const tasks = defineModule({
  id: "tasks",
  group: "work",
  order: 10,
  icon: Icon,
  title: "tasks.title",
  routes: [
    { path: "tasks", name: "tasks.list", component: Page },
    { path: "tasks/reviews", name: "tasks.reviews", component: Page, meta: { perm: "tasks.confirm" } },
  ],
  nav: [
    { key: "all", title: "tasks.nav.all", to: "tasks" },
    { key: "reviews", title: "tasks.nav.reviews", to: "tasks/reviews", perm: "tasks.confirm", badge: counter("tasks.review") },
  ],
  invalidates: ["tasks"],
  extensions: { "tasks.toolbar": [Slot] },
  messages,
});
const finance = defineModule({
  id: "finance",
  group: "money",
  order: 30,
  icon: Icon,
  title: "finance.title",
  perm: ["finance.view", "finance.record"],
  feature: "finance",
  routes: [{ path: "finance", name: "finance.overview", component: Page }],
  badge: counter("finance.claims", "finance.overdue"),
  invalidates: ["finance", "sales"],
  extensions: { "tasks.toolbar": [Slot] },
  messages,
});
const overview = defineModule({
  id: "overview",
  group: "overview",
  order: 10,
  icon: Icon,
  title: "overview.title",
  index: true,
  routes: [{ path: "", name: "overview", component: Page }],
  messages,
});
const all: DashboardModule[] = [finance, tasks, overview].sort(byGroupThenOrder);
const pulse = { counters: { "tasks.review": 2, "finance.claims": 1, "finance.overdue": 3 }, versions: {} };

describe("perms", () => {
  it("owners hold everything, others what they were given", () => {
    const owner = company();
    const distributor = manager(["sales.view"]);
    expect(hasPerm(owner, "payroll.finalize")).toBe(true);
    expect(hasPerm(distributor, "sales.view")).toBe(true);
    expect(hasPerm(distributor, ["finance.view", "sales.view"])).toBe(true);
    expect(hasPerm(distributor, "finance.view")).toBe(false);
    expect(hasPerm(distributor, [])).toBe(true);
    expect(hasPerm(null, undefined)).toBe(false);
    expect(isPerm("crm.manage")).toBe(true);
    expect(isPerm("crm.delete")).toBe(false);
    expect(permArea("time_off.manage")).toBe("time_off");
  });
});

describe("buildNav", () => {
  it("sorts groups and filters by permission and feature switch", () => {
    expect(all.map((m) => m.id)).toEqual(["overview", "tasks", "finance"]);
    const nav = buildNav(all, company(), pulse);
    expect(nav.map((g) => g.id)).toEqual(["overview", "work", "money"]);
    const distributor = buildNav(all, manager(["finance.view"], { features: ["sales"] }), pulse);
    expect(distributor.map((g) => g.id)).toEqual(["overview", "work"]);
    // Without tasks.confirm the Reviews page disappears and Tasks becomes a single item.
    expect(distributor[1]!.modules[0]!.children).toEqual([]);
    expect(isModuleVisible(finance, manager(["finance.record"]))).toBe(true);
    expect(buildNav(all, null)).toEqual([]);
  });

  it("adds badges from pulse, summing sub-pages into the module and group", () => {
    const nav = buildNav(all, company(), pulse);
    const work = nav.find((g) => g.id === "work")!;
    expect(work.modules[0]!.children.map((c) => c.badge)).toEqual([0, 2]);
    expect(work.modules[0]!.badge).toBe(2);
    expect(nav.find((g) => g.id === "money")!.badge).toBe(4);
    expect(pulseCount(pulse, "nothing")).toBe(0);
  });

  it("builds full paths and finds the active row", () => {
    const nav = buildNav(all, company({ id: 12 }), pulse);
    expect(nav[0]!.modules[0]!.path).toBe("/c/12");
    expect(activeEntryKey(nav, "/c/12/tasks/reviews")).toBe("tasks:reviews");
    expect(activeEntryKey(nav, "/c/12/tasks")).toBe("tasks:all");
    expect(activeEntryKey(nav, "/c/12/tasks/archive")).toBe("tasks:all");
    expect(activeEntryKey(nav, "/c/12")).toBe("overview");
    expect(activeEntryKey(nav, "/c/12/finance")).toBe("finance");
    expect(isActivePath({ path: "/c/12", exact: true }, "/c/12/tasks")).toBe(false);
    expect(companyPath(3, "/people/")).toBe("/c/3/people/");
    expect(moduleNavItems(finance)).toEqual([{ key: "finance", title: "finance.title", to: "finance" }]);
    expect(moduleNavItems({ ...finance, nav: [] })).toEqual([]);
  });
});

describe("access", () => {
  it("checks module visibility and every matched record's meta", async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: "/c/:companyId", component: Page, children: [{ path: "finance", component: Page, meta: { module: "finance" } }] },
        { path: "/c/:companyId/reviews", component: Page, meta: { module: "tasks", perm: "tasks.confirm" } },
      ],
    });
    // findModule reads the global registry, which is empty in tests: only meta perms apply here.
    const reviews = router.resolve("/c/1/reviews").matched;
    expect(canAccessRecords(reviews, manager([]))).toBe(false);
    expect(canAccessRecords(reviews, manager(["tasks.confirm"]))).toBe(true);
    expect(canAccessRecords(reviews, null)).toBe(false);
  });
});

describe("extensions", () => {
  it("collects components from visible modules only", () => {
    expect(extensionsFor("tasks.toolbar", company(), all).map((e) => e.moduleId)).toEqual(["tasks", "finance"]);
    expect(extensionsFor("tasks.toolbar", manager([]), all).map((e) => e.moduleId)).toEqual(["tasks"]);
    expect(hasExtension("shell.panel", company(), all)).toBe(false);
  });
});

describe("pulse", () => {
  it("finds changed versions and the modules to refresh", () => {
    expect(changedVersions(null, { tasks: "2" })).toEqual([]);
    expect(changedVersions({ tasks: "1", sales: "4" }, { tasks: "2", sales: "4", hr: "1" })).toEqual(["tasks", "hr"]);
    expect(modulesToRefresh(["sales"], all)).toEqual(["finance"]);
    expect(modulesToRefresh(["tasks", "finance"], all)).toEqual(["tasks", "finance"]);
    expect(modulesToRefresh([], all)).toEqual([]);
  });

  it("treats a moved counter as a change and lets an entry name a whole app", () => {
    const before = { counters: { "console.queue": 3, "inbox.unread": 1 }, versions: { "inbox.unread": "4", "tasks.tasks": "1" } };
    expect(changedKeys(null, before)).toEqual([]);
    // A new approval bumps no version of its own; only the queue counter moves.
    expect(changedKeys(before, { ...before, counters: { ...before.counters, "console.queue": 4 } })).toEqual(["console.queue"]);
    expect(changedKeys(before, { counters: { "inbox.unread": 1 }, versions: { ...before.versions, "tasks.tasks": "2" } }).sort()).toEqual(["console.queue", "tasks.tasks"]);
    expect(keyMatches("sales", "sales.shifts")).toBe(true);
    expect(keyMatches("sales", "salesforce")).toBe(false);
    expect(keyMatches("inbox.unread", "inbox.unread")).toBe(true);
    // "tasks" (an app) covers the backend's "tasks.review" key; "finance" covers "finance.transactions".
    expect(modulesToRefresh(["tasks.review"], all)).toEqual(["tasks"]);
    expect(modulesToRefresh(["finance.transactions"], all)).toEqual(["finance"]);
  });
});
