/**
 * Response shapes of the projects endpoints (`apps/projects/serializers.py`, owner API under
 * `/api/v1/owner/companies/{cid}/projects/`), written by hand. Money is a decimal string, days are
 * company-local "YYYY-MM-DD", moments ISO strings. Colours are palette keys ("chart-1" … "chart-8").
 */
import type { Currency, Money } from "@/api/types";

export type ProjectStatus = "planning" | "active" | "on_hold" | "completed" | "cancelled";
export type ProjectPriority = "low" | "normal" | "high";
export type Visibility = "members" | "company";
export type Health = "on_track" | "at_risk" | "off_track";
export type MemberRole = "lead" | "member" | "viewer";
export type TaskStatus = "todo" | "in_progress" | "review" | "returned" | "done" | "cancelled";
export type TaskPriority = "low" | "normal" | "high" | "urgent";
export type Proof = "none" | "photo" | "text" | "any";
export type PaletteColor = "" | `chart-${1 | 2 | 3 | 4 | 5 | 6 | 7 | 8}`;

export const PROJECT_STATUSES: readonly ProjectStatus[] = ["planning", "active", "on_hold", "completed", "cancelled"];
export const HEALTHS: readonly Health[] = ["on_track", "at_risk", "off_track"];
export const PALETTE: readonly PaletteColor[] = ["chart-1", "chart-2", "chart-3", "chart-4", "chart-5", "chart-6", "chart-7", "chart-8"];

export interface Person {
  id: number;
  name: string;
  photo_url: string | null;
}

export interface Ref {
  id: number;
  name: string;
}

export interface Progress {
  done: number;
  total: number;
  overdue: number;
  percent: number;
}

export interface Reported {
  health: Health;
  text: string;
  at: string;
  author: Person | null;
}

export interface ProjectItem {
  id: number;
  key: string;
  name: string;
  color: PaletteColor;
  icon: string;
  status: ProjectStatus;
  priority: ProjectPriority;
  visibility: Visibility;
  lead: Person | null;
  branch: Ref | null;
  client: Ref | null;
  start_on: string | null;
  due_on: string | null;
  completed_at: string | null;
  archived_at: string | null;
  progress: Progress;
  health: Health | null;
  reported: Reported | null;
  members: Person[];
  member_count: number;
  next_milestone: { id: number; name: string; due_on: string | null } | null;
  my_role: MemberRole | null;
  currency: Currency;
  budget: Money | null;
  budget_currency: Currency;
  /** Only for people who see the project's money. */
  spent?: Money | null;
  burn?: number | null;
}

export interface BoardList {
  id: number;
  name: string;
  position: number;
  is_done: boolean;
  wip_limit: number | null;
}

export interface Label {
  id: number;
  name: string;
  color: PaletteColor;
}

export interface Milestone {
  id: number;
  name: string;
  description: string;
  due_on: string | null;
  status: "open" | "done";
  completed_at: string | null;
  position: number;
  done: number;
  total: number;
  percent: number;
  overdue: boolean;
}

export interface Capabilities {
  manage: boolean;
  edit_cards: boolean;
  /** Cards may go to other people: with tasks.assign, or as the project's lead (to its people). */
  assign_others: boolean;
  post_update: boolean;
  see_money: boolean;
  add_expense: boolean;
  see_labour: boolean;
  see_all_time: boolean;
}

export interface ProjectDetail extends ProjectItem {
  description: string;
  created_at: string;
  created_by: Person | null;
  lists: BoardList[];
  labels: Label[];
  milestones: Milestone[];
  capabilities: Capabilities;
}

export interface Card {
  id: number;
  number: number | null;
  key: string;
  title: string;
  list_id: number | null;
  position: number;
  status: TaskStatus;
  priority: TaskPriority;
  due_at: string | null;
  start_on: string | null;
  assignee: Person | null;
  label_ids: number[];
  milestone_id: number | null;
  checklist_done: number;
  checklist_total: number;
  comments: number;
  proof: Proof;
  proof_thumb: string | null;
  needs_confirmation: boolean;
  overdue: boolean;
  completed_at: string | null;
  minutes: number;
  can_move: boolean;
}

export interface Board {
  project: ProjectItem;
  lists: BoardList[];
  cards: Card[];
  labels: Label[];
  milestones: Milestone[];
  people: Person[];
  capabilities: Capabilities;
}

export interface TimeEntry {
  id: number;
  person: Person;
  project: Ref | null;
  project_key: string | null;
  task: Ref | null;
  day: string;
  minutes: number;
  note: string;
  billable: boolean;
  source: "manual" | "timer";
  created_at: string;
  can_edit: boolean;
}

export interface CardDetail extends Card {
  description: string;
  created_at: string;
  created_by: Person | null;
  checklist: Array<{ id: number; text: string; is_done: boolean }>;
  recent_comments: Array<{ id: number; author: Person | null; text: string; created_at: string }>;
  time: TimeEntry[];
  actions: string[];
  can_edit_task: boolean;
  proof_text: string;
  proof_photo: string | null;
}

