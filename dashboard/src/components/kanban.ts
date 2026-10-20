/**
 * Board logic behind KanbanBoard, kept free of the DOM so it can be tested: grouping cards into
 * columns, moving a card, finding the next column a card may go to, and describing where a card
 * landed (the neighbours the server needs to place it: Tasks, Projects, CRM and Hiring all use it).
 */
export interface KanbanColumn {
  id: string;
  title: string;
  /** Any CSS color for the column dot. */
  color?: string;
  /** Show "4 / 5" and warn above it. */
  wipLimit?: number | null;
  description?: string;
}

export type Lists<Item> = Record<string, Item[]>;

/** Cards per column in the order given; cards of unknown columns are left out. */
export function groupItems<Item>(columns: readonly KanbanColumn[], items: readonly Item[], columnOf: (item: Item) => string): Lists<Item> {
  const lists: Lists<Item> = Object.fromEntries(columns.map((column) => [column.id, [] as Item[]]));
  for (const item of items) lists[columnOf(item)]?.push(item);
  return lists;
}

export function findCard<Item>(lists: Lists<Item>, key: string, keyOf: (item: Item) => string): { column: string; index: number; item: Item } | null {
  for (const [column, list] of Object.entries(lists)) {
    const index = list.findIndex((item) => keyOf(item) === key);
    if (index >= 0) return { column, index, item: list[index]! };
  }
  return null;
}

/** A copy of the lists with the card moved to `toColumn` at `toIndex` (clamped). */
export function moveCard<Item>(lists: Lists<Item>, key: string, toColumn: string, toIndex: number, keyOf: (item: Item) => string): Lists<Item> {
  const found = findCard(lists, key, keyOf);
  if (!found || !(toColumn in lists)) return lists;
  const next: Lists<Item> = Object.fromEntries(Object.entries(lists).map(([column, list]) => [column, [...list]]));
  next[found.column]!.splice(found.index, 1);
  const target = next[toColumn]!;
  target.splice(Math.max(0, Math.min(target.length, toIndex)), 0, found.item);
  return next;
}

/**
 * The nearest column in `direction` (−1 left, +1 right) the card may enter, skipping the ones
 * `allowed` refuses; null when there is none.
 */
export function nextColumn(columns: readonly KanbanColumn[], from: string, direction: -1 | 1, allowed: (columnId: string) => boolean): string | null {
  let index = columns.findIndex((column) => column.id === from) + direction;
  while (index >= 0 && index < columns.length) {
    const candidate = columns[index]!.id;
    if (allowed(candidate)) return candidate;
    index += direction;
  }
  return null;
}

export interface KanbanMove<Item> {
  item: Item;
  from: string;
  to: string;
  /** Position in the target column after the move. */
  index: number;
  /** The card now right above it, and right below (to compute the server's position). */
  before: Item | null;
  after: Item | null;
}

/** Where a card is in `lists`, described for the `move` event. */
export function describeMove<Item>(lists: Lists<Item>, key: string, from: string, keyOf: (item: Item) => string): KanbanMove<Item> | null {
  const found = findCard(lists, key, keyOf);
  if (!found) return null;
  const list = lists[found.column]!;
  return {
    item: found.item,
    from,
    to: found.column,
    index: found.index,
    before: list[found.index - 1] ?? null,
    after: list[found.index + 1] ?? null,
  };
}

/** A float position between two neighbours (Projects' `list_position`), for callers that keep one. */
export function positionBetween(before: number | null, after: number | null, step = 1024): number {
  if (before === null && after === null) return step;
  if (before === null) return after! - step;
  if (after === null) return before + step;
  return (before + after) / 2;
}
