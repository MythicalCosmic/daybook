/**
 * Attendance endpoints (plan §4.9, `attendance/…`) as typed functions, and the vue-query helpers the
 * pages use. Keys start with `[companyId, "attendance"]`, so the pulse keys in `index.ts`
 * (`attendance.*`) refresh everything here, and switching company never shows another company's data.
 * Mutations update the cache optimistically where an undo makes sense and roll back on error.
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import { computed, toValue, type MaybeRefOrGetter } from "vue";

import { http, ownerPath } from "@/api/http";
import { keys as shellKeys, moduleKey, qk } from "@/api/keys";
import { useCompanyStore } from "@/stores/company";

import type {
  AttendanceSettings,
  AttendanceSummary,
  Board,
  BulkAction,
  Correction,
  MemberMonth,
  Page,
  RecordCreate,
  RecordDetail,
  RecordEdit,
  RecordParams,
  RecordRow,
  Roster,
  Schedule,
  ScheduleInput,
  Shift,
  ShiftInput,
  ShiftPatch,
  ShiftTemplate,
  StaffMember,
  Swap,
  Timesheet,
} from "./types";

export const MODULE = "attendance";

const path = (companyId: number, rest: string) => ownerPath(companyId, `attendance/${rest}`);

// ─── Endpoints ──────────────────────────────────────────────────────────────

export function getBoard(companyId: number, params: { date?: string | null; branch?: number[] }, signal?: AbortSignal): Promise<Board> {
  return http.get<Board>(path(companyId, "board/"), { date: params.date ?? undefined, branch: params.branch?.length ? params.branch : undefined }, { signal });
}

export function listRecords(companyId: number, params: RecordParams, signal?: AbortSignal): Promise<Page<RecordRow>> {
  return http.get<Page<RecordRow>>(path(companyId, "records/"), { ...params, branch: params.branch?.length ? params.branch : undefined }, { signal });
}

export function getRecord(companyId: number, id: number, signal?: AbortSignal): Promise<RecordDetail> {
  return http.get<RecordDetail>(path(companyId, `records/${id}/`), undefined, { signal });
}

export function editRecord(companyId: number, id: number, body: RecordEdit): Promise<RecordRow> {
  return http.patch<RecordRow>(path(companyId, `records/${id}/`), body);
}

export function createRecord(companyId: number, body: RecordCreate): Promise<RecordRow> {
  return http.post<RecordRow>(path(companyId, "records/"), body);
}

export function excuseRecord(companyId: number, id: number, reason: string): Promise<RecordRow> {
  return http.post<RecordRow>(path(companyId, `records/${id}/excuse/`), { reason });
}

export function decideOvertime(companyId: number, id: number, approve: boolean, reason = ""): Promise<RecordRow> {
  return http.post<RecordRow>(path(companyId, `records/${id}/overtime/`), { approve, reason });
}

export function getTimesheet(companyId: number, params: { month: string; branch?: number | null }, signal?: AbortSignal): Promise<Timesheet> {
  return http.get<Timesheet>(path(companyId, "timesheet/"), { month: params.month, branch: params.branch ?? undefined }, { signal });
}

export function getSummary(
  companyId: number,
  params: { from?: string; to?: string; preset?: string; compare?: string; member?: number; branch?: number[] },
  signal?: AbortSignal,
): Promise<AttendanceSummary> {
  return http.get<AttendanceSummary>(path(companyId, "summary/"), { ...params, branch: params.branch?.length ? params.branch : undefined }, { signal });
}

export function getRoster(companyId: number, params: { week: string; branch?: number | null }, signal?: AbortSignal): Promise<Roster> {
  return http.get<Roster>(path(companyId, "roster/"), { week: params.week, branch: params.branch ?? undefined }, { signal });
}

export function createShift(companyId: number, body: ShiftInput): Promise<Shift> {
  return http.post<Shift>(path(companyId, "shifts/"), body);
}

export function updateShift(companyId: number, id: number, body: ShiftPatch): Promise<Shift> {
  return http.patch<Shift>(path(companyId, `shifts/${id}/`), body);
}

export function deleteShift(companyId: number, id: number): Promise<void> {
  return http.delete(path(companyId, `shifts/${id}/`));
}

export function bulkRoster(companyId: number, body: { action: BulkAction; week: string; branch_id?: number | null; member_ids?: number[] }): Promise<{ count: number }> {
  return http.post<{ count: number }>(path(companyId, "shifts/bulk/"), body);
}

export function publishRoster(companyId: number, body: { start: string; end: string; branch_id?: number | null }): Promise<{ count: number }> {
  return http.post<{ count: number }>(path(companyId, "shifts/publish/"), body);
}

export function listSchedules(companyId: number, signal?: AbortSignal): Promise<Schedule[]> {
  return http.get<Schedule[]>(path(companyId, "schedules/"), undefined, { signal });
}

export function createSchedule(companyId: number, body: ScheduleInput): Promise<Schedule> {
  return http.post<Schedule>(path(companyId, "schedules/"), body);
}

export function updateSchedule(companyId: number, id: number, body: Partial<ScheduleInput>): Promise<Schedule> {
  return http.patch<Schedule>(path(companyId, `schedules/${id}/`), body);
}

export function archiveSchedule(companyId: number, id: number): Promise<void> {
  return http.delete(path(companyId, `schedules/${id}/`));
}

export function assignSchedule(companyId: number, id: number, memberIds: number[], effectiveFrom?: string | null): Promise<{ count: number }> {
  return http.post<{ count: number }>(path(companyId, `schedules/${id}/assign/`), { member_ids: memberIds, effective_from: effectiveFrom ?? null });
}

export function unassignSchedule(companyId: number, memberIds: number[]): Promise<{ count: number }> {
  return http.post<{ count: number }>(path(companyId, "schedules/unassign/"), { member_ids: memberIds });
}

export function listTemplates(companyId: number, signal?: AbortSignal): Promise<ShiftTemplate[]> {
  return http.get<ShiftTemplate[]>(path(companyId, "templates/"), undefined, { signal });
}

export function saveTemplate(companyId: number, body: Partial<ShiftTemplate> & { name: string; starts_at: string; ends_at: string }, id?: number): Promise<ShiftTemplate> {
  return id ? http.patch<ShiftTemplate>(path(companyId, `templates/${id}/`), body) : http.post<ShiftTemplate>(path(companyId, "templates/"), body);
}

export function removeTemplate(companyId: number, id: number): Promise<void> {
  return http.delete(path(companyId, `templates/${id}/`));
}

export function listSwaps(companyId: number, status: string, signal?: AbortSignal): Promise<Page<Swap>> {
  return http.get<Page<Swap>>(path(companyId, "swaps/"), { status, page_size: 100 }, { signal });
}

export function decideSwap(companyId: number, id: number, approve: boolean, reason = ""): Promise<Swap> {
  return approve ? http.post<Swap>(path(companyId, `swaps/${id}/approve/`)) : http.post<Swap>(path(companyId, `swaps/${id}/reject/`), { reason });
}

export function listCorrections(companyId: number, status: string, signal?: AbortSignal): Promise<Page<Correction>> {
  return http.get<Page<Correction>>(path(companyId, "corrections/"), { status, page_size: 100 }, { signal });
}

export function decideCorrection(companyId: number, id: number, approve: boolean, reason = ""): Promise<Correction> {
  return http.post<Correction>(path(companyId, `corrections/${id}/decide/`), { approve, reason });
}

export function getSettings(companyId: number, signal?: AbortSignal): Promise<AttendanceSettings> {
  return http.get<AttendanceSettings>(path(companyId, "settings/"), undefined, { signal });
}

export function saveSettings(companyId: number, body: Partial<AttendanceSettings>): Promise<AttendanceSettings> {
  return http.patch<AttendanceSettings>(path(companyId, "settings/"), body);
}

export function listStaff(companyId: number, branch?: number | null, signal?: AbortSignal): Promise<StaffMember[]> {
  return http.get<StaffMember[]>(path(companyId, "staff/"), { branch: branch ?? undefined }, { signal });
}

export function getMemberMonth(companyId: number, memberId: number, month: string, signal?: AbortSignal): Promise<MemberMonth> {
  return http.get<MemberMonth>(path(companyId, `members/${memberId}/`), { month }, { signal });
}

// ─── Keys ───────────────────────────────────────────────────────────────────

export const attendanceKeys = {
  all: (companyId: number) => moduleKey(companyId, MODULE),
  board: (companyId: number, params: object) => qk(companyId, MODULE, "board", { ...params }),
  records: (companyId: number, params: object) => qk(companyId, MODULE, "records", { ...params }),
  record: (companyId: number, id: number) => qk(companyId, MODULE, "record", { id }),
  timesheet: (companyId: number, params: object) => qk(companyId, MODULE, "timesheet", { ...params }),
  summary: (companyId: number, params: object) => qk(companyId, MODULE, "summary", { ...params }),
  roster: (companyId: number, params: object) => qk(companyId, MODULE, "roster", { ...params }),
  rosterAll: (companyId: number) => [companyId, MODULE, "roster"] as const,
  schedules: (companyId: number) => qk(companyId, MODULE, "schedules"),
  templates: (companyId: number) => qk(companyId, MODULE, "templates"),
  swaps: (companyId: number, status: string) => qk(companyId, MODULE, "swaps", { status }),
  swapsAll: (companyId: number) => [companyId, MODULE, "swaps"] as const,
  corrections: (companyId: number, status: string) => qk(companyId, MODULE, "corrections", { status }),
  correctionsAll: (companyId: number) => [companyId, MODULE, "corrections"] as const,
  settings: (companyId: number) => qk(companyId, MODULE, "settings"),
  staff: (companyId: number, branch: number | null) => qk(companyId, MODULE, "staff", { branch }),
  member: (companyId: number, memberId: number, month: string) => qk(companyId, MODULE, "member", { memberId, month }),
};

// ─── Queries ────────────────────────────────────────────────────────────────

export function useCompanyId() {
  const company = useCompanyStore();
  return computed(() => company.currentId ?? 0);
}

export function useBoard(params: MaybeRefOrGetter<{ date: string | null; branch: number[] }>) {
  const companyId = useCompanyId();
  return useQuery({
    queryKey: computed(() => attendanceKeys.board(companyId.value, toValue(params))),
    queryFn: ({ signal }) => getBoard(companyId.value, toValue(params), signal),
    enabled: computed(() => companyId.value > 0),
    placeholderData: keepPreviousData,
    staleTime: 10_000,
    // The board is live: the pulse refreshes it on check-ins, and a minute tick moves "not yet" to "absent".
    refetchInterval: 60_000,
  });
}

export function useRecords(params: MaybeRefOrGetter<RecordParams>, enabled: MaybeRefOrGetter<boolean> = true) {
  const companyId = useCompanyId();
  return useQuery({
    queryKey: computed(() => attendanceKeys.records(companyId.value, toValue(params))),
    queryFn: ({ signal }) => listRecords(companyId.value, toValue(params), signal),
    enabled: computed(() => companyId.value > 0 && toValue(enabled)),
    placeholderData: keepPreviousData,
  });
}

export function useRecord(id: MaybeRefOrGetter<number | null>) {
  const companyId = useCompanyId();
  return useQuery({
    queryKey: computed(() => attendanceKeys.record(companyId.value, toValue(id) ?? 0)),
    queryFn: ({ signal }) => getRecord(companyId.value, toValue(id)!, signal),
    enabled: computed(() => companyId.value > 0 && !!toValue(id)),
  });
}

export function useTimesheet(params: MaybeRefOrGetter<{ month: string; branch: number | null }>) {
  const companyId = useCompanyId();
  return useQuery({
    queryKey: computed(() => attendanceKeys.timesheet(companyId.value, toValue(params))),
    queryFn: ({ signal }) => getTimesheet(companyId.value, toValue(params), signal),
    enabled: computed(() => companyId.value > 0),
    placeholderData: keepPreviousData,
  });
}

export function useSummary(params: MaybeRefOrGetter<{ from?: string; to?: string; preset?: string; compare?: string; branch?: number[]; member?: number }>) {
  const companyId = useCompanyId();
  return useQuery({
    queryKey: computed(() => attendanceKeys.summary(companyId.value, toValue(params))),
    queryFn: ({ signal }) => getSummary(companyId.value, toValue(params), signal),
    enabled: computed(() => companyId.value > 0),
    placeholderData: keepPreviousData,
    staleTime: 60_000,
  });
}

export function useRoster(params: MaybeRefOrGetter<{ week: string; branch: number | null }>) {
  const companyId = useCompanyId();
  return useQuery({
    queryKey: computed(() => attendanceKeys.roster(companyId.value, toValue(params))),
    queryFn: ({ signal }) => getRoster(companyId.value, toValue(params), signal),
    enabled: computed(() => companyId.value > 0),
    placeholderData: keepPreviousData,
  });
}

export function useSchedules() {
  const companyId = useCompanyId();
  return useQuery({
    queryKey: computed(() => attendanceKeys.schedules(companyId.value)),
    queryFn: ({ signal }) => listSchedules(companyId.value, signal),
    enabled: computed(() => companyId.value > 0),
  });
}

export function useTemplates() {
  const companyId = useCompanyId();
  return useQuery({
    queryKey: computed(() => attendanceKeys.templates(companyId.value)),
    queryFn: ({ signal }) => listTemplates(companyId.value, signal),
    enabled: computed(() => companyId.value > 0),
  });
}

export function useSwaps(status: MaybeRefOrGetter<string>) {
  const companyId = useCompanyId();
  return useQuery({
    queryKey: computed(() => attendanceKeys.swaps(companyId.value, toValue(status))),
    queryFn: ({ signal }) => listSwaps(companyId.value, toValue(status), signal),
    enabled: computed(() => companyId.value > 0),
    placeholderData: keepPreviousData,
  });
}

export function useCorrections(status: MaybeRefOrGetter<string>, enabled: MaybeRefOrGetter<boolean> = true) {
  const companyId = useCompanyId();
  return useQuery({
    queryKey: computed(() => attendanceKeys.corrections(companyId.value, toValue(status))),
    queryFn: ({ signal }) => listCorrections(companyId.value, toValue(status), signal),
    enabled: computed(() => companyId.value > 0 && toValue(enabled)),
    placeholderData: keepPreviousData,
  });
}

export function useSettings(enabled: MaybeRefOrGetter<boolean> = true) {
  const companyId = useCompanyId();
  return useQuery({
    queryKey: computed(() => attendanceKeys.settings(companyId.value)),
    queryFn: ({ signal }) => getSettings(companyId.value, signal),
    enabled: computed(() => companyId.value > 0 && toValue(enabled)),
  });
}

export function useStaff(branch: MaybeRefOrGetter<number | null> = null) {
  const companyId = useCompanyId();
  return useQuery({
    queryKey: computed(() => attendanceKeys.staff(companyId.value, toValue(branch))),
    queryFn: ({ signal }) => listStaff(companyId.value, toValue(branch), signal),
    enabled: computed(() => companyId.value > 0),
    staleTime: 5 * 60_000,
  });
}

export function useMemberMonth(memberId: MaybeRefOrGetter<number | null>, month: MaybeRefOrGetter<string>) {
  const companyId = useCompanyId();
  return useQuery({
    queryKey: computed(() => attendanceKeys.member(companyId.value, toValue(memberId) ?? 0, toValue(month))),
    queryFn: ({ signal }) => getMemberMonth(companyId.value, toValue(memberId)!, toValue(month), signal),
    enabled: computed(() => companyId.value > 0 && !!toValue(memberId)),
    placeholderData: keepPreviousData,
  });
}

// ─── Mutations ──────────────────────────────────────────────────────────────

/** Everything attendance shows, plus the shell's queue and pulse (approvals change "Needs you"). */
export function useRefresh() {
  const client = useQueryClient();
  const companyId = useCompanyId();
  return () => {
    void client.invalidateQueries({ queryKey: attendanceKeys.all(companyId.value) });
    void client.invalidateQueries({ queryKey: [companyId.value, "shell", "queue"] });
    void client.invalidateQueries({ queryKey: shellKeys.pulse(companyId.value) });
  };
}

