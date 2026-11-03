/**
 * Where a disciplinary record stands for the person, without React: what it asks of them, which
 * still count, and the explanation's checks. Calm by design: nothing here grades anybody.
 */
import type { DisciplinaryRecord } from "./api";

/**
 * withdrawn: taken back; read: issued and waiting for "Tanishdim"; done: acknowledged; past: no
 * longer counts (its time ran out).
 */
export type RecordStage = "withdrawn" | "toRead" | "done" | "past";

export function recordStage(record: Pick<DisciplinaryRecord, "status" | "active">): RecordStage {
  if (record.status === "withdrawn") return "withdrawn";
  if (record.status === "issued") return "toRead";
  return record.active ? "done" : "past";
}

/** Records that ask the person to acknowledge them: Home's card and Me's bubble. */
export function toAcknowledge(records: readonly DisciplinaryRecord[] | undefined): DisciplinaryRecord[] {
  return (records ?? []).filter((record) => recordStage(record) === "toRead");
}

/** The ones that still count first (newest first, as the API sends them), then the rest. */
export function splitRecords(records: readonly DisciplinaryRecord[]): { current: DisciplinaryRecord[]; earlier: DisciplinaryRecord[] } {
  const current = records.filter((record) => record.active && record.status !== "withdrawn");
  return { current, earlier: records.filter((record) => !current.includes(record)) };
}

/** An explanation is written once, on a record that stands. */
export const canExplain = (record: Pick<DisciplinaryRecord, "status" | "employee_response">): boolean =>
  record.status !== "withdrawn" && !record.employee_response;

export const EXPLAIN_MAX = 2000;

/** The explanation's body, or null while there is nothing (or too much) to send. */
export function explainPayload(text: string): { text: string } | null {
  const clean = text.trim();
  return clean && clean.length <= EXPLAIN_MAX ? { text: clean } : null;
}
