/**
 * The AI module's logic, free of Vue and the network so it is tested on its own: what the status
 * lets a person see, how a draft is edited and sent back, what a problem's one-tap fix does, how
 * the generic agent settings become form controls, and how the activity feed merges its pages.
 */
import { TZDate } from "@date-fns/tz";

import { addDays } from "@/lib/dates";

import type {
  ActivityItem,
  AgentConfigValue,
  AgentField,
  AiDraft,
  AiStatus,
  ApplyDraft,
  ClaudeState,
  DraftProblem,
  DraftStatus,
  SpeechState,
  SubjectType,
  TurnStatus,
} from "./types";

// ─── Status → what shows ────────────────────────────────────────────────────

export interface AiVisibility {
  /** The "Turn on AI" hero (owners and ai.configure people while AI is off). */
  turnOn: boolean;
  /** AI is off and this person can't switch it on: say who can. */
  offNotice: boolean;
  /** Recording a voice instruction (AI on, the voice agent on, speech ready). */
  dictate: boolean;
  /** Several tasks from typed text (AI on, the voice agent on). */
  smartAdd: boolean;
  chat: boolean;
  /** "Ask AI comes with Claude" for people who could connect it. */
  chatTeaser: boolean;
  /** "Add ANTHROPIC_API_KEY on the server": no key, and this person configures AI. */
  keyNotice: boolean;
}

export function aiVisibility(status: AiStatus | null | undefined): AiVisibility {
  if (!status) return { turnOn: false, offNotice: false, dictate: false, smartAdd: false, chat: false, chatTeaser: false, keyNotice: false };
  const on = status.enabled;
  return {
    turnOn: !on && status.can_configure,
    offNotice: !on && !status.can_configure,
    dictate: on && status.features.voice,
    smartAdd: on && status.features.smart_text,
    chat: on && status.features.chat,
    chatTeaser: !(on && status.features.chat) && status.can_configure,
    keyNotice: status.can_configure && status.claude === "not_configured",
  };
}

export type Tone = "neutral" | "primary" | "success" | "warning" | "danger" | "info";

export const CLAUDE_TONE: Record<ClaudeState, Tone> = {
  connected: "success",
  fake: "info",
  not_configured: "neutral",
  blocked: "danger",
  budget_reached: "warning",
  unavailable: "warning",
};

export const SPEECH_TONE: Record<SpeechState, Tone> = { ready: "success", fake: "info", not_configured: "neutral" };

// ─── Drafts: states and polling ─────────────────────────────────────────────

export const WORKING: readonly DraftStatus[] = ["queued", "transcribing", "thinking"];
export const DRAFT_POLL_MS = 1000;
/** How long a person waits for a draft before "this is taking too long" and Try again. */
export const DRAFT_GIVE_UP_MS = 90_000;

export function isWorking(status: DraftStatus | undefined | null): boolean {
  return !!status && WORKING.includes(status);
}

/** Poll again, stop (an answer came), or give up (90 s without one). */
export function pollDecision(status: DraftStatus | undefined | null, elapsedMs: number, limitMs = DRAFT_GIVE_UP_MS): "poll" | "stop" | "give_up" {
  if (status && !isWorking(status)) return "stop";
  return elapsedMs >= limitMs ? "give_up" : "poll";
}

/** "Eshitayapman…" while the voice is turned into words, "Tushunyapman…" while tasks are read from them. */
export function workingPhase(status: DraftStatus | undefined | null, hasAudio: boolean): "upload" | "listening" | "thinking" {
  if (!status) return "upload";
  if (status === "thinking") return "thinking";
  return hasAudio ? "listening" : "thinking";
}

export const DRAFT_TONE: Record<DraftStatus, Tone> = {
  queued: "info",
  transcribing: "info",
  thinking: "info",
  ready: "warning",
  failed: "danger",
  applied: "success",
  discarded: "neutral",
  expired: "neutral",
};

// ─── Drafts: editing ────────────────────────────────────────────────────────

/** One draft as the review edits it. `assigneeId` null = for the author ("Me"). */
export interface EditableDraft {
  key: string;
  title: string;
  description: string;
  assigneeId: number | null;
  assigneeName: string | null;
  assigneePosition: string | null;
  /** The person picked by hand: the server's doubts about who was meant no longer apply. */
  assigneeTouched: boolean;
  /** Who was heard but not matched ("Alisher"). */
  guess: string;
  dueAt: string | null;
  /** The server's words for `dueAt` ("Ertaga, 10:00") until the time is changed here. */
  dueText: string;
  dueTouched: boolean;
  priority: "normal" | "urgent";
  checklist: string[];
  proof: "none" | "photo";
  /** What the server found wrong with the draft as heard. */
  problems: DraftProblem[];
  removed: boolean;
}

