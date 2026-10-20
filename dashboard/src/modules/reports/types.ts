/** Shapes of the team reports endpoints (plan §4.5 `reports/`, analytics shape of §4). */
import type { Range } from "@/api/types";

export type GroupBy = "member" | "position" | "routine" | "branch" | "day";

export interface Score {
  total: number;
  done: number;
  on_time: number;
  late: number;
  missed: number;
  on_time_percent: number | null;
  late_now: number;
  reminders: number;
  avg_delay_minutes: number | null;
}

export interface TrendPoint {
  date: string;
  total: number;
  done: number;
  on_time: number;
  late: number;
  missed: number;
  on_time_percent: number | null;
}

export interface TeamRow extends Score {
  key: string;
  label: string;
  position?: string | null;
  member?: { id: number; name: string; photo_url: string | null; position: string | null };
  previous_on_time_percent: number | null;
}

export interface TeamReport {
  range: Range;
  compare: Range | null;
  group_by: GroupBy;
  totals: Score;
  previous: Score | null;
  series: TrendPoint[];
  breakdown: TeamRow[];
}

export interface RoutineRow {
  key: string;
  label: string;
  id: number;
  title: string;
  is_active: boolean;
  branch: string | null;
  made: number;
  on_time: number;
  late: number;
  missed: number;
  on_time_percent: number | null;
  completion_percent: number | null;
  people: number;
  previous_on_time_percent: number | null;
}

export interface RoutineReport {
  range: Range;
  compare: Range | null;
  totals: { routines: number; made: number; on_time: number; late: number; missed: number; on_time_percent: number | null; completion_percent: number | null; idle: number };
  previous: RoutineReport["totals"] | null;
  series: TrendPoint[];
  breakdown: RoutineRow[];
}
