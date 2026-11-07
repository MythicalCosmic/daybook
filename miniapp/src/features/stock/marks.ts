/**
 * What this phone marked on the expiry check: "on the near-expiry shelf" (the day) and "write-off
 * proposed" (its id), per stock row. The server records both (the audit log, the write-off), but
 * its expiry list doesn't say so yet, so without this a reload would offer them again. A per
 * person convenience: storage may be missing or full, and then the marks last as long as the app.
 */

export type Mark = { shelf?: string; writeoff?: number | "pending" };
export type Marks = Record<number, Mark>;

/** Enough for a pharmacy's expiry list; the oldest go first. */
const LIMIT = 400;

const keyOf = (company: number) => `stock.marks.${company}`;

function storage(): Storage | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null;
  }
}

export function readMarks(company: number): Marks {
  try {
    const raw = storage()?.getItem(keyOf(company));
    if (!raw) return {};
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return {};
    const marks: Marks = {};
    for (const [id, value] of Object.entries(parsed as Record<string, unknown>)) {
      if (!/^\d+$/.test(id) || !value || typeof value !== "object") continue;
      const { shelf, writeoff } = value as Record<string, unknown>;
      const mark: Mark = {};
      if (typeof shelf === "string" && /^\d{4}-\d{2}-\d{2}$/.test(shelf)) mark.shelf = shelf;
      if (typeof writeoff === "number" && Number.isInteger(writeoff)) mark.writeoff = writeoff;
      if (mark.shelf || mark.writeoff) marks[Number(id)] = mark;
    }
    return marks;
  } catch {
    return {};
  }
}

/** A proposal still on its way isn't kept: after a reload the server is asked again. */
export function writeMarks(company: number, marks: Marks): void {
  const kept = Object.entries(marks)
    .map(([id, mark]) => [id, { ...mark, writeoff: mark.writeoff === "pending" ? undefined : mark.writeoff }] as const)
    .filter(([, mark]) => mark.shelf || mark.writeoff)
    .slice(-LIMIT);
  try {
    storage()?.setItem(keyOf(company), JSON.stringify(Object.fromEntries(kept)));
  } catch {
    // Full or blocked: the marks stay for this session only.
  }
}