export function toEditable(draft: Pick<AiDraft, "id" | "drafts">): EditableDraft[] {
  return draft.drafts.map((item, index) => ({
    key: `${draft.id}:${index}`,
    title: item.title,
    description: item.description ?? "",
    assigneeId: item.assignee?.id ?? null,
    assigneeName: item.assignee?.name ?? null,
    assigneePosition: item.assignee?.position ?? null,
    assigneeTouched: false,
    guess: item.assignee_guess ?? "",
    dueAt: item.due_at,
    dueText: item.due_text ?? "",
    dueTouched: false,
    priority: item.priority === "urgent" ? "urgent" : "normal",
    checklist: [...(item.checklist ?? [])],
    proof: item.proof === "photo" ? "photo" : "none",
    problems: [...(item.problems ?? [])],
    removed: false,
  }));
}

/** The body of `apply/`: the drafts as reviewed, removed ones left out, empty steps dropped. */
export function toApplyPayload(edits: readonly EditableDraft[]): { drafts: ApplyDraft[] } {
  return {
    drafts: edits
      .filter((edit) => !edit.removed)
      .map((edit) => ({
        title: edit.title.trim(),
        description: edit.description.trim(),
        assignee_id: edit.assigneeId,
        due_at: edit.dueAt,
        priority: edit.priority,
        checklist: edit.checklist.map((step) => step.trim()).filter(Boolean),
        proof: edit.proof,
      })),
  };
}

const ASSIGNEE_PROBLEMS: readonly DraftProblem[] = ["no_assignee_match", "ambiguous_assignee", "not_allowed"];
const DUE_PROBLEMS: readonly DraftProblem[] = ["no_due", "past_due"];
/** What stops "Create": a task would go to the wrong person or carry a time already gone. */
export const BLOCKING: readonly DraftProblem[] = ["no_assignee_match", "ambiguous_assignee", "not_allowed", "past_due"];

/**
 * The problems a draft has now: the server's, minus the ones an edit answered, plus "the time has
 * passed" for a deadline that went by while the person was reading.
 */
export function liveProblems(edit: EditableDraft, now: number): DraftProblem[] {
  let problems = edit.problems.filter((problem) => !(edit.assigneeTouched && ASSIGNEE_PROBLEMS.includes(problem)));
  if (edit.dueTouched) problems = problems.filter((problem) => !DUE_PROBLEMS.includes(problem));
  const passed = edit.dueAt !== null && Date.parse(edit.dueAt) <= now;
  if (passed && !problems.includes("past_due")) problems = [...problems, "past_due"];
  if (!passed && edit.dueTouched) problems = problems.filter((problem) => problem !== "past_due");
  if (edit.dueAt !== null) problems = problems.filter((problem) => problem !== "no_due");
  return problems;
}

export function blockingProblems(edit: EditableDraft, now: number): DraftProblem[] {
  return liveProblems(edit, now).filter((problem) => BLOCKING.includes(problem));
}

/** Why "Create" can't be pressed yet: nothing left, a draft without a title, or problems to fix. */
export function applyBlockers(edits: readonly EditableDraft[], now: number): { count: number; untitled: number; problems: number } {
  const kept = edits.filter((edit) => !edit.removed);
  return {
    count: kept.length,
    untitled: kept.filter((edit) => !edit.title.trim()).length,
    problems: kept.reduce((sum, edit) => sum + blockingProblems(edit, now).length, 0),
  };
}

export type Fix = { kind: "pick" } | { kind: "me" } | { kind: "due"; day: string; time: string } | { kind: "keepNoDue" };

/** A company-local day and wall-clock time ("2026-11-03", "10:00") as an ISO instant. */
export function zonedIso(day: string, time: string, timeZone: string): string {
  const [year, month, date] = day.split("-").map(Number) as [number, number, number];
  const [hour, minute] = time.split(":").map(Number) as [number, number];
  return new TZDate(year, month - 1, date, hour, minute, timeZone).toISOString();
}

/** The company-local day and time ("2026-11-03", "10:00") of an ISO instant. */
export function zonedParts(iso: string, timeZone: string): { day: string; time: string } {
  const zoned = new TZDate(new Date(iso).getTime(), timeZone);
  const pad = (n: number) => String(n).padStart(2, "0");
  return { day: `${zoned.getFullYear()}-${pad(zoned.getMonth() + 1)}-${pad(zoned.getDate())}`, time: `${pad(zoned.getHours())}:${pad(zoned.getMinutes())}` };
}

/** The one-tap answers to a problem, most likely first. */
export function problemFixes(problem: DraftProblem, edit: EditableDraft, ctx: { timeZone: string; now: number }): Fix[] {
  const today = zonedParts(new Date(ctx.now).toISOString(), ctx.timeZone);
  const tomorrow = addDays(today.day, 1);
  switch (problem) {
    case "no_assignee_match":
    case "ambiguous_assignee":
    case "not_allowed":
      return [{ kind: "pick" }, { kind: "me" }];
    case "no_due": {
      const fixes: Fix[] = [];
      // "Today, 18:00" only while there is still a working day left before it.
      if (today.time < "17:00") fixes.push({ kind: "due", day: today.day, time: "18:00" });
      fixes.push({ kind: "due", day: tomorrow, time: "09:00" });
      return fixes;
    }
    case "past_due": {
      const was = edit.dueAt ? zonedParts(edit.dueAt, ctx.timeZone).time : "09:00";
      const fixes: Fix[] = [{ kind: "due", day: tomorrow, time: was }];
      if (was !== "09:00") fixes.push({ kind: "due", day: tomorrow, time: "09:00" });
      return fixes;
    }
  }
}

