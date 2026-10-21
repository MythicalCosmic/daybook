/**
 * The module registry: the contract module engineers code against (plan §6.6).
 *
 * A module is a folder `src/modules/<id>/` whose `index.ts` default-exports `defineModule({...})`.
 * The shell discovers every module at build time, builds the router and the navigation from them,
 * and asks them for palette commands, Overview widgets, settings panels, Person 360 tabs, inbox
 * renderers and extension-slot components. Modules never import each other or the shell.
 */
import type { Component } from "vue";
import type { RouteLocationRaw, RouteRecordRaw, Router } from "vue-router";

import type { Company, Language, Pulse, Range } from "@/api/types";
import type { CompanyFeature } from "@/core/features";
import type { Perm, PermRequirement } from "@/core/perms";

export type ModuleGroup = "overview" | "work" | "people" | "money" | "comms" | "insights" | "company";

/** Sidebar group order. */
export const MODULE_GROUPS: readonly ModuleGroup[] = [
  "overview",
  "work",
  "people",
  "money",
  "comms",
  "insights",
  "company",
];

export type Messages = Record<string, string>;
export type ModuleMessages = Record<Language, Messages>;
/**
 * One language's dictionary, loaded when that language is needed: a JSON module
 * (`(language) => import(`./i18n/${language}.json`)`, one chunk per language) or a plain object.
 */
export type ModuleMessagesLoader = (language: Language) => Promise<Messages | { default: Messages }>;

export interface NavItem {
  /** Unique within the module (registry.test.ts). */
  key: string;
  /** i18n key. */
  title: string;
  /** Path relative to `/c/:companyId` ("" is the company index). */
  to: string;
  icon?: Component;
  perm?: PermRequirement;
  feature?: CompanyFeature;
  badge?: (pulse: Pulse) => number | undefined;
  /** Highlight only on an exact path match (default: also on child paths). */
  exact?: boolean;
}

export interface CommandCtx {
  companyId: number;
  company: Company;
  router: Router;
  t: (key: string, params?: Record<string, unknown>) => string;
  can: (perm?: PermRequirement) => boolean;
  /** Navigate to a path relative to the current company. */
  go: (to: string) => void;
}

export interface Command {
  id: string;
  /** Already translated: commands are built with `ctx.t`. */
  title: string;
  subtitle?: string;
  icon?: Component;
  keywords?: string[];
  /** Displayed hint, e.g. ["N"] or ["mod", "shift", "E"]. Binding it is the module's job. */
  shortcut?: string[];
  perm?: PermRequirement;
  run: () => void | Promise<void>;
}

export type WidgetSpan = 1 | 2 | 3 | 4;

export interface WidgetProps {
  companyId: number;
  range: Range;
  compare: Range | null;
}

export interface Widget {
  id: string;
  span: WidgetSpan;
  order: number;
  perm?: PermRequirement;
  feature?: CompanyFeature;
  kind: "kpi" | "card" | "chart";
  /** Receives WidgetProps. Use defineAsyncComponent so Overview stays small. */
  component: Component;
}

export interface SettingsPanel {
  id: string;
  /** i18n key. */
  title: string;
  perm?: PermRequirement;
  feature?: CompanyFeature;
  order?: number;
  icon?: Component;
  component: Component;
}

export interface PersonTab {
  id: string;
  /** i18n key. */
  title: string;
  perm?: PermRequirement;
  feature?: CompanyFeature;
  order?: number;
  /** Receives the prop `memberId: number`. */
  component: Component;
}

/** Places where one module renders components that other modules provide (plan §6.6). */
export const EXTENSION_POINTS = [
  "shell.panel",
  "shell.topbar.end",
  /** Top of the sidebar: package A's "Get started" progress pill (§6.1). */
  "shell.nav.top",
  /** Body of the "New company" dialog the company switcher opens (package A, §13.2). */
  "shell.company.create",
  "overview.hero",
  "tasks.toolbar",
  "tasks.drawer.actions",
  "people.profile.actions",
  "comms.composer.tools",
  "finance.quickadd.receipt",
  "finance.transactions.toolbar",
  "sales.shift.detail",
  "payroll.run.toolbar",
] as const;

export type ExtensionPoint = (typeof EXTENSION_POINTS)[number];

