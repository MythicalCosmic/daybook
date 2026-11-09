/** Shapes of the recognition owner endpoints (backend/apps/recognition/owner_api.py), by hand. */

export type Tier = "bronze" | "silver" | "gold";
export type Period = "week" | "month" | "all";
export type BoardKind = "all" | "learning";
export type KudosBadge = "thanks" | "teamwork" | "fast" | "careful" | "helpful" | "star";

export interface RecPerson {
  id: number;
  name: string;
  avatar_url: string | null;
  position: string | null;
}

export interface LevelRef {
  number: number;
  name: string;
}

export interface Level extends LevelRef {
  starts_at: number;
  next_at: number | null;
  next_name?: string | null;
}

export interface BoardRow {
  place: number;
  member: RecPerson;
  points: number;
  level: LevelRef;
  badges: number;
  streak: number;
}

export interface OwnerBoard {
  period: Period;
  kind: BoardKind;
  start: string | null;
  end: string | null;
  rows: BoardRow[];
}

export interface EarnedBadge {
  key: string;
  ref: string;
  name: string;
  description: string;
  icon: string;
  tier: Tier;
  awarded_at: string;
}

export interface HistoryRow {
  id: number;
  points: number;
  reason: string;
  label: string;
  detail: string;
  at: string;
}

export interface Profile {
  member: RecPerson;
  points: number;
  week_points: number;
  month_points: number;
  level: Level;
  streak: number;
  best_streak: number;
  badges: EarnedBadge[];
  history: HistoryRow[];
  kudos_received: number;
  kudos_given: number;
}

export interface Kudos {
  id: number;
  from: RecPerson;
  to: RecPerson;
  badge: KudosBadge;
  badge_label: string;
  message: string;
  task: { id: number; title: string } | null;
  at: string;
  seen: boolean;
  mine: boolean;
}

export interface Holder {
  member: RecPerson;
  ref: string;
  name: string;
  awarded_at: string;
}

export interface CatalogueEntry {
  key: string;
  name: string;
  description: string;
  icon: string;
  tier: Tier;
  count: number;
  holders: Holder[];
}

export interface PointRow {
  key: string;
  label: string;
  default: number;
  points: number;
}

export interface RecognitionSettings {
  points_enabled: boolean;
  leaderboard_for_staff: boolean;
  leaderboard_scope: "company" | "branch";
  task_points: boolean;
  kudos_enabled: boolean;
  kudos_per_day: number;
  post_kudos_to_groups: boolean;
  /** Only the rows that differ from the defaults. */
  points_table: Record<string, number>;
  points: PointRow[];
  levels: Level[];
}

export type SettingsInput = Partial<Omit<RecognitionSettings, "points" | "levels">>;

export interface SendKudosInput {
  to: number;
  badge: KudosBadge;
  message: string;
}
