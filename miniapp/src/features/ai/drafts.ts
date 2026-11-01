/**
 * The review of what the AI heard, as plain data: each task it understood becomes an editable
 * card, the problems the server saw stay until the person fixes them (or a fix is one tap: "Make
 * it mine", "Same time tomorrow"), and the cards go back as the `apply/` payload.
 */
import { whenDue, whenOf, type WhenValue } from "../../components/WhenPicker";
import { addDays, clock, dayKey } from "../../lib/time";
import type { AIDraft, ApplyItem, DraftItem, Problem } from "./api";

export type EditableDraft = {
  /** Stable for React while cards are removed. */
  key: string;
  title: string;
  description: string;
  /** Null: for me. */
  assigneeId: number | null;
  /** Who the server matched (shown even when they aren't in the picker's list). */
  assignee: DraftItem["assignee"];
  /** Who was heard but not matched ("Alisher"), for the problem line. */
  assigneeGuess: string;
  /** The person picked someone (or "Me") themselves: the server's doubts about who no longer apply. */
  assigneeTouched: boolean;
  when: WhenValue;
  /** The person changed the time themselves. */
  whenTouched: boolean;
  priority: "normal" | "urgent";
  proof: "none" | "photo";
  checklist: string[];
  removed: boolean;
  /** What the server saw wrong with the card as it came. */
  serverProblems: readonly Problem[];
  /** "No deadline is fine": problems the person chose to leave. */
  accepted: readonly Problem[];
};

const WHO: readonly Problem[] = ["no_assignee_match", "ambiguous_assignee", "not_allowed"];

/** The cards for a ready draft. A deadline that has passed stays as heard, so the card can say so. */
export function editableFrom(draft: Pick<AIDraft, "id" | "drafts">, now: Date, timeZone: string): EditableDraft[] {
  return draft.drafts.map((item, index) => {
    const passed = item.due_at !== null && new Date(item.due_at) <= now;
    const when: WhenValue = passed
      ? { when: "date", date: dayKey(item.due_at!, timeZone), time: clock(item.due_at!, timeZone, "en-GB") }
      : whenOf(item.due_at, now, timeZone);
    return {
      key: `${draft.id}-${index}`,
      title: item.title,
      description: item.description,
      assigneeId: item.assignee?.id ?? null,
      assignee: item.assignee,
      assigneeGuess: item.assignee_guess,
      assigneeTouched: false,
      when,
      whenTouched: false,
      priority: item.priority === "urgent" ? "urgent" : "normal",
      proof: item.proof === "photo" ? "photo" : "none",
      checklist: [...item.checklist],
      removed: false,
      serverProblems: [...item.problems],
      accepted: [],
    };
  });
}

/** The deadline a card stands for now. */
export function dueOf(card: EditableDraft, now: Date, timeZone: string): Date | null {
  return whenDue(card.when, now, timeZone).due;
}

/** What is still wrong with a card, in the order the card shows the fixes. */
export function problemsOf(card: EditableDraft, now: Date, timeZone: string): Problem[] {
  const problems: Problem[] = [];
  const open = (problem: Problem) => card.serverProblems.includes(problem) && !card.accepted.includes(problem);
  if (!card.assigneeTouched) for (const problem of WHO) if (open(problem)) problems.push(problem);
  const due = dueOf(card, now, timeZone);
  if (due !== null && due <= now) problems.push("past_due");
  else if (due === null && !card.whenTouched && open("past_due")) problems.push("past_due");
  else if (due === null && !card.whenTouched && open("no_due")) problems.push("no_due");
  return problems;
}

/** Problems that stop "Create": the wrong person, a time already gone. A missing deadline is allowed. */
export function isBlocking(problem: Problem): boolean {
  return problem !== "no_due";
}

/** Whether a card can be created as it stands. */
export function cardReady(card: EditableDraft, now: Date, timeZone: string): boolean {
  return Boolean(card.title.trim()) && !problemsOf(card, now, timeZone).some(isBlocking);
}

/** The cards that will become tasks. */
export function kept(cards: readonly EditableDraft[]): EditableDraft[] {
  return cards.filter((card) => !card.removed);
}

/** The first card (by key) that still needs a fix before creating, or null when all are ready. */
export function firstUnready(cards: readonly EditableDraft[], now: Date, timeZone: string): string | null {
  return kept(cards).find((card) => !cardReady(card, now, timeZone))?.key ?? null;
}

/** The `apply/` body: every kept card, as the person left it. */
export function applyPayload(cards: readonly EditableDraft[], now: Date, timeZone: string): ApplyItem[] {
  return kept(cards).map((card) => ({
    title: card.title.trim(),
    description: card.description.trim(),
    assignee_id: card.assigneeId,
    due_at: dueOf(card, now, timeZone)?.toISOString() ?? null,
    priority: card.priority,
    checklist: card.checklist.map((step) => step.trim()).filter(Boolean),
    proof: card.proof,
  }));
}

// — one-tap fixes —

/** "Make it mine": the task stays with the author, and the doubt about who is settled. */
export function makeMine(card: EditableDraft): EditableDraft {
  return { ...card, assigneeId: null, assigneeTouched: true };
}

/** Someone picked in the list (null: "Me"). */
export function pickAssignee(card: EditableDraft, assigneeId: number | null): EditableDraft {
  return { ...card, assigneeId, assigneeTouched: true };
}

export function setWhen(card: EditableDraft, when: WhenValue): EditableDraft {
  return { ...card, when, whenTouched: true };
}

/** "Same time tomorrow" for a time that has passed (tomorrow 09:00 when no time was heard). */
export function sameTimeTomorrow(card: EditableDraft, now: Date, timeZone: string): EditableDraft {
  return setWhen(card, { ...card.when, when: "tomorrow", date: addDays(dayKey(now, timeZone), 2), time: card.when.time || "09:00" });
}

/** A deadline chip for a card that had none: today at `time` (tomorrow when it has passed) or tomorrow. */
export function quickDue(card: EditableDraft, day: "today" | "tomorrow", time: string): EditableDraft {
  return setWhen(card, { ...card.when, when: day, time });
}

/** "No deadline is fine". */
export function acceptProblem(card: EditableDraft, problem: Problem): EditableDraft {
  return card.accepted.includes(problem) ? card : { ...card, accepted: [...card.accepted, problem] };
}
