/**
 * Pure helpers of the unchangeable lists (O‘zgarmas ro‘yxatlar), tested in __tests__/lists.test.ts.
 * A cell (topic × student) holds its latest "studied" line that no correction took back; its
 * history is every line of it, oldest first, corrections included.
 */
import type { StatusTone } from "@/components/StatusPill.vue";

import type { StudyListDetail, StudyListRow, StudyListState, StudyMark, StudyStudent, StudyTopic } from "./types";

export const LIST_STATE_TONES: Record<StudyListState, StatusTone> = { open: "info", sealed: "primary" };

export const cellKey = (topicId: number, studentId: number): string => `${topicId}:${studentId}`;

export interface StudyCell {
  topicId: number;
  studentId: number;
  /** The line the cell holds; null when it is empty. */
  standing: StudyMark | null;
  /** Every line of the cell, oldest first (corrections included). */
  history: StudyMark[];
  /** A line of the cell was taken back by a correction. */
  corrected: boolean;
}

const byNumber = (a: StudyMark, b: StudyMark) => a.number - b.number;

/** Every cell that has lines, by `cellKey`: its standing line and its history. */
export function cellsOf(marks: readonly StudyMark[]): Map<string, StudyCell> {
  const ordered = [...marks].sort(byNumber);
  const byId = new Map(ordered.map((mark) => [mark.id, mark]));
  // Taken back: by the line's own pointer or by a correction that names it.
  const takenBack = new Set<number>();
  for (const mark of ordered) {
    if (mark.kind === "studied" && mark.corrected_by_id !== null) takenBack.add(mark.id);
    if (mark.kind === "correction" && mark.corrects_id !== null) takenBack.add(mark.corrects_id);
  }
  const cells = new Map<string, StudyCell>();
  for (const mark of ordered) {
    // A correction sits in the cell of the line it takes back.
    const home = mark.kind === "correction" && mark.corrects_id !== null ? (byId.get(mark.corrects_id) ?? mark) : mark;
    const key = cellKey(home.topic_id, home.student_id);
    let cell = cells.get(key);
    if (!cell) {
      cell = { topicId: home.topic_id, studentId: home.student_id, standing: null, history: [], corrected: false };
      cells.set(key, cell);
    }
    cell.history.push(mark);
    if (mark.kind === "correction" || takenBack.has(mark.id)) cell.corrected = true;
    // Oldest first: the latest standing line wins.
    if (mark.kind === "studied" && !takenBack.has(mark.id)) cell.standing = mark;
  }
  return cells;
}

/** The line a cell holds, or null when it is empty. */
export function standingLine(marks: readonly StudyMark[], topicId: number, studentId: number): StudyMark | null {
  return cellsOf(marks).get(cellKey(topicId, studentId))?.standing ?? null;
}

/** Every line of a cell, oldest first. */
export function cellHistory(marks: readonly StudyMark[], topicId: number, studentId: number): StudyMark[] {
  return cellsOf(marks).get(cellKey(topicId, studentId))?.history ?? [];
}

export interface StudyProgress {
  /** Cells holding a line. */
  studied: number;
  /** Topics × students. */
  cells: number;
  /** Whole percent, 100 only when every cell holds a line. */
  percent: number;
  /** Students who studied each topic, by topic id. */
  byTopic: Record<number, number>;
  /** Topics each student studied, by student id. */
  byStudent: Record<number, number>;
}

export function percentOf(studied: number, cells: number): number {
  if (cells <= 0) return 0;
  return studied >= cells ? 100 : Math.floor((studied / cells) * 100);
}

