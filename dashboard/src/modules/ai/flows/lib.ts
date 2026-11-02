/**
 * The Flows builder's logic, free of Vue and the network so it is tested on its own: which control
 * a setting gets, the variables a step may use and how a chip lands at the cursor, the step list
 * edits and the PATCH they become, `when` conditions, a 400 mapped back onto its fields, whether
 * the switch may move, the test-run polling and the runs pages, and the plain words on each card.
 */
import type {
  Flow,
  FlowCatalog,
  FlowConfig,
  FlowField,
  FlowModel,
  FlowPatch,
  FlowProblem,
  FlowRun,
  FlowStep,
  FlowTrigger,
  FlowValue,
  RunStatus,
  StepDef,
  StepResult,
  StepRunStatus,
  StepWhen,
  TriggerDef,
} from "./types";

export type Tone = "neutral" | "primary" | "success" | "warning" | "danger" | "info";
export type Option = { value: string; label: string };

// ─── Settings: fields → controls ────────────────────────────────────────────

export type FlowControl =
  | { kind: "switch" }
  | { kind: "stepper"; min: number; max: number; unit: string }
  | { kind: "time" }
  | { kind: "segmented"; options: Option[] }
  | { kind: "select"; options: Option[] }
  | { kind: "text"; maxLength: number | null }
  | { kind: "template"; maxLength: number | null }
  | { kind: "person" }
  | { kind: "branches" }
  | { kind: "weekdays" }
  | { kind: "model"; options: Option[] };

/**
 * Which control a setting gets: a few short choices side by side, more in a select; the model
 * select starts with the company's own choice ("" = "Company default · Claude Haiku 5.5").
 */
export function flowControl(field: FlowField, models: readonly FlowModel[] = [], defaultLabel = ""): FlowControl {
  switch (field.type) {
    case "bool":
      return { kind: "switch" };
    case "int":
      return { kind: "stepper", min: field.min ?? 0, max: field.max ?? 9999, unit: field.unit ?? "" };
    case "time":
      return { kind: "time" };
    case "choice": {
      const options = field.options ?? [];
      const short = options.length <= 3 && options.every((option) => option.label.length <= 18);
      return short ? { kind: "segmented", options } : { kind: "select", options };
    }
    case "text":
      return { kind: "text", maxLength: field.max_length ?? null };
    case "template":
      return { kind: "template", maxLength: field.max_length ?? null };
    case "person":
      return { kind: "person" };
    case "branches":
      return { kind: "branches" };
    case "weekdays":
      return { kind: "weekdays" };
    case "model":
      return { kind: "model", options: [{ value: "", label: defaultLabel || "—" }, ...models.map((model) => ({ value: model.id, label: model.name }))] };
  }
}

function clone<T>(value: T): T {
  return Array.isArray(value) ? ([...value] as T) : value;
}

/** A setting's value as shown: the saved one, else the field's default. */
export function valueOf(config: FlowConfig | undefined, field: FlowField): FlowValue {
  const value = config?.[field.key];
  return value === undefined ? clone(field.default ?? null) : value;
}

/** A new trigger's or step's settings: every field at its default. */
export function defaultConfig(fields: readonly FlowField[]): FlowConfig {
  return Object.fromEntries(fields.map((field) => [field.key, clone(field.default ?? null)]));
}

const sortedUnique = (values: readonly number[]) => [...new Set(values)].sort((a, b) => a - b);

/** A value as the field allows it (ints in range, "HH:MM", a listed choice, ids as numbers). */
export function coerceFlowValue(field: FlowField, value: unknown): FlowValue {
  switch (field.type) {
    case "bool":
      return value === true || value === "true";
    case "int": {
      const number = Math.round(Number(value));
      const min = field.min ?? Number.NEGATIVE_INFINITY;
      const max = field.max ?? Number.POSITIVE_INFINITY;
      if (!Number.isFinite(number)) return Number.isFinite(min) ? min : 0;
      return Math.min(max, Math.max(min, number));
    }
    case "time": {
      const match = /^(\d{1,2}):(\d{2})/.exec(String(value ?? ""));
      if (!match) return null;
      const pad = (n: number) => String(n).padStart(2, "0");
      return `${pad(Math.min(23, Number(match[1])))}:${pad(Math.min(59, Number(match[2])))}`;
    }
    case "choice": {
      const options = field.options ?? [];
      return options.some((option) => option.value === value) ? String(value) : (options[0]?.value ?? null);
    }
    case "text":
    case "template": {
      const text = typeof value === "string" ? value : value === null || value === undefined ? "" : String(value);
      return field.max_length ? text.slice(0, field.max_length) : text;
    }
    case "person": {
      const id = Number(value);
      return value === null || value === undefined || value === "" || !Number.isFinite(id) || id <= 0 ? null : id;
    }
    case "branches":
      return Array.isArray(value) ? sortedUnique(value.map(Number).filter((id) => Number.isFinite(id) && id > 0)) : [];
    case "weekdays":
      return Array.isArray(value) ? sortedUnique(value.map(Number).filter((day) => Number.isInteger(day) && day >= 1 && day <= 7)) : [];
    case "model":
      return typeof value === "string" ? value : "";
  }
}

