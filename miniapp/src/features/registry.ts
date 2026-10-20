/**
 * Feature folders plug into the mini app here, without editing its shared files.
 *
 * A feature is a folder `src/features/<id>/` whose `index.ts` default-exports `defineFeature`:
 *
 *   export default defineFeature({
 *     id: "wallet",                                   // = the folder name
 *     messages,                                       // defineMessages({en, ru, uz}) from ./messages
 *     visible: (member) => can(member, "payroll.view") || true,
 *     pages: { home: lazy(() => import("./WalletPage")), payslip: lazy(() => import("./Payslip")) },
 *     sheets: { advance: lazy(() => import("./AdvanceSheet")) },
 *     homeCards: [{ id: "earned", component: EarnedCard }],
 *     meItems: [{ id: "pay", group: "money", label: "me.pay", icon: Wallet, to: { page: "home" } }],
 *     plusActions: [{ id: "advance", label: "plus.advance", icon: HandCoins, to: { sheet: "advance" } }],
 *     routes: { payslip: { page: "payslip", tab: "profile" } },   // ?screen=payslip:12
 *   });
 *
 * Home renders `homeHero` and `homeCards`, Profile ("Me") renders `meItems` grouped by `group`,
 * the (+) sheet renders `plusActions`. A visible item can `replaces` a built-in entry (for
 * example the leave feature replaces "me.timeOff"), and the built-in one disappears. Pages and
 * sheets open through `useNavigation()`: `push({feature: "wallet", page: "payslip", params: {id}})`
 * or `openSheet({kind: "feature", feature: "wallet", sheet: "advance"})`.
 */

import type { LucideIcon } from "lucide-react";
import type { ComponentType, ReactNode } from "react";

import type { MemberBrief, Summary } from "../api/types";
import type { Dictionary } from "../i18n";
import type { FeatureMessages } from "../i18n/feature";
import type { NavigationInit, PageRef, Params, Tab } from "../state/navigation";
import type { Member } from "../state/session";

export type Visible = (member: Member, summary: Summary | undefined) => boolean;

/** What every slot component receives. */
export type SlotProps = { member: Member; summary: Summary | undefined };
export type PageProps = { params: Params };
export type SheetProps = { params: Params; close: () => void };

/** Built-in entries a feature may replace with its own (critic item 43). */
export const BUILT_IN_ENTRIES = ["me.timeOff", "me.team", "me.work"] as const;
export type BuiltInEntry = (typeof BUILT_IN_ENTRIES)[number];

/** The groups on the Me screen, in display order. */
export const ME_GROUPS = ["money", "work", "documents", "team"] as const;
export type MeGroup = (typeof ME_GROUPS)[number];

export type SlotName = "home.hero" | "home.cards";

export type Slot = {
  /** Unique within the feature. */
  id: string;
  component: ComponentType<SlotProps>;
  /** Lower comes first; default 100. */
  order?: number;
  visible?: Visible;
  replaces?: readonly BuiltInEntry[];
};

/** Where a Me row or a (+) action leads: one of the feature's pages or sheets. */
export type Target<P extends string, S extends string> = { page: P; params?: Params } | { sheet: S; params?: Params };

export type MeItemStatus = {
  /** Text on the right, before the chevron ("3 days", "1 250 000 so‘m"). */
  value?: ReactNode;
  /** A count bubble (unseen payslips); hidden when 0 or null. */
  badge?: number | null;
};

export type MeItem<K extends string, P extends string, S extends string> = {
  id: string;
  group: MeGroup;
  /** A key in the feature's messages. */
  label: K;
  icon: LucideIcon;
  to: Target<P, S>;
  order?: number;
  visible?: Visible;
  replaces?: readonly BuiltInEntry[];
  /** A React hook (it may call useQuery) for the row's value and badge. */
  useStatus?: (props: SlotProps) => MeItemStatus;
};

export type PlusAction<K extends string, P extends string, S extends string> = {
  id: string;
  label: K;
  icon: LucideIcon;
  to: Target<P, S>;
  order?: number;
  visible?: Visible;
};

/**
 * A deep link name the feature answers (`?screen=<name>:<arg>` or `startapp=<name>-<arg>`):
 * a page name (the argument becomes `params.id`), a page or sheet with the parameter name and
 * the tab underneath (default Home), or a function for anything else.
 */
export type Route<P extends string, S extends string> =
  | P
  | { page: P; param?: string; tab?: Tab }
  | { sheet: S; param?: string; tab?: Tab }
  | ((arg: string | null) => NavigationInit | null);