export interface MoveResult {
  card: Card;
  message: string;
}

export interface Member {
  id: number | null;
  person: Person;
  position: string;
  role: MemberRole;
  open: number;
  review: number;
  done: number;
  overdue: number;
  week_minutes: number;
}

export interface Update {
  id: number;
  health: Health;
  text: string;
  author: Person | null;
  created_at: string;
}

export interface ProjectFile {
  id: number;
  name: string;
  kind: "pdf" | "xlsx" | "csv" | "image";
  size: number;
  url: string;
  uploaded_by: Person | null;
  created_at: string;
  can_delete: boolean;
}

export interface ProjectLink {
  id: number;
  title: string;
  url: string;
  added_by: Person | null;
  created_at: string;
  can_delete: boolean;
}

export interface Timer {
  id: number;
  person: Person;
  project: Ref | null;
  project_key: string | null;
  task: Ref | null;
  task_key: string | null;
  started_at: string;
  note: string;
}

export interface TimeWeek {
  start: string;
  end: string;
  days: string[];
  rows: Array<{ person: Person; days: number[]; total: number; billable: number }>;
  totals: number[];
  total: number;
  billable: number;
  entries: TimeEntry[];
  running: Timer[];
}

export interface Financials {
  currency: Currency;
  budget: Money | null;
  budget_original: Money | null;
  budget_currency: Currency;
  spent: Money;
  income: Money;
  receivable: Money;
  /** Only for payroll.view holders; null until payroll knows the rates. */
  labour_cost?: Money | null;
  margin: Money;
  margin_includes_labour: boolean;
  burn: number | null;
  remaining: Money | null;
  by_category: Array<{ category_id: number | null; name: string; color: string; amount: Money }>;
  by_month: Array<{ month: string; spent: Money; income: Money }>;
  transactions: Array<{
    id: number;
    occurred_on: string;
    kind: string;
    status: string;
    amount: Money;
    currency: Currency;
    base_amount: Money;
    category: string;
    account: string;
    counterparty: string;
    description: string;
    hidden: boolean;
  }>;
}

export interface ExpenseOptions {
  accounts: Array<{ id: number; name: string; currency: Currency; kind: string; balance: Money }>;
  categories: Array<{ id: number; name: string; parent_id: number | null; color: string }>;
  counterparties: Ref[];
}

export interface TimelineRow {
  id: number;
  key: string;
  title: string;
  status: TaskStatus;
  list: string;
  list_id: number | null;
  milestone_id: number | null;
  assignee: Person | null;
  start: string;
  end: string;
  has_due: boolean;
  progress: number;
  editable: boolean;
  overdue: boolean;
}

export interface Timeline {
  project: { start: string; end: string };
  rows: TimelineRow[];
  milestones: Array<{ id: number; name: string; date: string; done: boolean }>;
}

export interface RoadmapRow extends ProjectItem {
  start: string;
  end: string;
  editable: boolean;
  milestones: Array<{ id: number; name: string; date: string; done: boolean }>;
}

export interface ProjectsSummary {
  active: number;
  planning: number;
  at_risk: number;
  off_track: number;
  overdue_cards: number;
  due_this_week: number;
  hours_this_week: number;
  budget: Money | null;
  spent: Money | null;
  currency: Currency;
}

export interface PersonOption extends Person {
  position: string;
}

export interface ProjectOptions {
  branches: Ref[];
  clients: Ref[];
  currency: Currency;
  can_create: boolean;
}

export interface ProjectSettings {
  default_lists: string[];
  custom_lists: boolean;
  weekly_nudge: boolean;
  nudge_weekday: number;
  at_risk_days: number;
  at_risk_percent: number;
  can_edit: boolean;
}

/** What the create/edit form sends. */
export interface ProjectInput {
  name: string;
  key?: string;
  description?: string;
  color?: PaletteColor;
  icon?: string;
  status?: ProjectStatus;
  priority?: ProjectPriority;
  visibility?: Visibility;
  lead?: number | null;
  branch?: number | null;
  client?: number | null;
  start_on?: string | null;
  due_on?: string | null;
  budget?: Money | null;
  budget_currency?: Currency;
  member_ids?: number[];
}

export interface CardInput {
  title: string;
  list?: number | null;
  assignee?: number | null;
  due_at?: string | null;
  priority?: TaskPriority;
  description?: string;
  milestone?: number | null;
  label_ids?: number[];
  checklist?: string[];
  start_on?: string | null;
}

export interface ListParams {
  status?: string[];
  health?: string[];
  lead?: string[];
  branch?: string[];
  q?: string;
  mine?: boolean;
  archived?: boolean;
  ordering?: string;
}

export type ProjectTab = "board" | "list" | "timeline" | "milestones" | "people" | "time" | "money" | "updates" | "files" | "settings";
export const PROJECT_TABS: readonly ProjectTab[] = ["board", "list", "timeline", "milestones", "people", "time", "money", "updates", "files", "settings"];
