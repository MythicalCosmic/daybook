/**
 * The Flows endpoints' shapes (briefs/v3-contract.md §4.7, `/api/v1/owner/companies/{cid}/ai/flows/…`),
 * typed by hand until the owner schema has them.
 */

// ─── The catalog: what a flow can be built from ─────────────────────────────

export type FlowFieldType = "bool" | "int" | "time" | "choice" | "text" | "template" | "person" | "branches" | "weekdays" | "model";

/** A setting of a trigger or a step: the agents' field shape plus the new types. */
export interface FlowField {
  key: string;
  type: FlowFieldType;
  label: string;
  help: string;
  required: boolean;
  default: FlowValue;
  min?: number;
  max?: number;
  max_length?: number;
  unit?: string;
  options?: { value: string; label: string }[];
  placeholder?: string;
}

/**
 * A setting's value: bool, int, "HH:MM", a choice, text with {variables}, a membership id (null =
 * none yet), branch ids ([] = all), ISO weekdays 1–7, or a model id ("" = the company's flows model).
 */
export type FlowValue = boolean | number | string | number[] | null;
export type FlowConfig = Record<string, FlowValue>;

export interface FlowVariable {
  key: string;
  label: string;
  example: string;
}

export type TriggerUnavailable = "" | "module_off" | string;

export interface TriggerDef {
  key: string;
  name: string;
  description: string;
  /** A lucide icon name ("alarm-clock"). */
  icon: string;
  available: boolean;
  unavailable_reason: TriggerUnavailable;
  /** What a run is about: "task", "member", "draft", "shift", "time_off" or "". */
  subject: string;
  fields: FlowField[];
  variables: FlowVariable[];
}

export type StepKind = "ai" | "action";

export interface StepDef {
  key: string;
  name: string;
  description: string;
  icon: string;
  kind: StepKind;
  needs_claude: boolean;
  /** The triggers this step fits; null = every trigger. */
  triggers: string[] | null;
  fields: FlowField[];
  outputs: { key: string; label: string }[];
}

export interface TemplateDef {
  key: string;
  name: string;
  description: string;
  icon: string;
  trigger: FlowTrigger;
  steps: FlowStep[];
  available: boolean;
  unavailable_reason: string;
  best_with_claude: boolean;
}

export interface FlowModel {
  id: string;
  name: string;
}

export interface FlowCatalog {
  triggers: TriggerDef[];
  steps: StepDef[];
  templates: TemplateDef[];
  models: FlowModel[];
  limits: { flows: number; steps: number };
}

// ─── A flow ─────────────────────────────────────────────────────────────────

export interface FlowTrigger {
  type: string;
  config: FlowConfig;
}

export type WhenOp = "eq" | "ne";

/** Run the step only if an earlier step's output equals (or doesn't equal) a value. */
export interface StepWhen {
  step: string;
  output: string;
  op: WhenOp;
  value: string;
}

export interface FlowStep {
  /** "s1", "s2"… stable across reorders: later steps' templates name it ({s1.text}). */
  id: string;
  type: string;
  config: FlowConfig;
  when: StepWhen | null;
}

export type FlowProblemCode = "needs_claude" | "module_off" | "owner_gone" | "too_many_runs" | "person_gone" | string;

export interface FlowProblem {
  code: FlowProblemCode;
  text: string;
}

export type RunStatus = "queued" | "running" | "done" | "skipped" | "failed";

export interface Flow {
  id: number;
  name: string;
  description: string;
  enabled: boolean;
  template: string;
  trigger: FlowTrigger;
  /** Translated: "A task is 2 hours late". */
  trigger_text: string;
  steps: FlowStep[];
  version: number;
  stats: { today: number; week: number };
  last_run: { id: number; status: RunStatus; at: string } | null;
  problems: FlowProblem[];
  owner: { id: number; name: string } | null;
  created_at: string;
  updated_at: string;
}

/** The body of `PATCH ai/flows/<id>/`: any of these. */
export interface FlowPatch {
  name?: string;
  description?: string;
  enabled?: boolean;
  trigger?: FlowTrigger;
  steps?: FlowStep[];
}

export type FlowCreate = { template: string } | { name: string; description?: string; trigger: FlowTrigger; steps: FlowStep[] };

// ─── Runs ───────────────────────────────────────────────────────────────────

export type StepRunStatus = "done" | "skipped" | "failed" | "preview" | "pending";
export type StepEngine = "claude" | "template" | "fake" | "";

export interface StepResult {
  id: string;
  type: string;
  name: string;
  status: StepRunStatus;
  /** One line in the reader's language ("Would send to Alisher Valiyev: …"). */
  summary: string;
  output: Record<string, unknown>;
  engine: StepEngine;
  model: string;
  ms: number;
  error: string;
}

export interface FlowRun {
  id: number;
  flow_id: number;
  flow_name: string;
  status: RunStatus;
  test: boolean;
  /** Translated: "Muzlatgich haroratini tekshirish — Alisher Valiyev, 2 soat kechikdi". */
  trigger_text: string;
  subject: { type: string; id: number; label: string } | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  /** "0.0011" */
  cost_usd: string;
  steps: StepResult[];
}

export interface RunsPage {
  results: FlowRun[];
  next_before: number | null;
}