/** A notification in the employee inbox (PLAN-OWNER §3.4), for `inboxRenderers`. */
export type InboxItem = {
  id: number;
  kind: string;
  severity: "info" | "warning" | "critical";
  title: string;
  body: string;
  app_screen: string;
  actor: MemberBrief | null;
  actions: { key: string; label: string; style: string }[];
  data: Record<string, unknown>;
  read_at: string | null;
  acted_at: string | null;
  created_at: string;
};

export type InboxRendererProps = { item: InboxItem; member: Member };

/** A feature as the registry stores it (keys erased). */
export type Feature = {
  id: string;
  pages?: Partial<Record<string, ComponentType<PageProps>>>;
  sheets?: Partial<Record<string, ComponentType<SheetProps>>>;
  homeHero?: readonly Slot[];
  homeCards?: readonly Slot[];
  meItems?: readonly MeItem<string, string, string>[];
  plusActions?: readonly PlusAction<string, string, string>[];
  routes?: Partial<Record<string, Route<string, string>>>;
  /** Custom rows for inbox notification kinds (the Inbox tab uses them when present). */
  inboxRenderers?: Partial<Record<string, ComponentType<InboxRendererProps>>>;
  messages: { en: Dictionary; ru: Dictionary; uz: Dictionary };
  /** Hide everything the feature shows (slots, rows, actions) for this person. */
  visible?: Visible;
};

/** A feature as its folder writes it: page, sheet and message keys are checked. */
export type FeatureDefinition<K extends string, P extends string, S extends string> = Omit<
  Feature,
  "pages" | "sheets" | "meItems" | "plusActions" | "routes" | "messages"
> & {
  pages?: Record<P, ComponentType<PageProps>>;
  sheets?: Record<S, ComponentType<SheetProps>>;
  meItems?: readonly MeItem<NoInfer<K>, NoInfer<P>, NoInfer<S>>[];
  plusActions?: readonly PlusAction<NoInfer<K>, NoInfer<P>, NoInfer<S>>[];
  routes?: Record<string, Route<NoInfer<P>, NoInfer<S>>>;
  messages: FeatureMessages<K>;
};

/**
 * Declare a feature. A function declaration on purpose: feature modules call it while this
 * module is still loading them (the glob below), and only hoisted declarations are ready then.
 */
export function defineFeature<K extends string, P extends string = never, S extends string = never>(
  definition: FeatureDefinition<K, P, S>,
): FeatureDefinition<K, P, S> {
  return definition;
}

// — discovery —

/** Check the feature modules a glob found. Problems are reported, never silently swallowed. */
export function collectFeatures(modules: Record<string, unknown>): { features: Feature[]; problems: string[] } {
  const features: Feature[] = [];
  const problems: string[] = [];
  for (const [path, module] of Object.entries(modules).sort(([a], [b]) => a.localeCompare(b))) {
    const folder = /\.\/([^/]+)\/index\.tsx?$/.exec(path)?.[1] ?? path;
    const feature = (module as { default?: Feature } | undefined)?.default;
    if (!feature || typeof feature !== "object") {
      problems.push(`${path}: no default export from defineFeature()`);
      continue;
    }
    if (feature.id !== folder) {
      problems.push(`${path}: id "${feature.id}" must match its folder "${folder}"`);
      continue;
    }
    if (!feature.messages?.en || !feature.messages.ru || !feature.messages.uz) {
      problems.push(`${path}: messages need en, ru and uz`);
      continue;
    }
    const targets = [...(feature.meItems ?? []), ...(feature.plusActions ?? [])].map((item) => item.to);
    const missing = targets.filter((to) => ("page" in to ? !feature.pages?.[to.page] : !feature.sheets?.[to.sheet]));
    if (missing.length) {
      problems.push(`${path}: unknown targets ${missing.map((to) => JSON.stringify(to)).join(", ")}`);
      continue;
    }
    features.push(feature);
  }
  return { features, problems };
}

const discovered = collectFeatures(import.meta.glob("./*/index.{ts,tsx}", { eager: true }));
if (discovered.problems.length) {
  if (import.meta.env.DEV) throw new Error(`Feature registry:\n${discovered.problems.join("\n")}`);
  console.error("Feature registry:", discovered.problems);
}

/** Every feature folder in the app, in folder order. */
export const features: readonly Feature[] = discovered.features;

// — what is visible for a person —

export type FeatureContext = SlotProps;
export type Placed<T> = { feature: Feature; item: T };

function allowed(visible: Visible | undefined, context: FeatureContext, where: string): boolean {
  if (!visible) return true;
  try {
    return visible(context.member, context.summary);
  } catch (error) {
    // One feature's broken rule must not take Home or Me down with it.
    console.error(`visible() failed in ${where}`, error);
    return false;
  }
}

