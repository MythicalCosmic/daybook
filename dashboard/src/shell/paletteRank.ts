/**
 * How the command palette orders what answers a query (CommandPalette.vue). People expect what
 * starts with their words first, whichever of the three languages they type in, and they type
 * Uzbek without its apostrophes ("tatil" for "Ta’til", "kokterak" for "Ko‘kterak").
 */

/** Lower case, without Uzbek apostrophes and without the emoji or symbols a title may open with. */
export function plain(text: string): string {
  return text
    .toLocaleLowerCase()
    .replace(/[‘’ʻʼ'`]/g, "")
    .replace(/^[^\p{L}\p{N}]+/u, "");
}

const WORD_BREAK = /[\s·:;,.!?()[\]/«»"“”—–-]+/;

/**
 * How well a title (and its keywords) answers the query: 0 when one starts with it, 1 when one of
 * their words does, 2 when it is only inside a word ("chil" in the Uzbek "Kiruvchilar"), 3 when it
 * isn't there as typed (a fuzzy match, a typo).
 */
export type Match = 0 | 1 | 2 | 3;

export function matchOf(texts: readonly string[], query: string): Match {
  const needle = plain(query.trim());
  if (!needle) return 3;
  const all = texts.map(plain);
  if (all.some((text) => text.startsWith(needle))) return 0;
  if (all.some((text) => text.split(WORD_BREAK).some((word) => plain(word).startsWith(needle)))) return 1;
  if (all.some((text) => text.includes(needle))) return 2;
  return 3;
}

export interface Rankable {
  title: string;
  keywords: readonly string[];
}

const textsOf = (item: Rankable) => [item.title, ...item.keywords];

/** Items, the best match first; equal matches keep their order (Fuse's, or the server's). */
export function byMatch<T extends Rankable>(items: readonly T[], query: string): T[] {
  return items
    .map((item, index) => ({ item, index, match: matchOf(textsOf(item), query) }))
    .sort((a, b) => a.match - b.match || a.index - b.index)
    .map((entry) => entry.item);
}

/**
 * Which local matches (pages, actions, companies) to show: those a title or keyword starts with,
 * or one of their words does, and close fuzzy ones ("finanse" finds Finance). A query found only
 * in the middle of a word is left out: "Chil" must not offer Inbox for its Uzbek "Kiruvchilar".
 */
export function keepLocal(item: Rankable, query: string, fuzzyScore: number, looseScore: number): boolean {
  const match = matchOf(textsOf(item), query);
  return match <= 1 || (match === 3 && fuzzyScore <= looseScore);
}

/**
 * Search groups by kind of record. When two groups answer a query equally well, the records come
 * first and what merely mentions them last: a shift before the payments that name it, a project
 * before its expenses. Types not listed here sit between the two.
 */
const LEADING = ["people", "members", "branches", "projects", "tasks", "shifts", "counterparties", "customers", "products", "pages", "knowledge", "events"];
const TRAILING = ["announcements", "transactions"];

export function groupWeight(labelKey: string | null): number {
  const name = labelKey?.split(".").at(-1) ?? "";
  if (LEADING.includes(name)) return LEADING.indexOf(name);
  if (TRAILING.includes(name)) return 100 + TRAILING.indexOf(name);
  return 50;
}

/**
 * Sections in answer order: the best match among each one's items, then its weight (the page list
 * is -1, so a page wins a tie), then its place.
 */
export function bySectionMatch<S extends { items: readonly Rankable[]; weight: number }>(sections: readonly S[], query: string): S[] {
  const best = (section: S) => Math.min(3, ...section.items.map((item) => matchOf(textsOf(item), query)));
  return sections
    .map((section, index) => ({ section, index, match: best(section) }))
    .sort((a, b) => a.match - b.match || a.section.weight - b.section.weight || a.index - b.index)
    .map((entry) => entry.section);
}