/** Turns a Telegram `startapp` argument into a route ("shift_1042" → "sales/shifts/1042"). */
export type DeepLinkResolver = (argument: string) => string | RouteLocationRaw | null;

export interface DashboardModule {
  /** Folder name and i18n namespace: "finance". */
  id: string;
  group: ModuleGroup;
  order: number;
  icon: Component;
  /** i18n key. */
  title: string;
  /** Visible when the member has any of these. */
  perm?: PermRequirement;
  /** `Company.features` switch. */
  feature?: CompanyFeature;
  /** Serves `/c/:companyId` itself with a route whose path is "" (only the overview module). */
  index?: boolean;
  /** Children of `/c/:companyId`, lazy components, `meta: { perm, feature, title }`. */
  routes: RouteRecordRaw[];
  /** Only the auth module: routes outside the shell that need no session (`/login`). */
  publicRoutes?: RouteRecordRaw[];
  /** Signed-in routes outside any company, rendered in the shell without the sidebar (`/portfolio`). */
  rootRoutes?: RouteRecordRaw[];
  /** Default: one item to the first route. `[]` keeps the module out of the sidebar (e.g. "Get started"). */
  nav?: NavItem[];
  /** Key after "g" that jumps to this module ("t" → g t). */
  hotkey?: string;
  badge?: (pulse: Pulse) => number | undefined;
  /** Pulse version keys that refresh this module's queries. */
  invalidates?: string[];
  /** Palette actions. */
  commands?: (ctx: CommandCtx) => Command[];
  /** Renderers for search hit types; each receives the prop `hit: SearchHit`. */
  searchResults?: Record<string, Component>;
  widgets?: Widget[];
  /** Notification kind → renderer; each receives the prop `notification: Notification`. */
  inbox?: Record<string, Component>;
  settings?: SettingsPanel[];
  extensions?: Partial<Record<ExtensionPoint, Component[]>>;
  personTabs?: PersonTab[];
  /** `startapp` prefixes this module answers inside Telegram ("shift" for "shift_1042"). */
  deepLinks?: Record<string, DeepLinkResolver>;
  /** The module's dictionary in one language: `(language) => import(`./i18n/${language}.json`)`. */
  messages: ModuleMessagesLoader;
}

/**
 * A function declaration on purpose: this file eagerly imports every module's index.ts (below), and
 * those import defineModule back. Declarations are hoisted, so the call works inside that cycle; a
 * `const` arrow would still be uninitialized.
 */
export function defineModule(m: DashboardModule): DashboardModule {
  return m;
}

export function byGroupThenOrder(a: DashboardModule, b: DashboardModule): number {
  const group = MODULE_GROUPS.indexOf(a.group) - MODULE_GROUPS.indexOf(b.group);
  return group || a.order - b.order || a.id.localeCompare(b.id);
}

// Modules import defineModule (and @/core helpers) back from here. That cycle is safe as long as
// this file is what loads them, which is the case in the app: nothing else imports a module's index.ts.
const found = import.meta.glob<{ default: DashboardModule }>("../modules/*/index.ts", { eager: true });

/** Every module, sorted for the sidebar. Built once at startup; never mutate it outside dev tooling. */
export const modules: DashboardModule[] = Object.values(found)
  .map((m) => m.default)
  .filter((m): m is DashboardModule => {
    // Only possible when a module's index.ts was imported before this file (a test importing the
    // module directly): that module is still mid-evaluation. Import @/core/modules first.
    if (!m && import.meta.env.DEV) console.warn("[modules] a module was imported before @/core/modules; import the registry first");
    return !!m;
  })
  .sort(byGroupThenOrder);

/**
 * Development only: adds modules that are not in src/modules (the VITE_MOCK stand-ins for packages
 * that haven't landed). A real module with the same id always wins.
 */
export function registerDevModules(extra: DashboardModule[]): void {
  if (!import.meta.env.DEV) return;
  const taken = new Set(modules.map((m) => m.id));
  for (const m of extra) if (!taken.has(m.id)) modules.push(m);
  modules.sort(byGroupThenOrder);
}

export function findModule(id: string | undefined): DashboardModule | undefined {
  return id ? modules.find((m) => m.id === id) : undefined;
}

/** The permission list a requirement names, for display ("Needs: Finance › View"). */
export function requirementList(required?: PermRequirement): Perm[] {
  if (required === undefined) return [];
  return typeof required === "string" ? [required] : [...required];
}