export function visibleFeatures(list: readonly Feature[], context: FeatureContext): Feature[] {
  return list.filter((feature) => allowed(feature.visible, context, feature.id));
}

function place<T extends { id: string; order?: number; visible?: Visible }>(
  list: readonly Feature[],
  context: FeatureContext,
  pick: (feature: Feature) => readonly T[] | undefined,
): Placed<T>[] {
  const placed: (Placed<T> & { index: number })[] = [];
  for (const feature of visibleFeatures(list, context)) {
    (pick(feature) ?? []).forEach((item, index) => {
      if (allowed(item.visible, context, `${feature.id}.${item.id}`)) placed.push({ feature, item, index });
    });
  }
  placed.sort(
    (a, b) =>
      (a.item.order ?? 100) - (b.item.order ?? 100) ||
      a.feature.id.localeCompare(b.feature.id) ||
      a.index - b.index,
  );
  return placed.map(({ feature, item }) => ({ feature, item }));
}

export function homeSlots(list: readonly Feature[], name: SlotName, context: FeatureContext): Placed<Slot>[] {
  return place(list, context, (feature) => (name === "home.hero" ? feature.homeHero : feature.homeCards));
}

export function meItemsByGroup(
  list: readonly Feature[],
  context: FeatureContext,
): Record<MeGroup, Placed<MeItem<string, string, string>>[]> {
  const groups = Object.fromEntries(ME_GROUPS.map((group) => [group, []])) as unknown as Record<
    MeGroup,
    Placed<MeItem<string, string, string>>[]
  >;
  for (const placed of place(list, context, (feature) => feature.meItems)) groups[placed.item.group].push(placed);
  return groups;
}

export function plusActions(list: readonly Feature[], context: FeatureContext): Placed<PlusAction<string, string, string>>[] {
  return place(list, context, (feature) => feature.plusActions);
}

/** Built-in entries that a visible slot or Me row replaces for this person. */
export function replacedEntries(list: readonly Feature[], context: FeatureContext): Set<BuiltInEntry> {
  const replaced = new Set<BuiltInEntry>();
  const items = [
    ...place(list, context, (feature) => feature.homeHero),
    ...place(list, context, (feature) => feature.homeCards),
    ...place(list, context, (feature) => feature.meItems),
  ];
  for (const { item } of items) for (const entry of item.replaces ?? []) replaced.add(entry);
  return replaced;
}

// — pages, sheets and routes —

export function findFeature(list: readonly Feature[], id: string): Feature | null {
  return list.find((feature) => feature.id === id) ?? null;
}

export function findPage(list: readonly Feature[], ref: PageRef): ComponentType<PageProps> | null {
  return findFeature(list, ref.feature)?.pages?.[ref.page] ?? null;
}

export function findSheet(list: readonly Feature[], feature: string, sheet: string): ComponentType<SheetProps> | null {
  return findFeature(list, feature)?.sheets?.[sheet] ?? null;
}

/** "12" → 12, so deep-linked ids match the ones screens push. */
function paramValue(arg: string): string | number {
  return /^\d{1,15}$/.test(arg) ? Number(arg) : arg;
}

/**
 * Where a deep link name leads: a feature route (`payslip`), or the generic `<feature>.<page>`
 * form for any page (`wallet.payslip`). Null when nobody answers to the name.
 */
export function routeTarget(list: readonly Feature[], name: string, arg: string | null): NavigationInit | null {
  for (const feature of list) {
    const route = feature.routes?.[name];
    if (!route) continue;
    if (typeof route === "function") return route(arg);
    const spec = typeof route === "string" ? { page: route } : route;
    const params: Params = arg !== null ? { [spec.param ?? "id"]: paramValue(arg) } : {};
    if ("page" in spec) {
      if (!feature.pages?.[spec.page]) return null;
      return { tab: spec.tab ?? "home", stack: [{ feature: feature.id, page: spec.page, params }] };
    }
    if (!feature.sheets?.[spec.sheet]) return null;
    return { tab: spec.tab ?? "home", sheet: { kind: "feature", feature: feature.id, sheet: spec.sheet, params } };
  }
  const dot = name.indexOf(".");
  if (dot > 0) {
    const feature = findFeature(list, name.slice(0, dot));
    const page = name.slice(dot + 1);
    if (feature?.pages?.[page]) {
      return { tab: "home", stack: [{ feature: feature.id, page, params: arg !== null ? { id: paramValue(arg) } : {} }] };
    }
  }
  return null;
}