/** How much of the list is studied: overall, per topic and per student. */
export function progressOf(list: Pick<StudyListDetail, "topics" | "students" | "marks">): StudyProgress {
  const cells = cellsOf(list.marks);
  const byTopic: Record<number, number> = {};
  const byStudent: Record<number, number> = {};
  for (const topic of list.topics) byTopic[topic.id] = 0;
  for (const student of list.students) byStudent[student.id] = 0;
  let studied = 0;
  for (const cell of cells.values()) {
    if (!cell.standing || !(cell.topicId in byTopic) || !(cell.studentId in byStudent)) continue;
    studied += 1;
    byTopic[cell.topicId]! += 1;
    byStudent[cell.studentId]! += 1;
  }
  const total = list.topics.length * list.students.length;
  return { studied, cells: total, percent: percentOf(studied, total), byTopic, byStudent };
}

export interface JournalLine {
  mark: StudyMark;
  topic: StudyTopic | null;
  student: StudyStudent | null;
  /** A "studied" line that was taken back: the correction that did it. */
  correctedBy: StudyMark | null;
  /** A correction: the line it takes back. */
  corrects: StudyMark | null;
}

/** Every line in order, as the bound journal reads, with what each one points at. */
export function journalOf(list: Pick<StudyListDetail, "topics" | "students" | "marks">): JournalLine[] {
  const ordered = [...list.marks].sort(byNumber);
  const byId = new Map(ordered.map((mark) => [mark.id, mark]));
  const correctionOf = new Map<number, StudyMark>();
  for (const mark of ordered) if (mark.kind === "correction" && mark.corrects_id !== null) correctionOf.set(mark.corrects_id, mark);
  const topics = new Map(list.topics.map((topic) => [topic.id, topic]));
  const students = new Map(list.students.map((student) => [student.id, student]));
  return ordered.map((mark) => {
    const corrects = mark.kind === "correction" && mark.corrects_id !== null ? (byId.get(mark.corrects_id) ?? null) : null;
    const home = corrects ?? mark;
    const correctedBy = mark.kind === "studied" ? ((mark.corrected_by_id !== null ? byId.get(mark.corrected_by_id) : undefined) ?? correctionOf.get(mark.id) ?? null) : null;
    return { mark, topic: topics.get(home.topic_id) ?? null, student: students.get(home.student_id) ?? null, correctedBy, corrects };
  });
}

/** Rows per state, for the filter's counts. */
export function stateCounts(rows: readonly Pick<StudyListRow, "state">[]): Record<StudyListState | "all", number> {
  const counts = { open: 0, sealed: 0, all: rows.length };
  for (const row of rows) counts[row.state] += 1;
  return counts;
}

/**
 * One topic per line, as typed or pasted: trimmed, inner spaces folded, empty lines dropped, and a
 * list's own numbering or bullets ("1.", "2)", "-", "•") taken off, since the list numbers topics.
 */
export function parseTitles(text: string): string[] {
  return text
    .split(/\r?\n/)
    .map((line) =>
      line
        .replace(/\s+/g, " ")
        .trim()
        .replace(/^(?:\d{1,3}[.)]|[-–—•*])\s+/, "")
        .trim(),
    )
    .filter(Boolean);
}

/** The small "by" under a mark: "Dilnoza Karimova" reads "Dilnoza K.". */
export function shortName(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length < 2) return parts[0] ?? "";
  return `${parts[0]} ${parts[1]!.charAt(0)}.`;
}

/** "2026-11-21" as "21.11". */
export function dayMonth(day: string | null | undefined): string {
  if (!day) return "";
  const [, month, date] = day.split("-");
  return month && date ? `${date}.${month}` : day;
}

/** "2026-11-21" as "21.11.2026". */
export function dottedDay(day: string | null | undefined): string {
  if (!day) return "";
  const [year, month, date] = day.split("-");
  return year && month && date ? `${date}.${month}.${year}` : day;
}

/** The start of a digest, as the screen shows it (the print shows it whole). */
export function shortDigest(digest: string | null | undefined, length: number): string {
  return (digest ?? "").slice(0, length);
}

/** A student's second line: the note written with the name, else the staff member's position. */
export function studentLine(student: Pick<StudyStudent, "note" | "position">): string {
  return student.note || student.position || "";
}
