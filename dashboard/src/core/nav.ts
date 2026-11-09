/** Builds the sidebar, tab bar and palette "Jump to" list from the registry, for one company. */
import type { Component } from "vue";
import type { RouteRecordRaw } from "vue-router";

import type { Company, Pulse } from "@/api/types";
import { allowed, isModuleVisible } from "@/core/access";
import { MODULE_GROUPS, type DashboardModule, type ModuleGroup, type NavItem } from "@/core/modules";

export interface NavEntry {
  key: string;
  moduleId: string;
  title: string;
  /** Full path, e.g. "/c/12/tasks/reviews". */
  path: string;
  /** Path relative to the company. */
  to: string;
  icon: Component | undefined;
  badge: number;
  exact: boolean;
}

export interface NavModule extends NavEntry {
  group: ModuleGroup;
  hotkey: string | undefined;
  /** Sub-pages when the module has more than one visible nav item. */
  children: NavEntry[];
}

export interface NavGroup {
  id: ModuleGroup;
  modules: NavModule[];
  /** Sum of the module badges, shown on a collapsed group or a phone tab. */
  badge: number;
}

export const EMPTY_PULSE: Pulse = { counters: {}, versions: {} };

export function companyPath(companyId: number, to: string): string {
  const clean = to.replace(/^\/+/, "");
  return clean ? `/c/${companyId}/${clean}` : `/c/${companyId}`;
}

/** The first child path of a module's first route, used when a module declares no `nav`. */
function firstRoutePath(routes: readonly RouteRecordRaw[]): string {
  const first = routes[0];
  if (!first) return "";
  return first.path.replace(/^\/+/, "").replace(/\/:.*$/, "");
}

export function moduleNavItems(module: DashboardModule): NavItem[] {
  if (module.nav) return module.nav;
  return [{ key: module.id, title: module.title, to: firstRoutePath(module.routes) }];
}

function badgeOf(fn: ((pulse: Pulse) => number | undefined) | undefined, pulse: Pulse): number {
  const value = fn?.(pulse);
  return typeof value === "number" && value > 0 ? value : 0;
}

/** One sidebar row of a module: the module itself, or one of its `NavItem.row`s. */
interface RowSpec {
  key: string;
  title: string;
  icon: Component;
  group: ModuleGroup;
  order: number;
  hotkey: string | undefined;
  /** The module's own badge counts on its own row only. */
  own: boolean;
  items: NavItem[];
}

/**
 * A module's rows: everything before its first `row` item is the module's own row, and each `row`
 * item starts a row with the items after it (one row for a module without any).
 */
export function moduleRows(module: DashboardModule): RowSpec[] {
  const rows: RowSpec[] = [];
  let current: RowSpec = { key: module.id, title: module.title, icon: module.icon, group: module.group, order: module.order, hotkey: module.hotkey, own: true, items: [] };
  rows.push(current);
  for (const item of moduleNavItems(module)) {
    if (item.row) {
      current = { key: item.row.key, title: item.row.title, icon: item.row.icon, group: item.row.group, order: item.row.order, hotkey: item.row.hotkey, own: false, items: [] };
      rows.push(current);
    }
    current.items.push(item);
  }
  return rows.filter((row) => row.items.length > 0);
}

export function buildNav(list: readonly DashboardModule[], company: Company | null | undefined, pulse: Pulse = EMPTY_PULSE): NavGroup[] {
  if (!company) return [];
  const groups = new Map<ModuleGroup, Array<NavModule & { order: number }>>();
  for (const module of list) {
    if (!isModuleVisible(module, company)) continue;
    for (const row of moduleRows(module)) {
      const items = row.items.filter((item) => allowed(company, item));
      if (items.length === 0) continue;
      const children: NavEntry[] = items.map((item) => ({
        key: `${module.id}:${item.key}`,
        moduleId: module.id,
        title: item.title,
        to: item.to,
        path: companyPath(company.id, item.to),
        icon: item.icon,
        badge: badgeOf(item.badge, pulse),
        exact: item.exact ?? item.to === "",
      }));
      const head = children[0]!;
      const own = row.own ? badgeOf(module.badge, pulse) : 0;
      const entry: NavModule & { order: number } = {
        key: row.key,
        moduleId: module.id,
        group: row.group,
        title: row.title,
        to: head.to,
        path: head.path,
        icon: row.icon,
        hotkey: row.hotkey,
        exact: head.to === "",
        badge: own || children.reduce((sum, child) => sum + child.badge, 0),
        children: children.length > 1 ? children : [],
        order: row.order,
      };
      const bucket = groups.get(row.group) ?? [];
      bucket.push(entry);
      groups.set(row.group, bucket);
    }
  }
  return MODULE_GROUPS.filter((id) => groups.has(id)).map((id) => {
    // Stable: modules arrive in registry order, so rows of equal order keep it.
    const modulesInGroup: NavModule[] = groups
      .get(id)!
      .sort((a, b) => a.order - b.order)
      .map(({ order: _order, ...entry }) => entry);
    return { id, modules: modulesInGroup, badge: modulesInGroup.reduce((sum, m) => sum + m.badge, 0) };
  });
}

/** Whether `path` is inside the entry (exact entries only match themselves). */
export function isActivePath(entry: Pick<NavEntry, "path" | "exact">, path: string): boolean {
  const current = path.replace(/\/+$/, "");
  if (entry.exact) return current === entry.path;
  return current === entry.path || current.startsWith(`${entry.path}/`);
}

/** The most specific entry that contains `path`, so only one row lights up (a sub-page when there is one). */
export function activeEntryKey(groups: readonly NavGroup[], path: string): string | undefined {
  let best: { key: string; length: number } | undefined;
  for (const group of groups) {
    for (const module of group.modules) {
      for (const entry of [module, ...module.children]) {
        // ">=": on a tie the sub-page wins over its module row, which shares the first path.
        if (isActivePath(entry, path) && (!best || entry.path.length >= best.length)) {
          best = { key: entry.key, length: entry.path.length };
        }
      }
    }
  }
  return best?.key;
}