/** The draft after a fix (or a hand edit of the same kind). */
export function applyFix(edit: EditableDraft, fix: Fix, ctx: { timeZone: string }): EditableDraft {
  switch (fix.kind) {
    case "me":
      return { ...edit, assigneeId: null, assigneeName: null, assigneePosition: null, assigneeTouched: true };
    case "due":
      return { ...edit, dueAt: zonedIso(fix.day, fix.time, ctx.timeZone), dueTouched: true };
    case "keepNoDue":
      return { ...edit, dueAt: null, dueTouched: true };
    case "pick":
      return edit;
  }
}

export function setAssignee(edit: EditableDraft, person: { id: number; name: string; position?: string | null } | null): EditableDraft {
  if (!person) return applyFix(edit, { kind: "me" }, { timeZone: "UTC" });
  return { ...edit, assigneeId: person.id, assigneeName: person.name, assigneePosition: person.position ?? null, assigneeTouched: true };
}

// ─── Agent settings: fields → controls ──────────────────────────────────────

export type FieldControl =
  | { kind: "switch" }
  | { kind: "stepper"; min: number; max: number; unit: string }
  | { kind: "time" }
  | { kind: "segmented"; options: { value: string; label: string }[] }
  | { kind: "select"; options: { value: string; label: string }[] };

/** Which control a field gets: a few short choices sit side by side, more go in a select. */
export function fieldControl(field: AgentField): FieldControl {
  switch (field.type) {
    case "bool":
      return { kind: "switch" };
    case "int":
      return { kind: "stepper", min: field.min ?? 0, max: field.max ?? 9999, unit: field.unit ?? "" };
    case "time":
      return { kind: "time" };
    case "choice": {
      const options = field.options ?? [];
      const short = options.length <= 3 && options.every((option) => option.label.length <= 14);
      return short ? { kind: "segmented", options } : { kind: "select", options };
    }
  }
}

/** A value as the field allows it: ints clamped to their range, times as HH:MM, a choice from its list. */
export function coerceValue(field: AgentField, value: unknown): AgentConfigValue {
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
      const hour = Math.min(23, Number(match[1]));
      const minute = Math.min(59, Number(match[2]));
      return `${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}`;
    }
    case "choice": {
      const options = field.options ?? [];
      return options.some((option) => option.value === value) ? String(value) : (options[0]?.value ?? null);
    }
  }
}

// ─── Activity ───────────────────────────────────────────────────────────────

/** One list, newest first, each item once (a newer copy of an item replaces the older one). */
export function mergeActivity(current: readonly ActivityItem[], incoming: readonly ActivityItem[]): ActivityItem[] {
  const byId = new Map<number, ActivityItem>();
  for (const item of current) byId.set(item.id, item);
  for (const item of incoming) byId.set(item.id, item);
  return [...byId.values()].sort((a, b) => b.id - a.id);
}

/** Ids in `next` that `previous` didn't have, newer than everything it had (live arrivals, not older pages). */
export function arrivals(previous: readonly ActivityItem[], next: readonly ActivityItem[]): number[] {
  if (!previous.length) return [];
  const newest = previous.reduce((max, item) => Math.max(max, item.id), 0);
  return next.filter((item) => item.id > newest).map((item) => item.id);
}

/** Where a subject chip leads inside the console (existing routes). */
export function subjectPath(subject: { type: SubjectType; id: number }, companyId: number): string {
  const base = `/c/${companyId}`;
  if (subject.type === "task") return `${base}/tasks?task=${subject.id}`;
  if (subject.type === "member") return `${base}/people/${subject.id}`;
  return `${base}/ai/voice?draft=${subject.id}`;
}

// ─── Ask AI ─────────────────────────────────────────────────────────────────

export const TURN_POLL_MS = 1000;

export function turnIsLive(status: TurnStatus | undefined | null): boolean {
  return status === "queued" || status === "running";
}

// ─── Small formats ──────────────────────────────────────────────────────────

/** 14 → "0:14", 125 → "2:05". */
export function formatSeconds(total: number): string {
  const value = Math.max(0, Math.floor(total));
  return `${Math.floor(value / 60)}:${String(value % 60).padStart(2, "0")}`;
}

/** "$0.42 of $20.00" pieces: spent as a share of the budget, 0–1. */
export function budgetShare(budget: { monthly_usd: string; spent_usd: string } | null | undefined): number {
  if (!budget) return 0;
  const monthly = Number(budget.monthly_usd);
  const spent = Number(budget.spent_usd);
  if (!Number.isFinite(monthly) || monthly <= 0 || !Number.isFinite(spent)) return 0;
  return Math.min(1, Math.max(0, spent / monthly));
}
