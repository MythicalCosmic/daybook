/**
 * When the bot would remind about a task, as `apps.reminders.engine` and `apps.reminders.schedule`
 * do it: a heads-up before the deadline (if there's still time for one), the first reminder at the
 * deadline, then one every N minutes until the cap, the manager told at reminder K; quiet hours
 * and quiet days push a reminder to when they end. Minutes count from 00:00 of the deadline's day.
 */

export interface PolicyShape {
  heads_up_minutes: number;
  repeat_every_minutes: number;
  /** 0 = until it's done. */
  max_reminders: number;
  /** 0 = nobody is told. */
  escalate_after: number;
  /** "22:00" or "22:00:00"; both null for no quiet hours. */
  quiet_from: string | null;
  quiet_until: string | null;
  /** 0 = Monday … 6 = Sunday. */
  quiet_days: number[];
}

export type PlanEventKind = "heads_up" | "reminder";

export interface PlanEvent {
  kind: PlanEventKind;
  /** Reminder number (0 for the heads-up). */
  step: number;
  /** Minutes from 00:00 of the deadline's day. */
  at: number;
  /** The manager hears about it with this reminder. */
  escalate: boolean;
  /** Quiet hours or a quiet day moved it later. */
  shifted: boolean;
  /** The last reminder: the bot stops after it. */
  last: boolean;
}

export interface QuietBand {
  from: number;
  to: number;
  /** A whole quiet day rather than quiet hours. */
  day: boolean;
}

export interface ReminderPlan {
  due: number;
  events: PlanEvent[];
  quiet: QuietBand[];
  /** The policy reminds until it's done; only the first `maxSteps` are shown. */
  endless: boolean;
  start: number;
  end: number;
}

const DAY = 24 * 60;

export function parseClock(value: string | null | undefined): number | null {
  if (!value) return null;
  const [h, m] = value.split(":").map(Number);
  return Number.isFinite(h) && Number.isFinite(m) ? h! * 60 + m! : null;
}

export function clock(minutes: number): string {
  const value = ((Math.round(minutes) % DAY) + DAY) % DAY;
  return `${String(Math.floor(value / 60)).padStart(2, "0")}:${String(value % 60).padStart(2, "0")}`;
}

/** Days after the deadline's day (0 the same day, 1 the next…). */
export function dayOffset(minutes: number): number {
  return Math.floor(minutes / DAY);
}

/** If `at` is quiet, the moment it stops being; else null (engine's `quiet_until`). */
export function quietUntil(at: number, policy: PolicyShape, dueWeekday: number): number | null {
  const start = parseClock(policy.quiet_from);
  const stop = parseClock(policy.quiet_until);
  let moment = at;
  for (let guard = 0; guard < 16; guard += 1) {
    const end = endOfQuietHours(moment, start, stop);
    if (end !== null) {
      moment = end;
      continue;
    }
    const weekday = (((dueWeekday + dayOffset(moment)) % 7) + 7) % 7;
    if (policy.quiet_days.includes(weekday)) {
      moment = (dayOffset(moment) + 1) * DAY;
      continue;
    }
    break;
  }
  return moment === at ? null : moment;
}

function endOfQuietHours(moment: number, start: number | null, stop: number | null): number | null {
  if (start === null || stop === null || start === stop) return null;
  const dayStart = dayOffset(moment) * DAY;
  const now = moment - dayStart;
  const todayStop = dayStart + stop;
  if (start < stop) return start <= now && now < stop ? todayStop : null;
  if (now >= start) return todayStop + DAY;
  return now < stop ? todayStop : null;
}

