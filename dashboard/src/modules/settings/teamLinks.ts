/**
 * Team links in words and numbers (Settings › Invite staff): which list a link sits in, its status
 * pill, the rule ("Adds straight away · Chilonzor · Farmatsevt role"), the places ("12 of 20
 * joined"), the end ("Until 27 Oct, 18:00") and the end a "Works for" choice gives. Pure, so the
 * list, the dialog and the live screen say the same thing.
 */
import { TZDate } from "@date-fns/tz";

import type { Language } from "@/api/types";
import type { StatusTone } from "@/components/StatusPill.vue";
import { formatInstant, todayIn, zonedDay } from "@/lib/dates";

import type { JoinLink, JoinLinkPerson, JoinLinkStatus } from "./types";

type T = (key: string, params?: Record<string, unknown>, plural?: number) => string;

const HOUR = 3_600_000;
const DAY = 24 * HOUR;

// ─── Lists and status ───────────────────────────────────────────────────────

/** Stopped and expired links are over; active and full ones still matter (a full one can grow). */
export function isEnded(link: Pick<JoinLink, "status">): boolean {
  return link.status === "stopped" || link.status === "expired";
}

/** The live links in the server's order (active first, then newest) and the ended ones apart. */
export function groupLinks<L extends Pick<JoinLink, "status">>(links: readonly L[]): { live: L[]; ended: L[] } {
  return { live: links.filter((link) => !isEnded(link)), ended: links.filter(isEnded) };
}

/** The "Ended" group starts open while it is this short, folded when longer. */
export const ENDED_OPEN_MAX = 3;

export const STATUS_TONE: Record<JoinLinkStatus, StatusTone> = { active: "success", full: "warning", expired: "neutral", stopped: "neutral" };

/** What the server would say now (stopped > expired > full > active): a change shown before its answer. */
export function statusNow(link: Pick<JoinLink, "is_active" | "expires_at" | "max_uses" | "uses">, now = Date.now()): JoinLinkStatus {
  if (!link.is_active) return "stopped";
  if (link.expires_at && new Date(link.expires_at).getTime() <= now) return "expired";
  if (link.max_uses !== null && link.uses >= link.max_uses) return "full";
  return "active";
}

// ─── Words ──────────────────────────────────────────────────────────────────

/** Places still free, or null without a limit. */
export function placesLeft(link: Pick<JoinLink, "max_uses" | "uses">): number | null {
  return link.max_uses === null ? null : Math.max(0, link.max_uses - link.uses);
}

/**
 * "12 of 20 joined", "12 joined", "No one yet". A link that asks for approval counts people who
 * signed up (they wait in Join requests), so it says so instead of "joined".
 */
export function placesText(link: Pick<JoinLink, "max_uses" | "uses" | "auto_approve">, t: T): string {
  const kind = link.auto_approve ? "joined" : "asked";
  if (link.max_uses !== null) return t(`settings.teamLinks.places.${kind}Of`, { n: link.uses, max: link.max_uses });
  if (!link.uses) return t("settings.teamLinks.places.none");
  return t(`settings.teamLinks.places.${kind}`, { n: link.uses });
}

/** The rule in words: how people get in, where, with which role and position. */
export function ruleParts(link: Pick<JoinLink, "auto_approve" | "branch" | "role" | "default_role" | "position">, t: T): string[] {
  const parts = [t(link.auto_approve ? "settings.teamLinks.rule.auto" : "settings.teamLinks.rule.ask")];
  if (link.branch) parts.push(link.branch.name);
  if (link.role) parts.push(t("settings.teamLinks.rule.role", { role: link.role.name }));
  else if (link.default_role) parts.push(t("settings.teamLinks.rule.defaultRole", { role: link.default_role.name }));
  if (link.position) parts.push(t("settings.teamLinks.rule.position", { position: link.position.name }));
  return parts;
}

/** An end as people say it: "18:00" today, "27 Oct, 18:00" this year, with the year after that. */
export function whenText(iso: string, tz: string, lang: Language, now = Date.now()): string {
  const day = zonedDay(iso, tz);
  const today = todayIn(tz, now);
  if (day === today) return formatInstant(iso, tz, lang, "time");
  return formatInstant(iso, tz, lang, day.slice(0, 4) === today.slice(0, 4) ? "short" : "datetime");
}

