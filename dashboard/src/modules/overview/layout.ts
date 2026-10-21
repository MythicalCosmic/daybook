/**
 * How the Overview arranges whatever widgets the modules registered (plan §6.2) into one owner
 * cockpit, without holes, whatever the mix:
 *
 *   lead   cards registered above the first KPI (Get started, Branches today): full width, stacked
 *   kpis   every `kind: "kpi"` tile in one band, four to a row (two on tablets and phones); a short
 *          last row borrows the first one-column cards so the band ends square
 *   cards  cards and charts packed into rows of four columns in their order; a later card fills an
 *          earlier gap, and the cards of a row that still isn't full widen to close it
 *
 * Within each band the registered `order` (then id) decides, or the person's own order when they
 * customised the page (widgetLayout.ts `arrange`, saved as their `overview` SavedView).
 */
import { useQuery } from "@tanstack/vue-query";
import { computed } from "vue";

import { http, ownerPath } from "@/api/http";
import { qk } from "@/api/keys";
import { arrange, type LayoutWidget, type WidgetLayout } from "@/components/widgetLayout";
import type { WidgetSpan } from "@/core/modules";
import type { SavedView } from "@/lib/useSavedViews";
import { useCompanyStore } from "@/stores/company";

/** The personal layout's SavedView (plan §3.3): `module="overview"`, `name="layout"`. */
export const LAYOUT_VIEW = "layout";

export interface LayoutState {
  widgets: Array<{ id: string; hidden: boolean; order: number }>;
}

/** A saved view's state as a WidgetLayout (anything malformed counts as no layout). */
export function layoutFromState(state: unknown): WidgetLayout {
  const rows = (state as Partial<LayoutState> | null)?.widgets;
  if (!Array.isArray(rows)) return { order: [], hidden: [] };
  const valid = rows.filter((row) => !!row && typeof row.id === "string");
  const sorted = [...valid].sort((a, b) => (Number(a.order) || 0) - (Number(b.order) || 0));
  return { order: sorted.map((row) => row.id), hidden: valid.filter((row) => row.hidden === true).map((row) => row.id) };
}

/** The state to save for `layout` over the widgets on the page now. */
export function layoutToState(widgets: readonly LayoutWidget[], layout: WidgetLayout): LayoutState {
  return { widgets: arrange(widgets, layout).map((widget, order) => ({ id: widget.id, hidden: widget.hidden, order })) };
}

/** Whether `layout` shows every widget in the registered order (nothing worth saving). */
export function isDefaultLayout(widgets: readonly LayoutWidget[], layout: WidgetLayout): boolean {
  return arrange(widgets, layout).every((widget, index) => !widget.hidden && widget.id === widgets[index]?.id);
}

/**
 * The person's own saved views of the Overview (`saved-views/?module=overview`). Same key as
 * `useSavedViews("overview")`, so the shell's `console.saved_views` pulse refreshes it. Here and
 * not in api.ts, which the widgets share: the page stays light (README "Budgets").
 */
export function useOverviewViews() {
  const company = useCompanyStore();
  const companyId = computed(() => company.currentId ?? 0);
  return useQuery({
    queryKey: computed(() => qk(companyId.value, "shell", "saved-views", { module: "overview" })),
    queryFn: ({ signal }) => http.get<SavedView[]>(ownerPath(companyId.value, "saved-views/"), { module: "overview" }, { signal }),
    enabled: computed(() => companyId.value > 0),
    staleTime: 5 * 60_000,
  });
}

/** Saves (or, with `state: null`, deletes) the person's layout; the helper loads on use ("Done" is rare). */
export async function saveOverviewLayout(companyId: number, current: SavedView | null, state: Record<string, unknown> | null): Promise<void> {
  const { savedViewsApi } = await import("@/lib/useSavedViews");
  const api = savedViewsApi(companyId);
  if (state === null) {
    if (current) await api.remove(current.id);
  } else if (current) await api.update(current.id, { state });
  else await api.create("overview", { name: LAYOUT_VIEW, state });
}

export interface CockpitWidget {
  id: string;
  span: WidgetSpan;
  kind: "kpi" | "card" | "chart";
}

export interface Placed<W> {
  widget: W;
  /** Columns on a four-column desktop row (tablets clamp it to two). */
  span: WidgetSpan;
}

export interface Cockpit<W> {
  lead: W[];
  kpis: Array<Placed<W>>;
  cards: Array<Placed<W>>;
}

export const COLUMNS = 4;

/** Packs `widgets` (already in display order) into the three bands. */
export function cockpit<W extends CockpitWidget>(widgets: readonly W[]): Cockpit<W> {
  const firstKpi = widgets.findIndex((widget) => widget.kind === "kpi");
  const lead = firstKpi < 0 ? [] : widgets.slice(0, firstKpi).filter((widget) => widget.kind !== "kpi");
  const leadIds = new Set(lead.map((widget) => widget.id));
  const kpis = widgets.filter((widget) => widget.kind === "kpi");
  const rest = widgets.filter((widget) => widget.kind !== "kpi" && !leadIds.has(widget.id));

  // A KPI band whose last row is short takes the first narrow cards (Team, Off today…) beside it.
  const short = kpis.length % COLUMNS;
  if (short) {
    for (let free = COLUMNS - short; free > 0; free--) {
      const index = rest.findIndex((widget) => widget.span === 1);
      if (index < 0) break;
      kpis.push(rest.splice(index, 1)[0]!);
    }
  }
  return { lead, kpis: pack(kpis), cards: pack(rest) };
}

/** First fit, row by row, keeping the order; then a row with room left widens its cards. */
export function pack<W extends CockpitWidget>(widgets: readonly W[], columns = COLUMNS): Array<Placed<W>> {
  const rows: Array<Array<Placed<W>>> = [];
  const used = (row: Array<Placed<W>>) => row.reduce((sum, item) => sum + item.span, 0);
  for (const widget of widgets) {
    const span = Math.min(widget.span, columns) as WidgetSpan;
    const row = rows.find((candidate) => used(candidate) + span <= columns);
    if (row) row.push({ widget, span });
    else rows.push([{ widget, span }]);
  }
  for (const row of rows) {
    // Round-robin from the last card, so [2] becomes [4] and [1, 1] becomes [2, 2].
    for (let free = columns - used(row), index = row.length - 1; free > 0; free--, index = (index - 1 + row.length) % row.length) {
      row[index]!.span = (row[index]!.span + 1) as WidgetSpan;
    }
  }
  return rows.flat();
}