type Listed<T> = Page<T> | undefined;

/** Removes an item from every cached page of a list at once, and returns the snapshot to roll back. */
async function dropFromPages<T extends { id: number }>(client: ReturnType<typeof useQueryClient>, prefix: readonly unknown[], id: number) {
  await client.cancelQueries({ queryKey: prefix });
  const snapshot = client.getQueriesData<Listed<T>>({ queryKey: prefix });
  for (const [key, data] of snapshot) {
    if (!data) continue;
    client.setQueryData<Page<T>>(key, { ...data, count: Math.max(0, data.count - 1), results: data.results.filter((row) => row.id !== id) });
  }
  return snapshot;
}

export function useSwapDecision() {
  const client = useQueryClient();
  const companyId = useCompanyId();
  const refresh = useRefresh();
  return useMutation({
    mutationFn: ({ swap, approve, reason }: { swap: Swap; approve: boolean; reason?: string }) => decideSwap(companyId.value, swap.id, approve, reason),
    onMutate: async ({ swap }) => ({ snapshot: await dropFromPages<Swap>(client, attendanceKeys.swapsAll(companyId.value), swap.id) }),
    onError: (_error, _vars, context) => {
      for (const [key, data] of context?.snapshot ?? []) client.setQueryData(key, data);
    },
    onSettled: refresh,
  });
}