/** "Until 27 Oct, 18:00", "No end date", "Ended 25 Oct, 18:00". */
export function endText(link: Pick<JoinLink, "expires_at">, t: T, tz: string, lang: Language, now = Date.now()): string {
  if (!link.expires_at) return t("settings.teamLinks.end.none");
  const when = whenText(link.expires_at, tz, lang, now);
  return new Date(link.expires_at).getTime() <= now ? t("settings.teamLinks.end.ended", { when }) : t("settings.teamLinks.end.until", { when });
}

/** A name to start from: "Chilonzor, 26 Oct" once a branch is chosen, else "Team link, 26 Oct". */
export function defaultName(t: T, day: string, branch?: string | null): string {
  return branch ? `${branch}, ${day}` : t("settings.teamLinks.defaultName", { day });
}

/** The bot a link opens ("https://t.me/daybook_bot?start=j_x" → "daybook_bot"), for the poster. */
export function botOf(link: string): string {
  try {
    return new URL(link).pathname.replace(/^\/+/, "");
  } catch {
    return "";
  }
}

/** Telegram's share screen with the link and a line of text. */
export function telegramShare(link: string, text: string): string {
  return `https://t.me/share/url?url=${encodeURIComponent(link)}&text=${encodeURIComponent(text)}`;
}

/** Who the live screen shows, newest first: people signing up or in, never someone turned away or gone. */
export function livePeople(people: readonly JoinLinkPerson[], max: number): JoinLinkPerson[] {
  return people.filter((person) => person.status === "approved" || person.status === "pending").slice(0, max);
}

// ─── "Works for" → expires_at ───────────────────────────────────────────────

export const VALID_FOR = ["24h", "7d", "30d", "date", "none"] as const;
export type ValidFor = (typeof VALID_FOR)[number];
export const DEFAULT_VALID_FOR: ValidFor = "7d";
/** The backend refuses an end further away than this. */
export const MAX_AHEAD_DAYS = 365;
/** "Until a date" starts at tomorrow, this time. */
export const DEFAULT_END_TIME = "18:00";

const SPANS: Partial<Record<ValidFor, number>> = { "24h": DAY, "7d": 7 * DAY, "30d": 30 * DAY };

const pad = (n: number) => String(n).padStart(2, "0");

/** A company-local day and time as an instant: ("2026-10-27", "18:00", "Asia/Tashkent") → ISO. */
export function localToIso(day: string, time: string, tz: string): string {
  const [y, m, d] = day.split("-").map(Number) as [number, number, number];
  const [hh, mm] = time.split(":").map(Number) as [number, number];
  return new Date(new TZDate(y, m - 1, d, hh, mm, 0, tz).getTime()).toISOString();
}

/** The end a "Works for" choice gives, counted from `now` (the moment of saving); null: no end date. */
export function expiresAt(choice: ValidFor, now: number, date?: { day: string | null; time: string | null; tz: string }): string | null {
  const span = SPANS[choice];
  if (span) return new Date(now + span).toISOString();
  if (choice === "date" && date?.day && date.time) return localToIso(date.day, date.time, date.tz);
  return null;
}

/** Why an end can't be saved: it has passed, or it is more than a year away. */
export function expiryProblem(iso: string | null, now: number): "past" | "tooFar" | null {
  if (!iso) return null;
  const at = new Date(iso).getTime();
  if (at <= now) return "past";
  if (at - now > MAX_AHEAD_DAYS * DAY) return "tooFar";
  return null;
}

/** How the form shows a link's end: a date and time, no end date, or (a new link) the default. */
export function validForOf(link: Pick<JoinLink, "expires_at"> | null, tz: string): { choice: ValidFor; day: string | null; time: string | null } {
  if (!link) return { choice: DEFAULT_VALID_FOR, day: null, time: null };
  if (!link.expires_at) return { choice: "none", day: null, time: null };
  const zoned = new TZDate(new Date(link.expires_at).getTime(), tz);
  return { choice: "date", day: zonedDay(link.expires_at, tz), time: `${pad(zoned.getHours())}:${pad(zoned.getMinutes())}` };
}
