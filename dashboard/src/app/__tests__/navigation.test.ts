import { describe, expect, it } from "vitest";
import { defineComponent, h } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";

import { safeNext } from "@/app/guards";
import { companyUrl } from "@/lib/links";
import { pathInCompany } from "@/app/navigation";
import { buildRoutes, stampModule } from "@/app/router";
import { defineModule } from "@/core/modules";
import { resolveStartParam, launchedFromTelegram } from "@/shell/TelegramBridge";

const Page = defineComponent({ render: () => h("div") });
const Icon = defineComponent({ render: () => h("svg") });

const people = defineModule({
  id: "people",
  group: "people",
  order: 10,
  icon: Icon,
  title: "people.title",
  routes: [
    { path: "people", name: "people.list", component: Page },
    { path: "people/:memberId/:tab?", name: "people.person", component: Page },
  ],
  deepLinks: { member: (id) => `people/${id}` },
  messages: () => Promise.resolve({ uz: {}, ru: {}, en: {} }),
});
const auth = defineModule({
  id: "auth",
  group: "company",
  order: 0,
  icon: Icon,
  title: "auth.title",
  routes: [],
  publicRoutes: [{ path: "/login", name: "login", component: Page }],
  messages: () => Promise.resolve({ uz: {}, ru: {}, en: {} }),
});

function router() {
  return createRouter({ history: createMemoryHistory(), routes: buildRoutes([people, auth]) });
}

describe("buildRoutes", () => {
  it("puts module routes under /c/:companyId with the module stamped in meta", () => {
    const r = router();
    const resolved = r.resolve("/c/4/people/17/pay");
    expect(resolved.name).toBe("people.person");
    expect(resolved.params).toMatchObject({ companyId: "4", memberId: "17", tab: "pay" });
    expect(resolved.matched.at(-1)!.meta.module).toBe("people");
    expect(r.resolve("/login").matched.at(-1)!.meta).toMatchObject({ public: true, module: "auth" });
    expect(r.resolve("/c/4/nope").name).toBe("company-not-found");
    expect(r.resolve("/nope").name).toBe("not-found");
    expect(r.resolve("/c/abc").name).toBe("not-found");
  });

  it("gets /login and, in development, /dev/login from the real auth module", async () => {
    const { modules } = await import("@/core/modules");
    const r = createRouter({ history: createMemoryHistory(), routes: buildRoutes(modules) });
    expect(r.resolve("/login").matched.at(-1)!.meta).toMatchObject({ public: true, module: "auth" });
    expect(r.resolve("/dev/login").name).toBe("dev-login");
    // The overview serves the company index, so no redirect stand-in is added.
    expect(r.resolve("/c/1").name).toBe("overview.today");
  });

  it("stamps nested children too", () => {
    const stamped = stampModule({ path: "x", component: Page, children: [{ path: "y", component: Page }] }, "m");
    expect(stamped.meta?.module).toBe("m");
    expect(stamped.children?.[0]?.meta?.module).toBe("m");
  });
});

describe("pathInCompany", () => {
  it("keeps the page but drops ids and the query", async () => {
    const r = router();
    await r.push("/c/1/people/17/pay?tab=x");
    expect(pathInCompany(r, r.currentRoute.value, 2)).toBe("/c/2/people");
    await r.push("/c/1/people?q=madina");
    expect(pathInCompany(r, r.currentRoute.value, 2)).toBe("/c/2/people");
    await r.push("/c/1/unknown");
    expect(pathInCompany(r, r.currentRoute.value, 2)).toBe("/c/2");
  });
});

describe("safeNext", () => {
  it("accepts only same-app paths", () => {
    expect(safeNext("/c/1/tasks?view=board")).toBe("/c/1/tasks?view=board");
    expect(safeNext("https://evil.example")).toBe("/");
    expect(safeNext("//evil.example")).toBe("/");
    expect(safeNext("/\\evil")).toBe("/");
    expect(safeNext(["/c/2"])).toBe("/c/2");
    expect(safeNext(undefined)).toBe("/");
  });
});

describe("companyUrl", () => {
  it("turns server links into in-app paths and never leaves the app", () => {
    expect(companyUrl(3, "/c/3/sales/shifts/4")).toBe("/c/3/sales/shifts/4");
    expect(companyUrl(3, "/dashboard/c/3/tasks?task=9")).toBe("/c/3/tasks?task=9");
    expect(companyUrl(3, "tasks?task=9")).toBe("/c/3/tasks?task=9");
    expect(companyUrl(3, "/people/17")).toBe("/c/3/people/17");
    expect(companyUrl(3, "")).toBe("/c/3");
    expect(companyUrl(3, null)).toBe("/c/3");
    expect(companyUrl(3, "https://evil.example/x")).toBe("/c/3");
    expect(companyUrl(3, "javascript:alert(1)")).toBe("/c/3");
    expect(companyUrl(3, "//evil.example")).toBe("/c/3");
    expect(companyUrl(null, "people")).toBe("/people");
  });
});

describe("Telegram", () => {
  it("routes startapp parameters", () => {
    expect(resolveStartParam("approvals", 3, [people])).toEqual({ path: "/c/3", query: { inbox: "needs" } });
    expect(resolveStartParam("member_17", 3, [people])).toBe("/c/3/people/17");
    expect(resolveStartParam("shift_1042", 3, [people])).toBe("/c/3");
    expect(resolveStartParam(null, 3, [people])).toBeNull();
  });

  it("detects a Telegram launch from the URL hash", () => {
    expect(launchedFromTelegram("#tgWebAppData=query_id%3D1&tgWebAppVersion=8.0")).toBe(true);
    expect(launchedFromTelegram("#section")).toBe(false);
  });
});