/** The weekday picker counts Monday as 0 (Python's weekday()); flows use ISO 1–7. */
export const isoToPicker = (days: readonly number[]) => days.map((day) => day - 1);
export const pickerToIso = (days: readonly number[]) => sortedUnique(days.map((day) => day + 1));

// ─── Variables: what a template may use, and a chip at the cursor ───────────

export interface VariableChip {
  /** What lands in the text: "{task.title}", "{s1.text}". */
  token: string;
  label: string;
  example: string;
}

export interface VariableGroup {
  /** "trigger" or the step id. */
  id: string;
  /** The trigger's or the step's position, for the group's title ("Step 1"). 0 = the trigger. */
  position: number;
  name: string;
  variables: VariableChip[];
}

export function stepDef(catalog: FlowCatalog | null | undefined, type: string): StepDef | null {
  return catalog?.steps.find((step) => step.key === type) ?? null;
}

export function triggerDef(catalog: FlowCatalog | null | undefined, type: string): TriggerDef | null {
  return catalog?.triggers.find((trigger) => trigger.key === type) ?? null;
}

/** The variables a step at `index` may use: the trigger's, then each earlier step's outputs. */
export function variableGroups(catalog: FlowCatalog | null | undefined, trigger: FlowTrigger, steps: readonly FlowStep[], index: number): VariableGroup[] {
  const groups: VariableGroup[] = [];
  const def = triggerDef(catalog, trigger.type);
  if (def?.variables.length) {
    groups.push({ id: "trigger", position: 0, name: def.name, variables: def.variables.map((variable) => ({ token: `{${variable.key}}`, label: variable.label, example: variable.example })) });
  }
  steps.slice(0, Math.max(0, index)).forEach((step, position) => {
    const sdef = stepDef(catalog, step.type);
    if (!sdef?.outputs.length) return;
    groups.push({ id: step.id, position: position + 1, name: sdef.name, variables: sdef.outputs.map((output) => ({ token: `{${step.id}.${output.key}}`, label: output.label, example: "" })) });
  });
  return groups;
}

/**
 * The text with `token` put where the cursor is (replacing a selection), a space added where it
 * would touch a word, and the cursor after it; null when it would pass the field's length.
 */
export function insertToken(text: string, start: number, end: number, token: string, maxLength?: number | null): { text: string; cursor: number } | null {
  const from = Math.max(0, Math.min(start, text.length));
  const to = Math.max(from, Math.min(end, text.length));
  const before = text.slice(0, from);
  const after = text.slice(to);
  const lead = /[\p{L}\p{N}}]$/u.test(before) ? " " : "";
  const trail = /^[\p{L}\p{N}{]/u.test(after) ? " " : "";
  const head = `${before}${lead}${token}${trail}`;
  const next = head + after;
  if (maxLength && next.length > maxLength) return null;
  return { text: next, cursor: head.length };
}

export type TemplatePart = { kind: "text"; text: string } | { kind: "var"; key: string; label: string | null };

const TOKEN = /\{([A-Za-z_]\w*(?:\.\w+)*)\}/g;

/** A template as text and variables, each variable with its label when known (unknown ones read as ""). */
export function templateParts(text: string, labels: ReadonlyMap<string, string>): TemplatePart[] {
  const parts: TemplatePart[] = [];
  let last = 0;
  for (const match of text.matchAll(TOKEN)) {
    const at = match.index ?? 0;
    if (at > last) parts.push({ kind: "text", text: text.slice(last, at) });
    parts.push({ kind: "var", key: match[1]!, label: labels.get(match[1]!) ?? null });
    last = at + match[0].length;
  }
  if (last < text.length) parts.push({ kind: "text", text: text.slice(last) });
  return parts;
}

