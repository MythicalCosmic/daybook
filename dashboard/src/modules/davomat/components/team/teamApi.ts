/**
 * What the Team pages read besides `../../api.ts` and the Overview's fetchers
 * (`../overview/overviewApi.ts`: the board, the terminals' status, the scans): one person's
 * attendance month (`attendance/members/{id}/`) and their scans of one day. The shapes are the
 * fields these pages show, copied from those modules' endpoints (modules share data through the
 * API, never through code).
 *
 * The per-person keys sit under the module whose data they are (`[cid, "attendance", …]`,
 * `[cid, "faceid", …]`), so a check-in or a scan refreshes them through that module's pulse.
 */
import { keepPreviousData, useMutation, useQuery } from "@tanstack/vue-query";
import { computed, toValue, type MaybeRefOrGetter } from "vue";

import { http, ownerPath } from "@/api/http";
import { qk } from "@/api/keys";
import { useCompanyId } from "@/stores/company";

import { employeeLeaves, employeeReturns, importEmployees, uploadEmployeePhoto, useRefresh } from "../../api";
import { getScans, type Board } from "../overview/overviewApi";

// ─── Attendance: one person's month ─────────────────────────────────────────

export type CellCode = "present" | "late" | "absent" | "leave" | "off" | "holiday" | "excused" | "open" | "auto" | "planned" | "unscheduled";

export interface MonthCell {
  code: CellCode;
  minutes: number;
  late: number;
  record_id: number | null;
  shift_id: number | null;
}

export interface MonthTotals {
  scheduled_days: number;
  attended_days: number;
  leave_days: number;
  absent_days: number;
  worked_minutes: number;
  approved_overtime_minutes: number;
  late_arrivals: number;
  late_minutes: number;
  has_schedule: boolean;
}

export interface MemberMonth {
  schedule: { id: number; name: string } | null;
  month: string;
  days: string[];
  today: string;
  holidays: Record<string, string>;
  cells: Record<string, MonthCell>;
  totals: MonthTotals;
}

export const getMemberMonth = (cid: number, id: number, month: string, signal?: AbortSignal) =>
  http.get<MemberMonth>(ownerPath(cid, `attendance/members/${id}/`), { month }, { signal });

export function useMemberMonth(id: MaybeRefOrGetter<number>, month: MaybeRefOrGetter<string>) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => qk(cid.value, "attendance", "davomat.month", { id: toValue(id), month: toValue(month) })),
    queryFn: ({ signal }) => getMemberMonth(cid.value, toValue(id), toValue(month), signal),
    enabled: computed(() => cid.value > 0 && toValue(id) > 0),
    placeholderData: keepPreviousData,
  });
}

// ─── Face ID: one person's scans of one day ─────────────────────────────────

export function useMemberScans(member: MaybeRefOrGetter<number>, date: MaybeRefOrGetter<string>) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => qk(cid.value, "faceid", "davomat.scans", { member: toValue(member), date: toValue(date) })),
    queryFn: ({ signal }) => getScans(cid.value, { member: toValue(member), date: toValue(date), page_size: 100 }, signal),
    enabled: computed(() => cid.value > 0 && toValue(member) > 0 && !!toValue(date)),
    placeholderData: keepPreviousData,
  });
}

// ─── Attendance: today per location ─────────────────────────────────────────

/** The board's numbers per location (`attendance/board/` sends them next to the people). */
export interface BoardBranch {
  id: number;
  name: string;
  rostered: number;
  checked_in: number;
  first_check_in: string | null;
}

export function branchesOf(board: Board | undefined): BoardBranch[] {
  return (board as (Board & { branches?: BoardBranch[] }) | undefined)?.branches ?? [];
}

// ─── Positions: show a hidden one again ─────────────────────────────────────

export const setPositionActive = (cid: number, id: number, active: boolean) =>
  http.patch<{ id: number }>(ownerPath(cid, `positions/${id}/`), { is_active: active }, { toast: false });

// ─── Employee writes ────────────────────────────────────────────────────────

export function useLeave() {
  const cid = useCompanyId();
  const refresh = useRefresh();
  return useMutation({ mutationFn: ({ id, date }: { id: number; date: string }) => employeeLeaves(cid.value, id, date), onSuccess: refresh });
}

export function useReturn() {
  const cid = useCompanyId();
  const refresh = useRefresh();
  return useMutation({ mutationFn: (id: number) => employeeReturns(cid.value, id), onSuccess: refresh });
}

export function usePhotoUpload() {
  const cid = useCompanyId();
  const refresh = useRefresh();
  return useMutation({ mutationFn: ({ id, photo }: { id: number; photo: Blob }) => uploadEmployeePhoto(cid.value, id, photo), onSuccess: refresh });
}

export function useImport() {
  const cid = useCompanyId();
  return useMutation({ mutationFn: ({ file, dryRun }: { file: File; dryRun: boolean }) => importEmployees(cid.value, file, dryRun) });
}
