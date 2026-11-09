/**
 * Shapes of the attendance endpoints (`/owner/companies/{cid}/attendance/…`, package F), written by
 * hand from `apps/attendance/serializers.py` and the dicts in `apps/attendance/queries.py`.
 * Instants are ISO strings in the company's timezone; days are "YYYY-MM-DD"; minutes are integers.
 */
import type { Page } from "@/api/types";

export type { Page };

export interface Ref {
  id: number;
  name: string;
}

export interface BranchRef extends Ref {
  code: string;
}

export interface BranchGeo extends BranchRef {
  latitude: string | null;
  longitude: string | null;
  geofence_m: number;
}

export interface PersonCard {
  id: number;
  name: string;
  photo_url: string | null;
  position: Ref | null;
  home_branch: Ref | null;
  status: string;
}

export type ShiftStatus = "planned" | "open" | "leave" | "cancelled";
export type ShiftSource = "schedule" | "manual" | "swap";

export interface Shift {
  id: number;
  member_id: number | null;
  date: string;
  starts_at: string;
  ends_at: string;
  /** Local "HH:MM". */
  start: string;
  end: string;
  break_minutes: number;
  minutes: number;
  branch: BranchRef | null;
  position: Ref | null;
  status: ShiftStatus;
  source: ShiftSource;
  published: boolean;
  note: string;
  time_off_id: number | null;
  swap_pending: boolean;
  has_record: boolean;
}

export type RecordStatus = "open" | "closed" | "auto_closed" | "absent" | "excused";
export type RecordFlag = "outside_geofence" | "low_accuracy" | "no_location" | "unscheduled" | "auto_closed" | "edited";
export type OvertimeStatus = "none" | "pending" | "approved" | "rejected";
export type RecordSource = "app" | "bot" | "manual" | "system" | "";

export interface AttendanceRecord {
  id: number;
  member_id: number;
  shift_id: number | null;
  date: string;
  status: RecordStatus;
  check_in_at: string | null;
  check_out_at: string | null;
  in_lat: string | null;
  in_lng: string | null;
  in_accuracy_m: number | null;
  in_distance_m: number | null;
  out_lat: string | null;
  out_lng: string | null;
  out_accuracy_m: number | null;
  out_distance_m: number | null;
  branch: BranchRef | null;
  in_source: RecordSource;
  out_source: RecordSource;
  late_minutes: number;
  early_leave_minutes: number;
  worked_minutes: number;
  overtime_minutes: number;
  overtime_status: OvertimeStatus;
  is_late: boolean;
  flags: RecordFlag[];
  note: string;
  has_photo: boolean;
}

export interface RecordRow extends AttendanceRecord {
  member: PersonCard;
  shift: Shift | null;
}

export interface RecordDetail extends RecordRow {
  photo_url: string | null;
  edited_by: string | null;
  branch_geo: BranchGeo | null;
}

// The board ------------------------------------------------------------------------------

export type BoardState = "in" | "late" | "not_yet" | "absent" | "off";
export type BoardReason = "late" | "leave" | "day_off" | "holiday" | "suspended" | "no_shift" | "excused" | null;

export interface BoardRow {
  member: PersonCard;
  branch: BranchRef | null;
  state: BoardState;
  reason: BoardReason;
  shift: Shift | null;
  record: AttendanceRecord | null;
}

export interface BoardBranch extends BranchGeo {
  rostered: number;
  checked_in: number;
  first_check_in: string | null;
}

export interface Board {
  date: string;
  is_today: boolean;
  now: string;
  holiday: string | null;
  /** Per state, plus `rostered`, `late_missing`, and of those who came `present` (still checked in) and `left`. */
  totals: Record<BoardState | "rostered" | "late_missing", number> & { present?: number; left?: number };
  branches: BoardBranch[];
  people: BoardRow[];
}

// Timesheet, summary, roster ---------------------------------------------------------------

export type CellCode = "present" | "late" | "absent" | "leave" | "off" | "holiday" | "excused" | "open" | "auto" | "planned" | "unscheduled";

export interface Cell {
  code: CellCode;
  minutes: number;
  late: number;
  record_id: number | null;
  shift_id: number | null;
  flags: RecordFlag[];
}

export interface PeriodTotals {
  scheduled_days: number;
  attended_days: number;
  leave_days: number;
  leave_time_off_ids: number[];
  absent_days: number;
  worked_minutes: number;
  approved_overtime_minutes: number;
  late_arrivals: number;
  late_minutes: number;
  holiday_worked_days: number;
  has_schedule: boolean;
  overtime_minutes?: number;
}

