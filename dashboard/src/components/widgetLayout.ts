/**
 * A person's widget arrangement (Overview "Customize", plan §6.2): an order and the hidden ids,
 * saved as their `overview` SavedView. Widgets registered later than the saved layout appear at the
 * end; ids that no longer exist are dropped.
 */
export interface WidgetLayout {
  order: string[];
  hidden: string[];
}

export interface LayoutWidget {
  id: string;
  span: 1 | 2 | 3 | 4;
}

export const EMPTY_LAYOUT: WidgetLayout = { order: [], hidden: [] };

/** Widgets in display order (hidden ones included, flagged). */
export function arrange<W extends LayoutWidget>(widgets: readonly W[], layout: WidgetLayout): Array<W & { hidden: boolean }> {
  const byId = new Map(widgets.map((widget) => [widget.id, widget]));
  const seen = new Set<string>();
  const ordered: W[] = [];
  for (const id of layout.order) {
    const widget = byId.get(id);
    if (widget && !seen.has(id)) {
      ordered.push(widget);
      seen.add(id);
    }
  }
  for (const widget of widgets) if (!seen.has(widget.id)) ordered.push(widget);
  const hidden = new Set(layout.hidden);
  return ordered.map((widget) => ({ ...widget, hidden: hidden.has(widget.id) }));
}

export function moveWidget(layout: WidgetLayout, widgets: readonly LayoutWidget[], from: number, to: number): WidgetLayout {
  const order = arrange(widgets, layout).map((widget) => widget.id);
  const [moved] = order.splice(from, 1);
  if (moved === undefined) return layout;
  order.splice(Math.max(0, Math.min(order.length, to)), 0, moved);
  return { ...layout, order };
}

export function toggleWidget(layout: WidgetLayout, id: string): WidgetLayout {
  const hidden = layout.hidden.includes(id) ? layout.hidden.filter((item) => item !== id) : [...layout.hidden, id];
  return { ...layout, hidden };
}
