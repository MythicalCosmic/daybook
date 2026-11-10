/**
 * The org chart's shapes (`GET lifecycle/org/`, backend/apps/lifecycle/orgchart), hand-written until
 * the lead regenerates the schema types. Dates are ISO days ("2026-11-20").
 */

export interface OrgRef {
  id: number;
  name: string;
  photo_url: string | null;
  /** The job title's name. */
  position: string | null;
}

export interface OrgDepartment {
  id: number;
  name: string;
  parent_id: number | null;
  /** 1 at the top. */
  depth: number;
  head: OrgRef | null;
  /** People the viewer sees directly in it. */
  headcount: number;
  /** With every department below it. */
  total: number;
}

export interface OrgBranch {
  id: number;
  name: string;
  code: string;
  manager: OrgRef | null;
  headcount: number;
}

export interface OrgPosition {
  id: number;
  name: string;
  order: number;
}

export interface OrgLeaving {
  id: number;
  status: "requested" | "agreed";
  day: string | null;
}

export interface OrgChange {
  id: number;
  status: "proposed" | "approved";
  effective_on: string;
  parts: string[];
}

/** Why the viewer can't move someone: no right (hr.manage), themselves, or an owner. */
export type WhyNot = "rights" | "self" | "owner";

export interface OrgPerson {
  id: number;
  name: string;
  photo_url: string | null;
  position_id: number | null;
  department_id: number | null;
  home_branch_id: number | null;
  /** Where the branch view puts them (their home branch when the viewer sees it). */
  branch_id: number | null;
  /** Their nearest head. */
  manager_id: number | null;
  is_owner: boolean;
  status: "approved" | "suspended";
  suspended_until: string | null;
  on_leave_until: string | null;
  leaving: OrgLeaving | null;
  /** The next job change waiting for them. */
  change: OrgChange | null;
  may_move: boolean;
  why_not: WhyNot | null;
}

export interface OrgVacancy {
  id: number;
  title: string;
  position_id: number | null;
  branch_id: number | null;
  /** Where the department view puts it (null: at the top). */
  department_id: number | null;
  /** Applicants still in the running. */
  applicants: number;
  /** Applicants nobody has looked at yet. */
  new: number;
}

export interface OrgCan {
  /** Proposes job changes (hr.manage). */
  move: boolean;
  /** May approve a move in the same step. */
  decide: boolean;
  /** Opens vacancies (hr.hiring). */
  hiring: boolean;
  /** Edits the departments. */
  structure: boolean;
}

export interface OrgChart {
  today: string;
  company: { id: number; name: string };
  owners: OrgRef[];
  /** Parents before children. */
  departments: OrgDepartment[];
  branches: OrgBranch[];
  positions: OrgPosition[];
  people: OrgPerson[];
  vacancies: OrgVacancy[];
  can: OrgCan;
}

export type OrgView = "department" | "branch";
export const ORG_VIEWS = ["department", "branch"] as const;