/** Variable keys → labels for the step at `index` ("task.title" → "Task title", "s1.text" → "Step 1 · Text"). */
export function variableLabels(groups: readonly VariableGroup[], stepWord: (position: number) => string): Map<string, string> {
  const labels = new Map<string, string>();
  for (const group of groups) {
    for (const variable of group.variables) {
      const key = variable.token.slice(1, -1);
      labels.set(key, group.id === "trigger" ? variable.label : `${stepWord(group.position)} · ${variable.label}`);
    }
  }
  return labels;
}

/** The step ids a template's variables name ({s1.text} → "s1"). */
export function referencedSteps(text: string): string[] {
  const ids = new Set<string>();
  for (const match of text.matchAll(TOKEN)) {
    const head = /^(s\d+)\./.exec(match[1]!);
    if (head) ids.add(head[1]!);
  }
  return [...ids];
}

/** A step's templates that name a step not before it (moved below, or removed): its result reads as "". */
export function laterReferences(steps: readonly FlowStep[], index: number, def: StepDef | null): string[] {
  const step = steps[index];
  if (!step || !def) return [];
  const earlier = new Set(steps.slice(0, index).map((item) => item.id));
  const named = def.fields.filter((field) => field.type === "template" || field.type === "text").flatMap((field) => referencedSteps(String(step.config[field.key] ?? "")));
  return [...new Set(named)].filter((id) => !earlier.has(id));
}

// ─── The step list: edits ───────────────────────────────────────────────────

export function stepFits(def: StepDef, triggerType: string): boolean {
  return def.triggers === null || def.triggers.includes(triggerType);
}

/** The steps the picker offers for this trigger, AI first. */
export function fittingSteps(catalog: FlowCatalog | null | undefined, triggerType: string): { ai: StepDef[]; actions: StepDef[] } {
  const fit = (catalog?.steps ?? []).filter((def) => stepFits(def, triggerType));
  return { ai: fit.filter((def) => def.kind === "ai"), actions: fit.filter((def) => def.kind !== "ai") };
}

/** "s1", "s2"…: one more than the highest, so a removed step's id is never reused for another. */
export function nextStepId(steps: readonly FlowStep[]): string {
  const max = steps.reduce((top, step) => {
    const match = /^s(\d+)$/.exec(step.id);
    return match ? Math.max(top, Number(match[1])) : top;
  }, 0);
  return `s${max + 1}`;
}

export function makeStep(def: StepDef, steps: readonly FlowStep[]): FlowStep {
  return { id: nextStepId(steps), type: def.key, config: defaultConfig(def.fields), when: null };
}

export function insertStep(steps: readonly FlowStep[], step: FlowStep, at: number): FlowStep[] {
  const next = [...steps];
  next.splice(Math.max(0, Math.min(at, next.length)), 0, step);
  return next;
}

/** `when` conditions that no longer point at an earlier step are dropped (their ids are returned). */
export function dropBrokenWhens(steps: readonly FlowStep[]): { steps: FlowStep[]; cleared: string[] } {
  const cleared: string[] = [];
  const next = steps.map((step, index) => {
    if (!step.when) return step;
    const earlier = steps.slice(0, index).some((item) => item.id === step.when!.step);
    if (earlier) return step;
    cleared.push(step.id);
    return { ...step, when: null };
  });
  return { steps: next, cleared };
}

export function removeStep(steps: readonly FlowStep[], id: string): { steps: FlowStep[]; cleared: string[] } {
  return dropBrokenWhens(steps.filter((step) => step.id !== id));
}

export function moveStep(steps: readonly FlowStep[], id: string, delta: -1 | 1): { steps: FlowStep[]; cleared: string[] } {
  const from = steps.findIndex((step) => step.id === id);
  const to = from + delta;
  if (from < 0 || to < 0 || to >= steps.length) return { steps: [...steps], cleared: [] };
  const next = [...steps];
  [next[from], next[to]] = [next[to]!, next[from]!];
  return dropBrokenWhens(next);
}

/** The list after a drag: `id` now sits at `to`. */
export function placeStep(steps: readonly FlowStep[], id: string, to: number): { steps: FlowStep[]; cleared: string[] } {
  const from = steps.findIndex((step) => step.id === id);
  if (from < 0) return { steps: [...steps], cleared: [] };
  const next = [...steps];
  const [moved] = next.splice(from, 1);
  next.splice(Math.max(0, Math.min(to, next.length)), 0, moved!);
  return dropBrokenWhens(next);
}