export interface TimesheetRow {
  member: PersonCard;
  totals: PeriodTotals;
  cells: Record<string, Cell>;
}

export interface Timesheet {
  month: string;
  days: string[];
  today: string;
  holidays: Record<string, string>;
  people: TimesheetRow[];
}

export interface SummaryTotals {
  present: number;
  late: number;
  absent: number;
  rostered: number;
  on_time_percent: string | null;
  attendance_percent: string | null;
  worked_hours: string;
}

export interface AttendanceSummary {
  range: { from: string; to: string };
  compare: { from: string; to: string } | null;
  currency: string;
  totals: SummaryTotals;
  previous: SummaryTotals | null;
  series: Array<{ date: string; present: number; late: number; absent: number; rostered: number }>;
  breakdown: Array<{ key: string; label: string; present: number; late: number; absent: number; rostered: number }>;
}

export interface RosterMember extends PersonCard {
  schedule: Ref | null;
  minutes: number;
  leave: string[];
}

export interface ShiftTemplate {
  id: number;
  name: string;
  starts_at: string;
  ends_at: string;
  break_minutes: number;
  color: number;
  position_id: number | null;
  order: number;
  is_active: boolean;
}

export interface Roster {
  week: string;
  days: string[];
  holidays: Record<string, string>;
  members: RosterMember[];
  shifts: Shift[];
  unpublished: number;
  coverage: Record<string, { planned: number; open: number; minutes: number }>;
  templates: ShiftTemplate[];
}

// Schedules ------------------------------------------------------------------------------

export type ScheduleKind = "weekly" | "rotating" | "flexible";

export interface ScheduleDay {
  weekday: number;
  starts_at: string;
  ends_at: string;
  break_minutes: number;
}

export interface Schedule {
  id: number;
  name: string;
  kind: ScheduleKind;
  color: number;
  days: ScheduleDay[];
  rotation: string;
  rotation_start: string | null;
  rotation_starts_at: string | null;
  rotation_ends_at: string | null;
  rotation_break_minutes: number;
  is_active: boolean;
  member_ids: number[];
  weekly_minutes: number;
}

export type ScheduleInput = Omit<Schedule, "id" | "is_active" | "member_ids" | "weekly_minutes">;

// Swaps and corrections ------------------------------------------------------------------

export type SwapKind = "cover" | "swap" | "claim";
export type SwapStatus = "requested" | "accepted" | "approved" | "rejected" | "cancelled" | "expired";

export interface Swap {
  id: number;
  kind: SwapKind;
  status: SwapStatus;
  shift: Shift;
  other_shift: Shift | null;
  requested_by: Ref;
  target: Ref | null;
  accepted_by: Ref | null;
  note: string;
  decision_note: string;
  expires_at: string;
  created_at: string;
  decided_at: string | null;
}

export type CorrectionStatus = "pending" | "approved" | "rejected";

export interface Correction {
  id: number;
  member: PersonCard;
  date: string;
  check_in_at: string | null;
  check_out_at: string | null;
  reason: string;
  status: CorrectionStatus;
  decision_note: string;
  record: AttendanceRecord | null;
  created_at: string;
  decided_at: string | null;
}

// Settings and one person ----------------------------------------------------------------

export interface AttendanceSettings {
  require_location: boolean;
  require_photo: boolean;
  outside_action: "flag" | "reject";
  grace_minutes: number;
  early_leave_grace_minutes: number;
  remind_after_minutes: number;
  no_show_alert_minutes: number;
  auto_close_after_hours: number;
  max_accuracy_m: number;
  tasks_follow_shifts: boolean;
  swaps_need_approval: boolean;
  open_shift_claim_needs_approval: boolean;
  pre_shift_reminder_minutes: number;
  early_check_in_minutes: number;
  overtime_after_minutes: number;
}

export interface MemberMonth {
  member: PersonCard;
  schedule: Ref | null;
  month: string;
  days: string[];
  today: string;
  holidays: Record<string, string>;
  cells: Record<string, Cell>;
  totals: PeriodTotals;
  summary: SummaryTotals;
  records: AttendanceRecord[];
  next_shifts: Shift[];
}

export interface StaffMember extends PersonCard {
  schedule: Ref | null;
}

// Writes ---------------------------------------------------------------------------------

export interface ShiftInput {
  member_id?: number | null;
  date: string;
  start: string;
  end: string;
  break_minutes?: number;
  branch_id?: number | null;
  position_id?: number | null;
  note?: string;
  publish?: boolean;
}

export type ShiftPatch = Partial<Omit<ShiftInput, "publish">>;

export type BulkAction = "copy_week" | "apply_schedule" | "clear";

