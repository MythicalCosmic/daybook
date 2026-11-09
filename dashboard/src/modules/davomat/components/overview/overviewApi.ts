/**
 * What the Overview reads: attendance's day board (`attendance/board/`), Face ID's terminal status
 * (`faceid/status/`) and today's scans (`faceid/events/`). Shapes copied from those modules'
 * types.ts (modules never import each other); keys live under this module, which lists "faceid" and
 * "attendance" in `invalidates`, so every scan and check-in refreshes the board.
 */
import { keepPreviousData, useQuery } from "@tanstack/vue-query";
import { computed, toValue, type MaybeRefOrGetter } from "vue";

import { http, ownerPath } from "@/api/http";
import { qk } from "@/api/keys";
import type { Page } from "@/api/types";
import { useCompanyId } from "@/stores/company";

export interface Ref {
  id: number;
  name: string;
}

export interface PersonCard {
  id: number;
  name: string;
  photo_url: string | null;
  position: Ref | null;
  home_branch: Ref | null;
  status: string;
}

export interface BoardShift {
  id: number;
  starts_at: string;
  ends_at: string;
  start: string;
  end: string;
  branch: (Ref & { code: string }) | null;
}

export interface BoardRecord {
  id: number;
  status: "open" | "closed" | "auto_closed" | "absent" | "excused";
  check_in_at: string | null;
  check_out_at: string | null;
  late_minutes: number;
  early_leave_minutes: number;
  worked_minutes: number;
  is_late: boolean;
}

export type BoardState = "in" | "late" | "not_yet" | "absent" | "off";
export type BoardReason = "late" | "leave" | "day_off" | "holiday" | "suspended" | "no_shift" | "excused" | null;

export interface BoardRow {
  member: PersonCard;
  branch: (Ref & { code: string }) | null;
  state: BoardState;
  reason: BoardReason;
  shift: BoardShift | null;
  record: BoardRecord | null;
}

export interface Board {
  date: string;
  is_today: boolean;
  now: string;
  holiday: string | null;
  totals: Record<BoardState | "rostered" | "late_missing", number> & { present?: number; left?: number };
  people: BoardRow[];
}

export type DeviceStatus = "online" | "quiet" | "never" | "disabled";

export interface TerminalStatus {
  total: number;
  online: number;
  quiet: number;
  never: number;
  unlinked: number | null;
  devices: Array<{ id: number; name: string; branch: Ref & { code: string }; status: DeviceStatus; last_event_at: string | null; scans_today: number }>;
}

export type ScanAction = "checked_in" | "checked_out" | "seen" | "repeat" | "not_linked" | "stranger" | "ignored" | "module_off";

export interface Scan {
  id: number;
  event_at: string;
  received_at: string;
  device: Ref;
  branch: Ref & { code: string };
  kind: "person" | "stranger" | "other";
  action: ScanAction;
  employee_no: string;
  name_on_device: string;
  member: PersonCard | null;
  record: { id: number; status: string; check_in_at: string | null; check_out_at: string | null; is_late: boolean; late_minutes: number; worked_minutes: number } | null;
  photo_url: string | null;
}

const MODULE = "davomat";

/** A status colour: a face's ring, a chip. */
export type FaceTone = "success" | "warning" | "danger" | "info" | "primary" | "neutral";

export const getBoard = (cid: number, branch: number[], signal?: AbortSignal, date?: string) =>
  http.get<Board>(ownerPath(cid, "attendance/board/"), { branch: branch.length ? branch : undefined, date }, { signal });
export const getTerminalStatus = (cid: number, signal?: AbortSignal) => http.get<TerminalStatus>(ownerPath(cid, "faceid/status/"), undefined, { signal });
export const getScans = (cid: number, params: { date?: string; branch?: number[]; member?: number; page_size?: number }, signal?: AbortSignal) =>
  http.get<Page<Scan>>(ownerPath(cid, "faceid/events/"), { ...params, branch: params.branch?.length ? params.branch : undefined }, { signal });

/** The day board; `date` (company-local) keeps it on the same day as the feed beside it. */
export function useBoard(branch: MaybeRefOrGetter<number[]>, date: MaybeRefOrGetter<string | undefined> = undefined) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => qk(cid.value, MODULE, "board", { branch: toValue(branch), date: toValue(date) })),
    queryFn: ({ signal }) => getBoard(cid.value, toValue(branch), signal, toValue(date)),
    enabled: computed(() => cid.value > 0),
    placeholderData: keepPreviousData,
    refetchInterval: 30_000,
  });
}

export function useTerminalStatus() {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => qk(cid.value, MODULE, "terminals")),
    queryFn: ({ signal }) => getTerminalStatus(cid.value, signal),
    enabled: computed(() => cid.value > 0),
    refetchInterval: 60_000,
  });
}

/** Today's scans, newest first; polled every 10 s while the page is open (the pulse adds the rest). */
export function useTodayScans(params: MaybeRefOrGetter<{ date: string; branch: number[] }>) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => qk(cid.value, MODULE, "scans", { ...toValue(params) })),
    queryFn: ({ signal }) => getScans(cid.value, { ...toValue(params), page_size: 40 }, signal),
    enabled: computed(() => cid.value > 0),
    placeholderData: keepPreviousData,
    refetchInterval: 10_000,
  });
}

// ─── What the board says, as the KPI strip needs it ─────────────────────────

export interface Kpis {
  inside: number;
  expected: number;
  late: number;
  lateMinutes: number;
  notIn: number;
  leave: number;
}

/** In the building (still checked in), expected today, late arrivals with their minutes, missing, on leave. */
export function kpisOf(board: Board | undefined): Kpis {
  if (!board) return { inside: 0, expected: 0, late: 0, lateMinutes: 0, notIn: 0, leave: 0 };
  const rows = board.people;
  const inside = board.totals.present ?? rows.filter((row) => row.record?.status === "open").length;
  const lateRows = rows.filter((row) => row.state === "late");
  return {
    inside,
    expected: board.totals.rostered ?? 0,
    late: lateRows.length,
    lateMinutes: lateRows.reduce((sum, row) => sum + (row.record?.late_minutes ?? 0), 0),
    notIn: board.totals.late_missing ?? 0,
    leave: rows.filter((row) => row.state === "off" && row.reason === "leave").length,
  };
}

/** People still in the building, earliest arrival first. */
export function insideNow(board: Board | undefined): BoardRow[] {
  return (board?.people ?? [])
    .filter((row) => row.record?.status === "open" && row.record.check_in_at)
    .sort((a, b) => (a.record!.check_in_at! < b.record!.check_in_at! ? -1 : 1));
}

/** Who needs a look: late arrivals (most minutes first), then people past their start who aren't in. */
export function attentionOf(board: Board | undefined, focus: "late" | "notIn" | "leave" | null): BoardRow[] {
  const rows = board?.people ?? [];
  const late = rows.filter((row) => row.state === "late").sort((a, b) => (b.record?.late_minutes ?? 0) - (a.record?.late_minutes ?? 0));
  const missing = rows.filter((row) => (row.state === "not_yet" && row.reason === "late") || (row.state === "absent" && !row.record));
  const leave = rows.filter((row) => row.state === "off" && row.reason === "leave");
  if (focus === "late") return late;
  if (focus === "notIn") return missing;
  if (focus === "leave") return leave;
  return [...missing, ...late];
}