export function setStepConfig(steps: readonly FlowStep[], id: string, key: string, value: FlowValue): FlowStep[] {
  return steps.map((step) => (step.id === id ? { ...step, config: { ...step.config, [key]: value } } : step));
}

export function setStepWhen(steps: readonly FlowStep[], id: string, when: StepWhen | null): FlowStep[] {
  return steps.map((step) => (step.id === id ? { ...step, when } : step));
}

// ─── `when`: run a step only if… ────────────────────────────────────────────

export interface WhenOutput {
  key: string;
  label: string;
  /** The values it can take, when they are known (a decision's options, a photo verdict). */
  values: string[] | null;
}

export interface WhenSource {
  step: FlowStep;
  /** 1-based, as the chain numbers it. */
  position: number;
  def: StepDef;
  outputs: WhenOutput[];
}

export const VERDICTS = ["looks_right", "check", "unclear"] as const;

/** "yes, no" → ["yes", "no"] (a decision's options, 2–4 short labels). */
export function choiceOptions(text: FlowValue | undefined): string[] {
  if (typeof text !== "string") return [];
  return [...new Set(text.split(/[,;\n]/).map((part) => part.trim()).filter(Boolean))];
}

/** The earlier steps a `when` may look at, with their outputs and known values. */
export function whenSources(catalog: FlowCatalog | null | undefined, steps: readonly FlowStep[], index: number): WhenSource[] {
  const sources: WhenSource[] = [];
  steps.slice(0, Math.max(0, index)).forEach((step, at) => {
    const def = stepDef(catalog, step.type);
    if (!def?.outputs.length) return;
    const outputs = def.outputs.map((output) => {
      let values: string[] | null = null;
      if (step.type === "ai_decide" && output.key === "choice") values = choiceOptions(step.config.options ?? def.fields.find((field) => field.key === "options")?.default);
      if (step.type === "ai_check_photo" && output.key === "verdict") values = [...VERDICTS];
      return { key: output.key, label: output.label, values: values?.length ? values : null };
    });
    sources.push({ step, position: at + 1, def, outputs });
  });
  return sources;
}

/** A first condition for the editor: the latest step with known values, its first output and value. */
export function suggestWhen(sources: readonly WhenSource[]): StepWhen | null {
  const pick = [...sources].reverse().find((source) => source.outputs.some((output) => output.values)) ?? sources.at(-1);
  if (!pick) return null;
  const output = pick.outputs.find((item) => item.values) ?? pick.outputs[0]!;
  const value = output.values?.[0] ?? "";
  // A photo check is worth acting on when it doesn't look right.
  const op = pick.step.type === "ai_check_photo" && output.key === "verdict" ? "ne" : "eq";
  return { step: pick.step.id, output: output.key, op, value };
}

// ─── The draft and the PATCH it becomes ─────────────────────────────────────

export interface FlowDraft {
  name: string;
  description: string;
  trigger: FlowTrigger;
  steps: FlowStep[];
}

