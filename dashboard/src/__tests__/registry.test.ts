/**
 * The module registry contract (plan §6.6) and the information architecture in core/catalog.ts.
 * Real modules (src/modules/<id>/index.ts) are checked here as they land; the dev placeholders
 * built from the catalog go through the same checks, so the checker itself is always exercised.
 */
import { describe, expect, it } from "vitest";
import { createMemoryHistory, createRouter, type RouteRecordRaw } from "vue-router";

import { buildRoutes } from "@/app/router";
import { CATALOG, CATALOG_HEADLESS, catalogEntry } from "@/core/catalog";
import { FEATURES } from "@/core/features";
import { EXTENSION_POINTS, MODULE_GROUPS, modules, type DashboardModule } from "@/core/modules";
import { moduleNavItems } from "@/core/nav";
import { PERMS, isPerm, type PermRequirement } from "@/core/perms";
import { devStubModules } from "@/dev/stubModules";

const discovered = import.meta.glob<{ default: DashboardModule }>("../modules/*/index.ts", { eager: true });

function permsOf(required: PermRequirement | undefined): string[] {
  if (required === undefined) return [];
  return typeof required === "string" ? [required] : [...required];
}

function flatRoutes(routes: readonly RouteRecordRaw[], parent = ""): Array<{ path: string; record: RouteRecordRaw }> {
  return routes.flatMap((route) => {
    const path = route.path.startsWith("/") ? route.path : [parent, route.path].filter(Boolean).join("/");
    return [{ path, record: route }, ...flatRoutes(route.children ?? [], path)];
  });
}

/** Contract problems for one module. */
export function moduleProblems(module: DashboardModule, folder?: string): string[] {
  const problems: string[] = [];
  const say = (text: string) => problems.push(`${module.id}: ${text}`);
  if (folder && folder !== module.id) say(`id must equal its folder name "${folder}"`);
  if (!/^[a-z][a-z0-9]*$/.test(module.id)) say("id must be lowercase letters and digits");
  if (!MODULE_GROUPS.includes(module.group)) say(`unknown group "${module.group}"`);
  if (!module.title.startsWith(`${module.id}.`)) say(`title key "${module.title}" must start with "${module.id}."`);
  for (const perm of permsOf(module.perm)) if (!isPerm(perm)) say(`unknown permission "${perm}"`);
  if (module.feature && !(FEATURES as readonly string[]).includes(module.feature)) say(`unknown feature "${module.feature}"`);

  const entry = catalogEntry(module.id);
  if (entry) {
    if (entry.group !== module.group) say(`group "${module.group}" differs from the catalog's "${entry.group}"`);
    if (entry.order !== module.order) say(`order ${module.order} differs from the catalog's ${entry.order}`);
  } else if (!CATALOG_HEADLESS.includes(module.id)) {
    say("is not in core/catalog.ts: add it there (W0) so the sidebar order is decided in one place");
  }

  const routes = flatRoutes(module.routes);
  for (const { path, record } of routes) {
    if (path.startsWith("/")) say(`route "${path}" must be relative to /c/:companyId`);
    if (record.name !== undefined && !String(record.name).startsWith(`${module.id}.`) && String(record.name) !== module.id) {
      say(`route name "${String(record.name)}" must start with "${module.id}."`);
    }
    for (const perm of permsOf(record.meta?.perm)) if (!isPerm(perm)) say(`route "${path}" has unknown permission "${perm}"`);
    if (record.meta?.title && !record.meta.title.startsWith(`${module.id}.`) && !record.meta.title.startsWith("common.")) {
      say(`route "${path}" title key "${record.meta.title}" is outside the module's namespace`);
    }
  }
  const paths = new Set(routes.map((r) => r.path.replace(/\/:.*$/, "")));
  for (const item of moduleNavItems(module)) {
    if (!paths.has(item.to)) say(`nav item "${item.id}" points to "${item.to}", which no route of the module serves`);
    for (const perm of permsOf(item.perm)) if (!isPerm(perm)) say(`nav item "${item.id}" has unknown permission "${perm}"`);
  }
  if (module.hotkey && !/^[a-z,.]$/.test(module.hotkey)) say(`hotkey "${module.hotkey}" must be one key`);
  for (const point of Object.keys(module.extensions ?? {})) {
    if (!(EXTENSION_POINTS as readonly string[]).includes(point)) say(`unknown extension point "${point}"`);
  }
  for (const widget of module.widgets ?? []) {
    if (!widget.id.startsWith(`${module.id}.`)) say(`widget id "${widget.id}" must start with "${module.id}."`);
  }
  for (const panel of module.settings ?? []) if (!panel.title.startsWith(`${module.id}.`)) say(`settings panel "${panel.id}" title is outside the namespace`);
  for (const tab of module.personTabs ?? []) if (!tab.title.startsWith(`${module.id}.`)) say(`person tab "${tab.id}" title is outside the namespace`);
  if (module.publicRoutes?.length && module.id !== "auth") say("only the auth module may bring public routes");
  return problems;
}

async function messageProblems(module: DashboardModule): Promise<string[]> {
  const messages = await module.messages();
  const problems: string[] = [];
  for (const lang of ["uz", "ru", "en"] as const) {
    const dict = messages[lang] ?? {};
    for (const key of Object.keys(dict)) if (!key.startsWith(`${module.id}.`)) problems.push(`${module.id}: ${lang} key "${key}" is outside the namespace`);
    if (!dict[module.title]) problems.push(`${module.id}: ${lang} has no text for its title "${module.title}"`);
  }
  return problems;
}