export function useCorrectionDecision() {
  const client = useQueryClient();
  const companyId = useCompanyId();
  const refresh = useRefresh();
  return useMutation({
    mutationFn: ({ correction, approve, reason }: { correction: Correction; approve: boolean; reason?: string }) =>
      decideCorrection(companyId.value, correction.id, approve, reason),
    onMutate: async ({ correction }) => ({ snapshot: await dropFromPages<Correction>(client, attendanceKeys.correctionsAll(companyId.value), correction.id) }),
    onError: (_error, _vars, context) => {
      for (const [key, data] of context?.snapshot ?? []) client.setQueryData(key, data);
    },
    onSettled: refresh,
  });
}

export function useOvertimeDecision() {
  const client = useQueryClient();
  const companyId = useCompanyId();
  const refresh = useRefresh();
  return useMutation({
    mutationFn: ({ record, approve, reason }: { record: { id: number }; approve: boolean; reason?: string }) => decideOvertime(companyId.value, record.id, approve, reason),
    onMutate: async ({ record }) => ({ snapshot: await dropFromPages<RecordRow>(client, [companyId.value, MODULE, "records"], record.id) }),
    onError: (_error, _vars, context) => {
      for (const [key, data] of context?.snapshot ?? []) client.setQueryData(key, data);
    },
    onSettled: refresh,
  });
}