/** JSON with sorted keys, so two configs with the same values compare equal. */
export function stable(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stable).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.keys(value)
      .sort()
      .filter((key) => (value as Record<string, unknown>)[key] !== undefined)
      .map((key) => `${JSON.stringify(key)}:${stable((value as Record<string, unknown>)[key])}`)
      .join(",")}}`;
  }
  return JSON.stringify(value ?? null);
}

export function draftOf(flow: Pick<Flow, "name" | "description" | "trigger" | "steps">): FlowDraft {
  return {
    name: flow.name,
    description: flow.description ?? "",
    trigger: { type: flow.trigger.type, config: { ...flow.trigger.config } },
    steps: flow.steps.map((step) => ({ id: step.id, type: step.type, config: { ...step.config }, when: step.when ? { ...step.when } : null })),
  };
}

/** What changed since the server's flow: the changed keys only, the steps always whole. */
export function flowPatch(draft: FlowDraft, flow: Pick<Flow, "name" | "description" | "trigger" | "steps">): FlowPatch {
  const patch: FlowPatch = {};
  if (draft.name.trim() !== flow.name) patch.name = draft.name.trim();
  if (draft.description.trim() !== (flow.description ?? "")) patch.description = draft.description.trim();
  if (stable(draft.trigger) !== stable(flow.trigger)) patch.trigger = draft.trigger;
  if (stable(draft.steps.map(stepBody)) !== stable(flow.steps.map(stepBody))) patch.steps = draft.steps.map(stepBody);
  return patch;
}

function stepBody(step: FlowStep): FlowStep {
  return { id: step.id, type: step.type, config: step.config, when: step.when ?? null };
}

export function isDirty(draft: FlowDraft | null, flow: Pick<Flow, "name" | "description" | "trigger" | "steps"> | null | undefined): boolean {
  return !!draft && !!flow && Object.keys(flowPatch(draft, flow)).length > 0;
}

/** A new trigger keeps nothing of the old one; steps that don't fit it are named for the person. */
export function changeTrigger(draft: FlowDraft, def: TriggerDef, catalog: FlowCatalog | null | undefined): { draft: FlowDraft; misfits: string[] } {
  const next = { ...draft, trigger: { type: def.key, config: defaultConfig(def.fields) } };
  const misfits = draft.steps.filter((step) => {
    const sdef = stepDef(catalog, step.type);
    return sdef ? !stepFits(sdef, def.key) : false;
  });
  return { draft: next, misfits: misfits.map((step) => step.id) };
}

// ─── A 400 mapped onto its fields ───────────────────────────────────────────

export interface FlowErrors {
  name: string | null;
  description: string | null;
  enabled: string | null;
  /** Field key → message; "" for the trigger as a whole. */
  trigger: Record<string, string>;
  /** Step id → field key → message; "" for the step as a whole. */
  steps: Record<string, Record<string, string>>;
  /** About the whole flow or the step list ("Up to 6 steps"). */
  general: string | null;
}

function firstMessage(value: unknown): string | null {
  if (typeof value === "string") return value;
  if (Array.isArray(value)) {
    for (const item of value) {
      if (typeof item === "string") return item;
    }
  }
  return null;
}

/** `{"hours": ["…"]}` or `{"config": {"hours": […]}}` or `["…"]` → field key → message. */
function fieldMessages(value: unknown): Record<string, string> {
  const out: Record<string, string> = {};
  const whole = firstMessage(value);
  if (whole) {
    out[""] = whole;
    return out;
  }
  if (!value || typeof value !== "object" || Array.isArray(value)) return out;
  for (const [key, inner] of Object.entries(value as Record<string, unknown>)) {
    if (key === "config" && inner && typeof inner === "object" && !Array.isArray(inner)) {
      Object.assign(out, fieldMessages(inner));
      continue;
    }
    const message = firstMessage(inner);
    if (message) out[key === "non_field_errors" ? "" : key] = message;
  }
  return out;
}

/**
 * The 400 of a save (`{"trigger": {"hours": [msg]}, "steps": {"1": {"text": [msg]}}, "name": [msg]}`)
 * by field: step errors come by position in the list that was sent and are given back by step id.
 * Null when the body names nothing this page shows.
 */
export function flowErrors(body: unknown, sent: readonly FlowStep[]): FlowErrors | null {
  if (!body || typeof body !== "object" || Array.isArray(body)) return null;
  const record = body as Record<string, unknown>;
  const errors: FlowErrors = { name: firstMessage(record.name), description: firstMessage(record.description), enabled: firstMessage(record.enabled), trigger: fieldMessages(record.trigger), steps: {}, general: firstMessage(record.non_field_errors) ?? null };
  const steps = record.steps;
  const add = (index: number, value: unknown) => {
    const step = sent[index];
    const messages = fieldMessages(value);
    if (!Object.keys(messages).length) return;
    if (step) errors.steps[step.id] = messages;
    else errors.general ??= Object.values(messages)[0] ?? null;
  };
  if (typeof steps === "string" || (Array.isArray(steps) && steps.every((item) => typeof item === "string"))) {
    errors.general = firstMessage(steps) ?? errors.general;
  } else if (Array.isArray(steps)) {
    steps.forEach((value, index) => add(index, value));
  } else if (steps && typeof steps === "object") {
    for (const [key, value] of Object.entries(steps as Record<string, unknown>)) {
      if (/^\d+$/.test(key)) add(Number(key), value);
      else errors.general ??= firstMessage(value);
    }
  }
  const found = errors.name || errors.description || errors.enabled || errors.general || Object.keys(errors.trigger).length || Object.keys(errors.steps).length;
  return found ? errors : null;
}

export function emptyErrors(): FlowErrors {
  return { name: null, description: null, enabled: null, trigger: {}, steps: {}, general: null };
}

// ─── The switch ─────────────────────────────────────────────────────────────

/** Problems that keep a flow from being turned on (the server refuses with `{"enabled": [msg]}`). */
export const BLOCKING_PROBLEMS: readonly string[] = ["module_off", "owner_gone", "person_gone"];

export function blockingProblem(problems: readonly FlowProblem[]): FlowProblem | null {
  return problems.find((problem) => BLOCKING_PROBLEMS.includes(problem.code)) ?? null;
}

export interface SwitchState {
  on: boolean;
  disabled: boolean;
  /** Why it can't move: "ai_off", "read_only" or a blocking problem's text. */
  reason: "ai_off" | "read_only" | null;
  problem: FlowProblem | null;
}

/** On only while AI is on; it moves for ai.configure people, and not to "on" over a blocking problem. */
export function switchState(flow: Pick<Flow, "enabled" | "problems">, ctx: { canEdit: boolean; aiOn: boolean }): SwitchState {
  const problem = flow.enabled ? null : blockingProblem(flow.problems);
  if (!ctx.canEdit) return { on: flow.enabled && ctx.aiOn, disabled: true, reason: "read_only", problem };
  if (!ctx.aiOn) return { on: false, disabled: true, reason: "ai_off", problem };
  return { on: flow.enabled, disabled: !!problem, reason: null, problem };
}

// ─── Runs: polling, pages, the staged reveal ────────────────────────────────

export const RUN_POLL_MS = 1000;
/** How long a test run is watched before "this is taking longer" and Try again. */
export const RUN_GIVE_UP_MS = 60_000;

export function runIsLive(status: RunStatus | undefined | null): boolean {
  return status === "queued" || status === "running";
}

/** Poll again, stop (the run finished), or give up (60 s without an end). */
export function runPollDecision(status: RunStatus | undefined | null, elapsedMs: number, limitMs = RUN_GIVE_UP_MS): "poll" | "stop" | "give_up" {
  if (status && !runIsLive(status)) return "stop";
  return elapsedMs >= limitMs ? "give_up" : "poll";
}

/** One list, newest first, each run once (a newer copy replaces the older one). */
export function mergeRuns(current: readonly FlowRun[], incoming: readonly FlowRun[]): FlowRun[] {
  const byId = new Map<number, FlowRun>();
  for (const run of current) byId.set(run.id, run);
  for (const run of incoming) byId.set(run.id, run);
  return [...byId.values()].sort((a, b) => b.id - a.id);
}

/** How many of a run's steps have an answer, in order (the first unanswered one is the one working). */
export function answeredSteps(run: Pick<FlowRun, "status" | "steps"> | null | undefined): number {
  if (!run) return 0;
  if (!runIsLive(run.status)) return run.steps.length;
  const first = run.steps.findIndex((step) => step.status === "pending");
  return first < 0 ? run.steps.length : first;
}

export const RUN_TONE: Record<RunStatus, Tone> = { queued: "info", running: "info", done: "success", skipped: "neutral", failed: "danger" };
export const STEP_TONE: Record<StepRunStatus, Tone> = { done: "success", preview: "primary", skipped: "neutral", failed: "danger", pending: "info" };

/** "0.0011" → "$0.0011", "0.5" → "$0.50"; nothing for a free run. */
export function formatCost(cost: string | number | null | undefined): string | null {
  const value = Number(cost);
  if (!Number.isFinite(value) || value <= 0) return null;
  if (value >= 1) return `$${value.toFixed(2)}`;
  const fixed = value.toFixed(4).replace(/0+$/, "");
  const [, decimals = ""] = fixed.split(".");
  return `$${decimals.length < 2 ? value.toFixed(2) : fixed}`;
}

/** The message a send_message step would send (or sent), read liberally from its output. */
export function messageOf(result: Pick<StepResult, "output" | "type">): { to: string[]; text: string; button: boolean } | null {
  const output = result.output ?? {};
  const text = [output.text, output.message, output.preview, output.body].find((value): value is string => typeof value === "string" && value.trim() !== "");
  if (text === undefined) return null;
  const raw = output.to ?? output.recipients ?? output.sent_to ?? output.recipient ?? [];
  const list = Array.isArray(raw) ? raw : [raw];
  const to = list
    .map((item) => (typeof item === "string" ? item : item && typeof item === "object" ? String((item as { name?: unknown }).name ?? (item as { label?: unknown }).label ?? "") : ""))
    .filter(Boolean);
  const button = output.open_button === true || output.button === true || typeof output.button === "string";
  return { to, text, button };
}

// ─── Plain words for the cards ──────────────────────────────────────────────

export type Translate = (key: string, named?: Record<string, unknown>, plural?: number) => string;

export interface WordsContext {
  t: Translate;
  /** The trigger's subject ("task", "member"…), for who "the person it is about" is. */
  subject: string;
  person: (id: number | null) => string | null;
  branches: (ids: number[]) => string | null;
  model: (id: string) => string | null;
  money: (amount: number) => string;
  weekdays: (iso: number[]) => string;
}

const asNumber = (value: FlowValue | undefined, fallback: number) => (typeof value === "number" && Number.isFinite(value) ? value : fallback);
const asString = (value: FlowValue | undefined, fallback = "") => (typeof value === "string" ? value : fallback);
const asIds = (value: FlowValue | undefined) => (Array.isArray(value) ? value.map(Number) : []);

function configOf(config: FlowConfig, fields: readonly FlowField[]): FlowConfig {
  const out: FlowConfig = {};
  for (const field of fields) out[field.key] = valueOf(config, field);
  for (const [key, value] of Object.entries(config)) if (!(key in out)) out[key] = value;
  return out;
}

/** A setting in a few words, for settings this file has no sentence for. */
function genericFact(field: FlowField, value: FlowValue, ctx: WordsContext): string | null {
  switch (field.type) {
    case "bool":
      return value === true ? field.label : null;
    case "int":
      return typeof value === "number" ? `${field.label}: ${value}${field.unit ? ` ${field.unit}` : ""}` : null;
    case "time":
      return typeof value === "string" && value ? `${field.label}: ${value}` : null;
    case "choice":
      return field.options?.find((option) => option.value === value)?.label ?? null;
    case "person":
      return ctx.person(typeof value === "number" ? value : null);
    case "branches":
      return ctx.branches(asIds(value));
    case "weekdays":
      return ctx.weekdays(asIds(value));
    case "model":
      return typeof value === "string" && value ? ctx.model(value) : null;
    default:
      return null;
  }
}

function branchFact(value: FlowValue | undefined, ctx: WordsContext): string {
  const ids = asIds(value);
  return (ids.length ? ctx.branches(ids) : null) ?? ctx.t("ai.flow.sum.allBranches");
}

/** Who "subject_person" is for this trigger ("the assignee", "the new employee"…). */
export function subjectWho(subject: string, t: Translate): string {
  const known = ["task", "member", "time_off", "draft", "shift"];
  return t(`ai.flow.who.subject.${known.includes(subject) ? subject : "other"}`);
}

function whoWords(to: string, personId: FlowValue | undefined, ctx: WordsContext): string {
  if (to === "subject_person") return subjectWho(ctx.subject, ctx.t);
  if (to === "person") return ctx.person(typeof personId === "number" ? personId : null) ?? ctx.t("ai.flow.who.nobody");
  if (["giver", "branch_head", "owners"].includes(to)) return ctx.t(`ai.flow.who.${to}`);
  return to;
}

/** The trigger's settings in one line: "2 hours or more · all branches". */
export function triggerLine(trigger: FlowTrigger, def: TriggerDef | null, ctx: WordsContext): string {
  const { t } = ctx;
  if (!def) return "";
  const config = configOf(trigger.config, def.fields);
  const facts: string[] = [];
  const handled = new Set<string>();
  const take = (...keys: string[]) => keys.forEach((key) => handled.add(key));
  switch (def.key) {
    case "task_overdue": {
      const hours = asNumber(config.hours, 2);
      facts.push(t("ai.flow.sum.lateBy", { n: hours }, hours));
      if (config.urgent_only === true) facts.push(t("ai.flow.sum.urgentOnly"));
      facts.push(branchFact(config.branch_ids, ctx));
      take("hours", "urgent_only", "branch_ids");
      break;
    }
    case "task_completed":
      facts.push(t(config.only_with_photo === true ? "ai.flow.sum.withPhoto" : "ai.flow.sum.anyFinished"));
      facts.push(branchFact(config.branch_ids, ctx));
      take("only_with_photo", "branch_ids");
      break;
    case "schedule":
      facts.push(t("ai.flow.sum.at", { time: asString(config.at, "20:00") }));
      facts.push(ctx.weekdays(asIds(config.weekdays)));
      take("at", "weekdays");
      break;
    case "member_joined":
      facts.push(branchFact(config.branch_ids, ctx));
      take("branch_ids");
      break;
    case "shift_closed": {
      const least = asNumber(config.min_mismatch, 0);
      facts.push(least > 0 ? t("ai.flow.sum.mismatchFrom", { amount: ctx.money(least) }) : t("ai.flow.sum.everyShift"));
      take("min_mismatch");
      break;
    }
  }
  for (const field of def.fields) {
    if (handled.has(field.key)) continue;
    const fact = genericFact(field, config[field.key] ?? null, ctx);
    if (fact) facts.push(fact);
  }
  return facts.filter(Boolean).join(" · ") || def.description;
}

/** A step's settings in one line: "A friendly message · in their language · up to 60 words". */
export function stepLine(step: FlowStep, def: StepDef | null, ctx: WordsContext): string {
  const { t } = ctx;
  if (!def) return t("ai.flow.unknownStep");
  const config = configOf(step.config, def.fields);
  const facts: string[] = [];
  const handled = new Set<string>(def.fields.filter((field) => field.type === "template" || field.type === "text").map((field) => field.key));
  const take = (...keys: string[]) => keys.forEach((key) => handled.add(key));
  switch (def.key) {
    case "ai_write": {
      const tone = asString(config.tone, "friendly");
      const language = asString(config.language, "recipient");
      const words = asNumber(config.max_words, 60);
      facts.push(["friendly", "neutral", "firm"].includes(tone) ? t(`ai.flow.sum.tone.${tone}`) : t("ai.flow.sum.tone.neutral"));
      facts.push(["recipient", "uz", "ru", "en"].includes(language) ? t(`ai.flow.sum.lang.${language}`) : language);
      facts.push(t("ai.flow.sum.words", { n: words }, words));
      take("tone", "language", "max_words");
      break;
    }
    case "ai_decide": {
      const options = choiceOptions(config.options);
      facts.push(t("ai.flow.sum.answer", { options: options.join(" / ") || "—" }));
      break;
    }
    case "ai_check_photo":
      facts.push(t("ai.flow.sum.photo"));
      break;
    case "ai_summarize": {
      const period = asString(config.period, "today");
      facts.push(t(period === "week" ? "ai.flow.sum.week" : "ai.flow.sum.today"));
      take("period");
      break;
    }
    case "send_message":
      facts.push(t("ai.flow.sum.to", { who: whoWords(asString(config.to, "subject_person"), config.person_id, ctx) }));
      if (config.open_button === true) facts.push(t("ai.flow.sum.openButton"));
      if (config.quiet_hours === true) facts.push(t("ai.flow.sum.quietHours"));
      take("to", "person_id", "open_button", "quiet_hours");
      break;
    case "create_task": {
      facts.push(t("ai.flow.sum.for", { who: whoWords(asString(config.assignee, "subject_person"), config.person_id, ctx) }));
      const hours = asNumber(config.due_in_hours, 0);
      if (hours > 0) facts.push(t("ai.flow.sum.dueIn", { n: hours }, hours));
      if (config.urgent === true) facts.push(t("ai.flow.sum.urgent"));
      if (config.photo_proof === true) facts.push(t("ai.flow.sum.photoProof"));
      take("assignee", "person_id", "due_in_hours", "urgent", "photo_proof");
      break;
    }
    case "add_comment":
      facts.push(t("ai.flow.sum.comment"));
      break;
  }
  for (const field of def.fields) {
    if (handled.has(field.key)) continue;
    const fact = genericFact(field, config[field.key] ?? null, ctx);
    if (fact) facts.push(fact);
  }
  return facts.filter(Boolean).join(" · ") || def.description;
}

/** The text a step works from (its instruction, question, message…): the card's quoted line. */
export function stepText(step: FlowStep, def: StepDef | null): string {
  if (!def) return "";
  const field = def.fields.find((item) => item.type === "template");
  const value = field ? valueOf(step.config, field) : null;
  return typeof value === "string" ? value.trim() : "";
}

/** "uses AI": a template or flow with at least one AI step. */
export function usesAi(steps: readonly Pick<FlowStep, "type">[], catalog: FlowCatalog | null | undefined): boolean {
  return steps.some((step) => stepDef(catalog, step.type)?.kind === "ai");
}

/** A step that needs Claude while Claude isn't there: it will be skipped. */
export function needsClaude(def: StepDef | null, claudeReady: boolean): boolean {
  return !!def?.needs_claude && !claudeReady;
}