/** The plan for a deadline at `due` minutes (default 18:00) on `dueWeekday`, at most `maxSteps` reminders. */
export function planReminders(policy: PolicyShape, due = 18 * 60, dueWeekday = 0, maxSteps = 16): ReminderPlan {
  const events: PlanEvent[] = [];
  const repeat = Math.max(5, policy.repeat_every_minutes || 5);
  let at = policy.heads_up_minutes > 0 ? due - policy.heads_up_minutes : due;
  let step = 0;
  let escalated = false;
  let endless = false;
  for (let guard = 0; guard < maxSteps + 4; guard += 1) {
    const resume = quietUntil(at, policy, dueWeekday);
    const shifted = resume !== null;
    if (resume !== null) at = resume;
    if (at < due) {
      events.push({ kind: "heads_up", step: 0, at, escalate: false, shifted, last: false });
      at = due;
      continue;
    }
    step += 1;
    const escalate = policy.escalate_after > 0 && step >= policy.escalate_after && !escalated;
    if (escalate) escalated = true;
    const more = policy.max_reminders === 0 || step < policy.max_reminders;
    events.push({ kind: "reminder", step, at, escalate, shifted, last: !more });
    if (!more) break;
    if (step >= maxSteps) {
      endless = policy.max_reminders === 0;
      break;
    }
    at += repeat;
  }
  const first = events[0]?.at ?? due;
  const last = events.at(-1)?.at ?? due;
  const start = Math.min(first, due) - 20;
  const end = Math.max(last, due) + 20;
  return { due, events, quiet: quietBands(policy, start, end, dueWeekday), endless, start, end };
}

/** Quiet hours and quiet days that overlap [start, end]. */
export function quietBands(policy: PolicyShape, start: number, end: number, dueWeekday: number): QuietBand[] {
  const bands: QuietBand[] = [];
  const from = parseClock(policy.quiet_from);
  const until = parseClock(policy.quiet_until);
  for (let day = dayOffset(start) - 1; day <= dayOffset(end); day += 1) {
    const base = day * DAY;
    const weekday = (((dueWeekday + day) % 7) + 7) % 7;
    if (policy.quiet_days.includes(weekday)) bands.push({ from: base, to: base + DAY, day: true });
    if (from !== null && until !== null && from !== until) {
      const band = from < until ? { from: base + from, to: base + until } : { from: base + from, to: base + DAY + until };
      bands.push({ ...band, day: false });
    }
  }
  return mergeBands(bands.map((band) => ({ ...band, from: Math.max(band.from, start), to: Math.min(band.to, end) })).filter((band) => band.to > band.from));
}

function mergeBands(bands: QuietBand[]): QuietBand[] {
  const sorted = [...bands].sort((a, b) => a.from - b.from);
  const out: QuietBand[] = [];
  for (const band of sorted) {
    const previous = out.at(-1);
    if (previous && band.from <= previous.to) {
      previous.to = Math.max(previous.to, band.to);
      previous.day = previous.day || band.day;
    } else out.push({ ...band });
  }
  return out;
}

/**
 * Horizontal positions (0–1) for minutes on a track from `start` to `end`, quiet bands squeezed to
 * a small fixed share each so a long night doesn't push the reminders off the edge.
 */
export function trackScale(start: number, end: number, quiet: QuietBand[], quietShare = 0.07): (minutes: number) => number {
  const total = Math.max(1, end - start);
  const squeezed = quiet.reduce((sum, band) => sum + (band.to - band.from), 0);
  const quietTotal = Math.min(0.5, quiet.length * quietShare);
  const activeMinutes = Math.max(1, total - squeezed);
  const activeShare = quiet.length ? 1 - quietTotal : 1;
  const perQuiet = quiet.length ? quietTotal / quiet.length : 0;
  return (minutes: number) => {
    let position = 0;
    let cursor = start;
    for (const band of quiet) {
      if (minutes <= band.from) break;
      position += ((Math.min(minutes, band.from) - cursor) / activeMinutes) * activeShare;
      if (minutes < band.to) return Math.min(1, position + ((minutes - band.from) / (band.to - band.from)) * perQuiet);
      position += perQuiet;
      cursor = band.to;
    }
    position += ((Math.max(minutes, cursor) - cursor) / activeMinutes) * activeShare;
    return Math.max(0, Math.min(1, position));
  };
}
