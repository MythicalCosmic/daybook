/**
 * The AI module's logic, free of Vue and the network so it is tested on its own: what the status
 * lets a person see, how a draft is edited and sent back, what a problem's one-tap fix does, how
 * the generic agent settings become form controls, and how the activity feed merges its pages.
 */
import { TZDate } from "@date-fns/tz";

import { isApiError } from "@/api/http";
import type { Pulse } from "@/api/types";
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

// ─── A server without the endpoint yet ──────────────────────────────────────

/**
 * The server doesn't have this endpoint yet (an AI step not deployed): Django's 404 without a body
 * of ours, or 405. The pages then show their quiet "coming" state instead of an error.
 */
export function isMissingEndpoint(error: unknown): boolean {
  return isApiError(error) && (error.status === 405 || (error.status === 404 && !error.code));
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

// The AI's little helper on the Agents page (components/AiBuddy.vue draws it, AiBuddyStage.vue
// moves it) ---------------------------------------------------------------------------------------

export type BuddyMood = "on" | "busy";
export type BuddyAction = "idle" | "blink" | "look" | "hop" | "wave" | "dance" | "hearts" | "love" | "sparkle" | "type" | "touch" | "tap" | "listen" | "ring" | "cheer";
/** The family: Claude itself, and one chibi per agent, each with its colours and its prop. */
export type BuddyVariant = "claude" | "voice" | "morning" | "deadline" | "photo";

const AGENT_BUDDIES: Record<string, BuddyVariant> = { voice_tasks: "voice", morning_plan: "morning", deadline_watcher: "deadline", photo_checker: "photo" };

/** An agent's chibi; an agent without one of its own gets Claude. */
export function buddyVariant(agentKey: string): BuddyVariant {
  return AGENT_BUDDIES[agentKey] ?? "claude";
}

/** What it does in place, by mood: while an agent runs it mostly types and sparkles. */
const BUDDY_POOLS: Record<BuddyMood, readonly BuddyAction[]> = {
  on: ["blink", "blink", "look", "hop", "wave", "dance", "hearts", "love", "sparkle"],
  busy: ["type", "type", "type", "sparkle", "sparkle", "blink", "hop", "hearts"],
};

export const BUDDY_DURATION: Record<BuddyAction, number> = {
  idle: 0,
  blink: 220,
  look: 1400,
  hop: 650,
  wave: 1300,
  dance: 1400,
  hearts: 1500,
  love: 1600,
  sparkle: 1200,
  type: 1800,
  touch: 900,
  tap: 1300,
  listen: 2400,
  ring: 1800,
  cheer: 1600,
};

export type BuddyParticle = "heart" | "spark" | "z" | "wave" | "alert";

export const BUDDY_PARTICLES: Partial<Record<BuddyAction, { kind: BuddyParticle; count: number }>> = {
  hearts: { kind: "heart", count: 3 },
  love: { kind: "heart", count: 2 },
  tap: { kind: "heart", count: 4 },
  sparkle: { kind: "spark", count: 3 },
  type: { kind: "spark", count: 2 },
  touch: { kind: "spark", count: 2 },
  listen: { kind: "wave", count: 3 },
  ring: { kind: "alert", count: 2 },
  cheer: { kind: "heart", count: 4 },
};

/** The next thing it does in place; `random` in [0, 1) picks from the mood's pool. */
export function pickBuddyAction(mood: BuddyMood, random: number): BuddyAction {
  const pool = BUDDY_POOLS[mood];
  return pool[Math.min(pool.length - 1, Math.floor(random * pool.length))]!;
}

/** An agent's chibi on its card is calmer than Claude: mostly blinks and looks, types while its agent runs. */
const CHIBI_POOLS = {
  on: ["blink", "blink", "blink", "look", "look", "wave", "hearts", "hop"],
  busy: ["type", "type", "sparkle", "blink"],
} as const satisfies Record<string, readonly BuddyAction[]>;

export function pickChibiAction(running: boolean, random: number): BuddyAction {
  const pool = CHIBI_POOLS[running ? "busy" : "on"];
  return pool[Math.min(pool.length - 1, Math.floor(random * pool.length))]!;
}

export type BuddyPlan = { kind: "act"; action: BuddyAction } | { kind: "stroll" } | { kind: "visit"; card: number };

/** What it does next: visit one of the `cards` it can see, stroll along its strip, or act in place. */
export function planBuddy(mood: BuddyMood, cards: number, random: () => number): BuddyPlan {
  const roll = random();
  if (cards > 0 && roll < 0.3) return { kind: "visit", card: Math.min(cards - 1, Math.floor(random() * cards)) };
  if (roll < 0.45) return { kind: "stroll" };
  return { kind: "act", action: pickBuddyAction(mood, random()) };
}

/** Pixels a second when it walks. */
export const BUDDY_SPEED = 110;

export function buddyWalkMs(dx: number, dy: number): number {
  return Math.round(Math.min(3200, Math.max(450, (Math.hypot(dx, dy) / BUDDY_SPEED) * 1000)));
}

export type Box = { left: number; top: number; width: number; height: number };

/** Its height for a width (the drawing is 36 × 34, its props above the head) and where its feet
 * are from its top (row 30). */
export function buddyBox(size: number): { height: number; feet: number } {
  return { height: Math.round((size * 34) / 36), feet: Math.round((size * 30) / 36) };
}

/**
 * Where it stands on a card, in `root`'s coordinates: feet on the card's top edge, somewhere on its
 * left part (`random` in [0, 1)) — over the card above it stands in front of the day's numbers, not
 * the "Run now" button on the right. Sitting puts the body on the edge, legs hanging.
 */
export function standPoint(card: Box, root: Box, size: number, random: number, sitting = false): { x: number; y: number } {
  const { feet } = buddyBox(size);
  const span = Math.max(0, card.width - size - 24) * 0.6;
  const legs = Math.round((size * 6) / 36);
  return { x: Math.round(card.left - root.left + 12 + random * span), y: Math.round(card.top - root.top - feet + (sitting ? legs : 0)) };
}

// What happens in the company, as the helpers' reactions (components/buddyCues.ts) ----------------

/** One reaction: `key` is an agent's key, or "" for everyone; `visit` sends Claude to that card. */
export type BuddyReaction = { key: string; action: BuddyAction; visit?: boolean };

/** Agent activity that arrived since the last look, as reactions: a late task told to someone
 * rings the deadline watcher's clock (and Claude goes to see), tasks made from a voice note
 * please its chibi, a checked photo pleases or puzzles the photo checker. */
export function activityReactions(items: readonly Pick<ActivityItem, "agent" | "kind">[]): BuddyReaction[] {
  return items.flatMap((item): BuddyReaction[] => {
    switch (`${item.agent}:${item.kind}`) {
      case "deadline_watcher:escalated":
        return [{ key: "deadline_watcher", action: "ring", visit: true }];
      case "voice_tasks:draft_applied":
      case "voice_tasks:draft_auto_applied":
        return [{ key: "voice_tasks", action: "hearts" }];
      case "photo_checker:looks_right":
        return [{ key: "photo_checker", action: "hearts" }];
      case "photo_checker:check":
      case "photo_checker:unclear":
        return [{ key: "photo_checker", action: "look" }];
      case "morning_plan:plan_sent":
        return [{ key: "morning_plan", action: "wave" }];
      default:
        return [];
    }
  });
}

/** Between two pulses: a task went late (the late count went up), and the tasks changed (worth
 * asking whether one was finished). The first real pulse is only the baseline — the empty one the
 * shell holds before the server first answers is none. */
export function pulseCues(previous: Pick<Pulse, "counters" | "versions"> | null, next: Pick<Pulse, "counters" | "versions">): { late: boolean; tasksChanged: boolean } {
  if (!previous || (!Object.keys(previous.counters).length && !Object.keys(previous.versions).length)) return { late: false, tasksChanged: false };
  return {
    late: (next.counters["tasks.late_now"] ?? 0) > (previous.counters["tasks.late_now"] ?? 0),
    tasksChanged: (next.versions["tasks.tasks"] ?? "") !== (previous.versions["tasks.tasks"] ?? ""),
  };
}

/** The newest voice notes against what was seen before: listen while any is being written down,
 * and a happy moment for a note that became tasks to look at (ready or created) since. */
export function draftCues(seen: ReadonlyMap<number, DraftStatus> | null, drafts: readonly Pick<AiDraft, "id" | "status">[]): { seen: Map<number, DraftStatus>; listen: boolean; done: boolean } {
  const now = new Map(drafts.map((draft) => [draft.id, draft.status] as const));
  const listen = drafts.some((draft) => WORKING.includes(draft.status));
  if (!seen) return { seen: now, listen, done: false };
  const done = drafts.some((draft) => (draft.status === "ready" || draft.status === "applied") && seen.get(draft.id) !== draft.status && (!seen.has(draft.id) || WORKING.includes(seen.get(draft.id)!)));
  return { seen: now, listen, done };
}