export interface RecordEdit {
  check_in_at?: string | null;
  check_out_at?: string | null;
  note?: string;
  reason: string;
}

export interface RecordCreate {
  member_id: number;
  date: string;
  check_in_at: string;
  check_out_at: string;
  reason: string;
  note?: string;
}

export interface RecordParams {
  from?: string;
  to?: string;
  member?: number;
  flag?: RecordFlag;
  status?: RecordStatus;
  overtime?: OvertimeStatus;
  branch?: number[];
  page?: number;
  page_size?: number;
  ordering?: string;
}

// ─── Reports (`attendance/reports/…`, apps/attendance/analytics.py) ─────────────

/** The five reports; each also downloads as Excel or PDF (`?format=xlsx|pdf`). */
export type ReportKind = "summary" | "departments" | "branches" | "trend" | "punctuality";
export type ReportFormat = "xlsx" | "pdf";

/** The sums every report row shows. Minutes are integers; percents have one decimal, null without a base. */
export interface ReportFigures {
  /** Days with a planned shift (the only days that can be absences). */
  days_scheduled: number;
  /** Days with a check-in, planned or not. */
  days_present: number;
  days_absent: number;
  days_leave: number;
  days_excused: number;
  worked_minutes: number;
  late_count: number;
  late_minutes: number;
  early_leave_count: number;
  early_leave_minutes: number;
  /** Not rejected (approved or waiting). */
  overtime_minutes: number;
  /** Check-ins for a planned shift, and those on time. */
  arrivals: number;
  on_time: number;
  punctuality_percent: number | null;
  attendance_percent: number | null;
}

export interface ReportTotals extends ReportFigures {
  people: number;
}

export interface ReportEmployee {
  /** The membership id. */
  id: number;
  name: string;
  photo_url: string | null;
  position: Ref | null;
  department: Ref | null;
  /** Their home branch. */
  branch: Ref | null;
}

interface ReportBase {
  range: { from: string; to: string };
  /** The last day counted (today when the period runs past it); null before the period starts. */
  counted_until: string | null;
  today: string;
  totals: ReportTotals;
}

export interface PersonReportRow extends ReportFigures {
  employee: ReportEmployee;
}

export interface DepartmentReportRow extends ReportFigures {
  /** null: people without a department. */
  department: Ref | null;
  people: number;
}

export interface BranchReportRow extends ReportFigures {
  /** null: days that belong to no branch. */
  branch: BranchRef | null;
  people: number;
}

export interface PeopleReport extends ReportBase {
  rows: PersonReportRow[];
  /** With `compare`: the period compared with and its totals (the KPIs' change). */
  compare?: { from: string; to: string } | null;
  previous?: ReportTotals | null;
}

export interface DepartmentReport extends ReportBase {
  rows: DepartmentReportRow[];
}

export interface BranchReport extends ReportBase {
  rows: BranchReportRow[];
}

export interface TrendDay {
  date: string;
  scheduled: number;
  present: number;
  /** Of the people expected that day, how many came (the attendance rate's top). */
  expected_present: number;
  /** People late that day. */
  late: number;
  absent: number;
  leave: number;
  excused: number;
  worked_minutes: number;
  punctuality_percent: number | null;
}

export interface TrendReport extends ReportBase {
  days: TrendDay[];
}

export interface RankingRow {
  /** Equal punctuality and late minutes share a rank. */
  rank: number;
  employee: ReportEmployee;
  punctuality_percent: number | null;
  arrivals: number;
  on_time: number;
  late_count: number;
  late_minutes: number;
  average_late_minutes: number;
  days_present: number;
}

export interface PunctualityReport extends ReportBase {
  /** The whole selection's punctuality. */
  average: number | null;
  /** The most punctual first. */
  rows: RankingRow[];
}

export interface ReportOf {
  summary: PeopleReport;
  departments: DepartmentReport;
  branches: BranchReport;
  trend: TrendReport;
  punctuality: PunctualityReport;
}

/** Company-local days, both included; branches within the caller's scope; departments with the ones below them. */
export interface ReportParams {
  /** The period's days (also when a preset is sent, for names and labels). */
  from: string;
  to: string;
  /** A preset ("month"…) is sent instead of from/to, so the server compares like with like. */
  preset?: string;
  /** The summary's `previous` totals: the period before, or the same days a year before. */
  compare?: "prev" | "year";
  branch?: number[];
  department?: number[];
}

/** One row of the members app's `GET departments/` that the filter needs (tree order). */
export interface DepartmentOption {
  id: number;
  name: string;
  parent_id: number | null;
  /** Names from the top down to it. */
  path: string[];
}
