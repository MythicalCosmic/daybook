/**
 * What the attendance endpoints send (backend/apps/attendance/queries.py payloads), written by
 * hand until the lead regenerates `schema.d.ts`. Times are ISO strings in the company's zone;
 * `start`/`end` are the shift's wall-clock "HH:MM".
 */

export type BranchRef = { id: number; name: string; code: string };

export type BranchGeo = BranchRef & {
  latitude: string | null;
  longitude: string | null;
  geofence_m: number;
};

export type PersonRef = { id: number; name: string };

export type PersonCard = PersonRef & {
  photo_url: string | null;
  position: { id: number; name: string } | null;
  home_branch: { id: number; name: string } | null;
  status: string;
};

export type ShiftStatus = "planned" | "open" | "leave" | "cancelled";

export type Shift = {
  id: number;
  member_id: number | null;
  date: string;
  starts_at: string;
  ends_at: string;
  start: string;
  end: string;
  break_minutes: number;
  minutes: number;
  branch: BranchRef | null;
  position: { id: number; name: string } | null;
  status: ShiftStatus;
  source: "schedule" | "manual" | "swap";
  published: boolean;
  note: string;
  time_off_id: number | null;
  swap_pending: boolean;
  has_record: boolean;
};

export type OpenShift = Shift & { claimed: boolean };

export type RecordStatus = "open" | "closed" | "auto_closed" | "absent" | "excused";

export type AttendanceRecord = {
  id: number;
  member_id: number;
  shift_id: number | null;
  date: string;
  status: RecordStatus;
  check_in_at: string | null;
  check_out_at: string | null;
  in_distance_m: number | null;
  out_distance_m: number | null;
  branch: BranchRef | null;
  late_minutes: number;
  early_leave_minutes: number;
  worked_minutes: number;
  overtime_minutes: number;
  overtime_status: "none" | "pending" | "approved" | "rejected";
  is_late: boolean;
  flags: string[];
  note: string;
  has_photo: boolean;
};

export type DayState = "off" | "upcoming" | "due" | "late" | "in" | "done";

export type MyDay = {
  now: string;
  date: string;
  state: DayState;
  settings: {
    require_location: boolean;
    require_photo: boolean;
    outside_action: "flag" | "reject";
    max_accuracy_m: number;
    grace_minutes: number;
  };
  shift: Shift | null;
  branch: BranchGeo | null;
  record: AttendanceRecord | null;
  next_shift: Shift | null;
  open_shifts: number;
  requests: number;
};

export type CheckResult = {
  record: AttendanceRecord;
  created: boolean;
  outside: boolean;
  distance_m: number | null;
};

/** The timesheet's cell codes (queries.py CELL_*). */
export type CellCode =
  | "present"
  | "late"
  | "absent"
  | "leave"
  | "off"
  | "holiday"
  | "excused"
  | "open"
  | "auto"
  | "planned"
  | "unscheduled";

export type MonthCell = {
  code: CellCode;
  minutes: number;
  late: number;
  record_id: number | null;
  shift_id: number | null;
  flags: string[];
};

export type MonthTotals = {
  scheduled_days?: number;
  attended_days?: number;
  leave_days?: number;
  absent_days?: number;
  worked_minutes?: number;
  approved_overtime_minutes?: number;
  overtime_minutes?: number;
  late_arrivals?: number;
  late_minutes?: number;
  has_schedule?: boolean;
};

export type MyMonth = {
  month: string;
  days: string[];
  today: string;
  holidays: Record<string, string>;
  cells: Record<string, MonthCell>;
  totals: MonthTotals;
};

export type RequestStatus = "pending" | "approved" | "rejected";

export type Correction = {
  id: number;
  date: string;
  check_in_at: string | null;
  check_out_at: string | null;
  reason: string;
  status: RequestStatus;
  decision_note: string;
  record: AttendanceRecord | null;
  created_at: string;
  decided_at: string | null;
};

export type SwapKind = "cover" | "swap" | "claim";
export type SwapStatus = "requested" | "accepted" | "approved" | "rejected" | "cancelled" | "expired";

export type Swap = {
  id: number;
  kind: SwapKind;
  status: SwapStatus;
  shift: Shift;
  other_shift: Shift | null;
  requested_by: PersonRef;
  target: PersonRef | null;
  accepted_by: PersonRef | null;
  note: string;
  decision_note: string;
  expires_at: string | null;
  created_at: string;
  decided_at: string | null;
};

export type MySwaps = { mine: Swap[]; requests: Swap[] };

export type Candidate = { member: PersonCard; shifts: Shift[] };

/** The managers' "Who's in" (`board/`, the same day board the dashboard reads). */
export type BoardState = "in" | "late" | "not_yet" | "absent" | "off";

export type BoardRow = {
  member: PersonCard;
  branch: BranchRef | null;
  state: BoardState;
  /** Why: late (not here yet), leave, day_off, holiday, suspended, no_shift, excused. */
  reason: string | null;
  shift: Shift | null;
  record: AttendanceRecord | null;
};

export type Board = {
  date: string;
  is_today: boolean;
  now: string;
  holiday: string | null;
  totals: Record<BoardState | "rostered" | "late_missing", number>;
  branches: (BranchGeo & { rostered: number; checked_in: number; first_check_in: string | null })[];
  people: BoardRow[];
};
