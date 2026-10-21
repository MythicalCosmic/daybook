/**
 * Group labels for the palette's search hits. A hit's `type` is the backend provider's key
 * (`apps.console.registry.register_search("finance.transaction", …)`); its label is the first
 * `shell.searchType.*` key that exists among: the whole type, its last part, that part as a plural
 * noun (the dictionaries name groups in the plural: "transactions", "counterparties"), and the app
 * prefix ("members", "knowledge"). `searchTypes.test.ts` fails when a registered type has none.
 */
export function searchTypeKeys(type: string): string[] {
  const parts = type.split(".");
  const prefix = parts[0] ?? type;
  const last = parts.at(-1) ?? type;
  const plural = last.endsWith("s") ? last : /[^aeiou]y$/.test(last) ? `${last.slice(0, -1)}ies` : `${last}s`;
  const candidates = parts.length > 1 ? [type, last, plural, prefix] : [type];
  return [...new Set(candidates)].map((candidate) => `shell.searchType.${candidate}`);
}

/** The first of `searchTypeKeys(type)` the dictionaries have, or null. */
export function searchTypeKey(type: string, exists: (key: string) => boolean): string | null {
  return searchTypeKeys(type).find(exists) ?? null;
}