function registryProblems(list: readonly DashboardModule[]): string[] {
  const problems: string[] = [];
  const ids = list.map((m) => m.id);
  for (const id of new Set(ids)) if (ids.filter((x) => x === id).length > 1) problems.push(`duplicate module id "${id}"`);
  const hotkeys = list.filter((m) => m.hotkey).map((m) => m.hotkey!);
  for (const key of new Set(hotkeys)) if (hotkeys.filter((x) => x === key).length > 1) problems.push(`hotkey "g ${key}" is used twice`);
  try {
    const router = createRouter({ history: createMemoryHistory(), routes: buildRoutes(list) });
    const names = router.getRoutes().map((r) => r.name).filter((n) => n !== undefined);
    for (const name of new Set(names)) if (names.filter((n) => n === name).length > 1) problems.push(`duplicate route name "${String(name)}"`);
    for (const module of list) {
      for (const item of moduleNavItems(module)) {
        const resolved = router.resolve(`/c/1/${item.to}`.replace(/\/$/, ""));
        if (!resolved.matched.length || resolved.matched.some((r) => r.path.includes("pathMatch"))) {
          problems.push(`${module.id}: nav "${item.to}" does not resolve to a page`);
        }
      }
    }
  } catch (error) {
    problems.push(`the router could not be built: ${String(error)}`);
  }
  return problems;
}

describe("permissions", () => {
  it("are unique codenames covering the plan's §5 and §13 additions", () => {
    expect(new Set(PERMS).size).toBe(PERMS.length);
    for (const perm of PERMS) expect(perm).toMatch(/^[a-z_]+\.[a-z_]+$/);
    expect(PERMS).toHaveLength(14 + 27 + 14);
    for (const perm of ["dashboard.access", "payroll.finalize", "hr.sensitive", "projects.view_all", "hr.terminate", "invoices.manage"]) {
      expect(PERMS).toContain(perm);
    }
  });
});

describe("catalog", () => {
  it("is internally consistent", () => {
    const problems: string[] = [];
    const ids = CATALOG.map((e) => e.id);
    expect(new Set(ids).size).toBe(ids.length);
    const orders = CATALOG.map((e) => `${e.group}:${e.order}`);
    expect(new Set(orders).size).toBe(orders.length);
    const pages = CATALOG.flatMap((e) => e.pages.map((p) => p.to));
    expect(new Set(pages).size).toBe(pages.length);
    const hotkeys = CATALOG.filter((e) => e.hotkey).map((e) => e.hotkey);
    expect(new Set(hotkeys).size).toBe(hotkeys.length);
    for (const entry of CATALOG) {
      if (!MODULE_GROUPS.includes(entry.group)) problems.push(`${entry.id}: group`);
      for (const perm of [...permsOf(entry.perm), ...entry.pages.flatMap((p) => permsOf(p.perm))]) if (!isPerm(perm)) problems.push(`${entry.id}: ${perm}`);
      for (const feature of [entry.feature, ...entry.pages.map((p) => p.feature)]) {
        if (feature && !(FEATURES as readonly string[]).includes(feature)) problems.push(`${entry.id}: feature ${feature}`);
      }
      if (entry.pages.length === 0) problems.push(`${entry.id}: no pages`);
    }
    expect(problems).toEqual([]);
  });

  it("places the owner's additions where the plan asks (§13)", () => {
    expect(catalogEntry("projects")?.group).toBe("work");
    expect(catalogEntry("agenda")?.group).toBe("comms");
    expect(catalogEntry("knowledge")?.group).toBe("comms");
    expect(catalogEntry("crm")?.group).toBe("money");
    for (const id of ["lifecycle", "hiring", "assets", "reviews"]) expect(catalogEntry(id)?.group).toBe("people");
  });
});

describe("registry", () => {
  it("real modules honour the contract", async () => {
    const problems: string[] = [];
    for (const [path, mod] of Object.entries(discovered)) {
      const folder = /modules\/([^/]+)\/index\.ts$/.exec(path)?.[1];
      problems.push(...moduleProblems(mod.default, folder));
      problems.push(...(await messageProblems(mod.default)));
    }
    problems.push(...registryProblems(modules));
    expect(problems).toEqual([]);
  });

  it("the catalog's placeholders honour the same contract", async () => {
    const stubs = devStubModules();
    expect(stubs.map((m) => m.id)).toEqual(CATALOG.map((e) => e.id));
    const problems = stubs.flatMap((m) => moduleProblems(m));
    for (const stub of stubs) problems.push(...(await messageProblems(stub)));
    problems.push(...registryProblems(stubs));
    expect(problems).toEqual([]);
  });

  it("the checker catches broken modules", () => {
    const [first] = devStubModules();
    const broken: DashboardModule = {
      ...first!,
      id: "Bad-Id",
      order: 99,
      title: "other.title",
      perm: "money.print" as never,
      routes: [{ path: "/absolute", name: "wrong.name", component: {} }],
      extensions: { "nowhere.slot": [] } as never,
    };
    const problems = moduleProblems(broken, "bad");
    expect(problems.length).toBeGreaterThanOrEqual(7);
  });
});