/** Moves or edits a shift in every cached roster at once; the server's answer replaces it. */
export function useShiftUpdate() {
  const client = useQueryClient();
  const companyId = useCompanyId();
  const refresh = useRefresh();
  return useMutation({
    mutationFn: ({ shift, patch }: { shift: Shift; patch: ShiftPatch; optimistic?: Partial<Shift> }) => updateShift(companyId.value, shift.id, patch),
    onMutate: async ({ shift, optimistic }) => {
      const prefix = attendanceKeys.rosterAll(companyId.value);
      await client.cancelQueries({ queryKey: prefix });
      const snapshot = client.getQueriesData<Roster>({ queryKey: prefix });
      if (optimistic) {
        for (const [key, data] of snapshot) {
          if (!data) continue;
          client.setQueryData<Roster>(key, { ...data, shifts: data.shifts.map((row) => (row.id === shift.id ? { ...row, ...optimistic } : row)) });
        }
      }
      return { snapshot };
    },
    onError: (_error, _vars, context) => {
      for (const [key, data] of context?.snapshot ?? []) client.setQueryData(key, data);
    },
    onSettled: refresh,
  });
}

export function useShiftCreate() {
  const companyId = useCompanyId();
  const refresh = useRefresh();
  return useMutation({ mutationFn: (body: ShiftInput) => createShift(companyId.value, body), onSettled: refresh });
}

export function useShiftDelete() {
  const client = useQueryClient();
  const companyId = useCompanyId();
  const refresh = useRefresh();
  return useMutation({
    mutationFn: (shift: Shift) => deleteShift(companyId.value, shift.id),
    onMutate: async (shift) => {
      const prefix = attendanceKeys.rosterAll(companyId.value);
      await client.cancelQueries({ queryKey: prefix });
      const snapshot = client.getQueriesData<Roster>({ queryKey: prefix });
      for (const [key, data] of snapshot) {
        if (data) client.setQueryData<Roster>(key, { ...data, shifts: data.shifts.filter((row) => row.id !== shift.id) });
      }
      return { snapshot };
    },
    onError: (_error, _vars, context) => {
      for (const [key, data] of context?.snapshot ?? []) client.setQueryData(key, data);
    },
    onSettled: refresh,
  });
}
