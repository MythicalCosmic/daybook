/**
 * One agent's page (briefs/v5-agent-page.md), its logic free of Vue and the network so it is tested
 * on its own: the sections `?tab=` names, the status pill, the scene's state, the night and the
 * lines on its screen, the KPI strip read from the API's strings, and dollars, tokens and times.
 */
import type { Language } from "@/api/types";
import { shareText } from "@/components/chartCard";
import { addDays, formatDay, formatInstant, formatRelative, todayIn, zonedDay, zonedNow } from "@/lib/dates";
import { capitalize, formatNumber } from "@/lib/format";
import { formatCompact } from "@/lib/money";

import type { Tone } from "./lib";
import { isNightHour, type SceneState } from "./scene";
import type { ActivityItem, Agent, AgentDetail, AgentRun, AgentRunStatus, AgentUsage } from "./types";

/** vue-i18n's `t` as these functions use it (a count picks the plural form). */
export type Translate = (key: string, named?: Record<string, unknown>, plural?: number) => string;

// ─── Sections ───────────────────────────────────────────────────────────────

/** The page's sections in order: what it did, its internal log, tokens, what's next, settings. */
export const AGENT_TABS = ["done", "log", "tokens", "next", "settings"] as const;
export type AgentTab = (typeof AGENT_TABS)[number];

// ─── Which agents work on a schedule ────────────────────────────────────────

/** The agents with a schedule (they have "Run now"); a backend that names a next run says so for any other. */
const SCHEDULED_AGENTS = new Set(["deadline_watcher", "morning_plan", "hr_assistant"]);

export function isScheduled(agent: Pick<Agent, "key" | "next_run_at">): boolean {
  return SCHEDULED_AGENTS.has(agent.key) || agent.next_run_at !== null;
}

// ─── Status and scene ───────────────────────────────────────────────────────

export type AgentStatusKey = "working" | "on" | "off" | "ai_off" | "needs_claude";

/** The pill beside the name: at work now, on, off, AI off for the company, or waiting for a Claude key. */
export function agentStatus(agent: Pick<Agent, "running" | "enabled" | "unavailable_reason">, aiOn: boolean): { key: AgentStatusKey; tone: Tone; live: boolean } {
  if (agent.running) return { key: "working", tone: "primary", live: true };
  if (!aiOn || agent.unavailable_reason === "ai_off") return { key: "ai_off", tone: "neutral", live: false };
  if (agent.unavailable_reason === "needs_claude") return { key: "needs_claude", tone: "warning", live: false };
  return agent.enabled ? { key: "on", tone: "success", live: false } : { key: "off", tone: "neutral", live: false };
}

/**
 * What the scene shows, by the server's rule (working while it runs, idle while on and able to
 * run, else asleep) read from the agent's own fields too, so a switch or "Run now" shows at once.
 * A run already going finishes even if the agent is switched off meanwhile.
 */
export function sceneOf(agent: Pick<AgentDetail, "running" | "enabled" | "available"> & { scene?: SceneState }, aiOn: boolean): SceneState {
  if (agent.running || agent.scene === "working") return "working";
  return aiOn && agent.enabled && agent.available ? "idle" : "asleep";
}

/** Night in the company (20:00–06:00 by its clock): the scene's window goes dark. */
export function isNight(timeZone: string, now: number): boolean {
  return isNightHour(zonedNow(timeZone, now).getHours());
}

/** The room's wall clock and calendar: the time and the day of the month in the company. */
export function sceneClock(timeZone: string, now: number): { hours: number; minutes: number; day: number } {
  const local = zonedNow(timeZone, now);
  return { hours: local.getHours(), minutes: local.getMinutes(), day: local.getDate() };
}

/** What the agent did today in the company (its activity of today), for its chibi to tell. */
export function doneToday(items: readonly Pick<ActivityItem, "created_at">[], timeZone: string, now: number): number {
  const today = todayIn(timeZone, now);
  return items.filter((item) => zonedDay(item.created_at, timeZone) === today).length;
}

// ─── The lines on its screen ────────────────────────────────────────────────

/** How many lines the page hands the scene (it shows the newest that fit: scene.ts screenLines). */
export const SCENE_LINES = 6;

/** A run in a few words: working, stopped with an error, what it did, or nothing new. */
export function runLine(run: Pick<AgentRun, "status" | "done">, t: Translate): string {
  if (run.status === "running") return t("ai.agent.line.running");
  if (run.status === "error") return t("ai.agent.line.error");
  return run.done > 0 ? t("ai.agent.line.done", { n: run.done }, run.done) : t("ai.agent.line.quiet");
}

/**
 * An activity text as its own screen shows it: without the agent's own name in front, which the
 * room already says ("Ertalabki reja (Dilnoza Karimova): bugun …" → "Dilnoza Karimova: bugun …").
 */
export function screenText(text: string, agentName: string): string {
  const name = agentName.trim();
  if (!name || !text.startsWith(name)) return text;
  const rest = text.slice(name.length).trim();
  const named = /^\(([^)]+)\)\s*([\s\S]*)$/.exec(rest);
  if (named) return `${named[1]}${named[2].startsWith(":") ? "" : " "}${named[2]}`.trim() || text;
  return rest.replace(/^[:—–-]\s*/, "") || text;
}

/**
 * The newest things it did (activity texts) and its runs in a few words, newest last, at most
 * `max`. A run that found nothing new shows once (the newest), so thirty quiet checks don't push
 * what it really did off the screen; a run still going is always the last line.
 */
export function sceneLines(activity: readonly Pick<ActivityItem, "text" | "created_at">[], runs: readonly AgentRun[], t: Translate, max = SCENE_LINES, agentName = ""): string[] {
  const lines = [
    ...activity.map((item) => ({ at: Date.parse(item.created_at), text: screenText(item.text, agentName), quiet: false })),
    ...runs.map((run) => ({
      at: run.status === "running" ? Number.POSITIVE_INFINITY : Date.parse(run.finished_at ?? run.started_at),
      text: runLine(run, t),
      quiet: run.status === "ok" && run.done === 0,
    })),
  ].sort((a, b) => b.at - a.at);
  const picked: string[] = [];
  let quietShown = false;
  for (const line of lines) {
    if (line.quiet && quietShown) continue;
    quietShown ||= line.quiet;
    picked.push(line.text);
    if (picked.length === max) break;
  }
  return picked.reverse();
}

// ─── Numbers ────────────────────────────────────────────────────────────────

/**
 * Dollars from the API's string ("0.003500"), as the AI settings show them: "$0.42", "$12.50",
 * and below a cent four places ("$0.0035": Haiku's calls cost fractions of a cent), so something
 * spent never reads "$0.00" ("<$0.0001" below that). Null stays null: hidden or unknown, the
 * caller says which.
 */
export function usdText(value: string | number | null | undefined): string | null {
  if (value === null || value === undefined || value === "") return null;
  const amount = Number(value);
  if (!Number.isFinite(amount)) return null;
  if (amount === 0) return "$0.00";
  if (amount > 0 && amount < 0.0001) return "<$0.0001";
  return `$${amount.toFixed(amount < 0.01 ? 4 : 2)}`;
}

/** Tokens: "48 210", or "48,2 ming" / "48,2 тыс." / "48.2K" with `compact` from ten thousand up. */
export function tokensText(count: number | null | undefined, lang: Language, compact = false): string {
  if (count === null || count === undefined || !Number.isFinite(count)) return "—";
  return compact && Math.abs(count) >= 10_000 ? formatCompact(count, lang) : formatNumber(count, lang);
}

const TIME_UNITS: Record<Language, { s: string; m: string }> = { uz: { s: "s", m: "daq" }, ru: { s: "с", m: "мин" }, en: { s: "s", m: "m" } };

/** How long a run or a call took: "<0,1 s", "2,4 s", "42 s", "3 daq 5 s" (en "2.4s", "3m 5s"). */
export function durationText(ms: number | null | undefined, lang: Language): string {
  if (ms === null || ms === undefined || !Number.isFinite(ms) || ms < 0) return "—";
  const unit = TIME_UNITS[lang];
  const join = (value: string | number, name: string) => (lang === "en" ? `${value}${name}` : `${value} ${name}`);
  if (ms < 100) return `<${join(formatNumber(0.1, lang, 1), unit.s)}`;
  if (ms < 60_000) return join(formatNumber(ms / 1000, lang, ms < 10_000 ? 1 : 0), unit.s);
  const total = Math.round(ms / 1000);
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  return seconds ? `${join(minutes, unit.m)} ${join(seconds, unit.s)}` : join(minutes, unit.m);
}

export const RUN_TONE: Record<AgentRunStatus, Tone> = { running: "primary", ok: "success", error: "danger" };

/** This agent's part of the company's AI spending this month, and the company's part of its budget (ai.configure). */
export function monthShare(usage: Pick<AgentUsage, "month" | "company">): { agent: number; company: number; budget: number; share: number | null; budgetShare: number | null } | null {
  const company = usage.company;
  if (!company || usage.month.cost_usd === null) return null;
  const agent = Number(usage.month.cost_usd);
  const spent = Number(company.month_cost_usd);
  const budget = Number(company.monthly_budget_usd);
  if (![agent, spent, budget].every(Number.isFinite)) return null;
  return {
    agent,
    company: spent,
    budget,
    share: spent > 0 ? Math.min(100, (agent / spent) * 100) : null,
    budgetShare: budget > 0 ? (spent / budget) * 100 : null,
  };
}

// ─── The KPI strip ──────────────────────────────────────────────────────────

export interface AgentKpi {
  id: "last" | "next" | "tokens" | "cost";
  label: string;
  /** Short, to fit a tile two to a row on a phone: a time, a count, an amount. */
  value: string;
  /** After the value, smaller ("/ 6,9 ming": the output tokens after the input). */
  secondary?: string;
  hint?: string;
  /** The last run's outcome, as a small pill under the time. */
  status?: { tone: Tone; label: string; live: boolean };
  /** The value is private to people who set up AI (shown as "hidden", never as 0). */
  hidden?: boolean;
}

export interface KpiContext {
  t: Translate;
  lang: Language;
  timeZone: string;
  now: number;
  aiOn: boolean;
}

/**
 * When something coming up happens, said once: "Bugun, 15:15" (with "20 daqiqadan keyin" beside
 * it), "Ertaga, 08:30", "Payshanba, 5-noyabr, 08:30".
 */
export function upcomingWhen(iso: string, timeZone: string, lang: Language, now: number, today: string): { when: string; soon: string | null } {
  const day = zonedDay(iso, timeZone);
  const time = formatInstant(iso, timeZone, lang, "time");
  if (day === todayIn(timeZone, now)) {
    const relative = formatRelative(iso, timeZone, lang, now);
    return { when: `${today}, ${time}`, soon: relative === time ? null : relative };
  }
  if (day === addDays(todayIn(timeZone, now), 1)) return { when: capitalize(formatRelative(iso, timeZone, lang, now)), soon: null };
  // Russian weekdays come lower-case from Intl ("четверг, 5 ноября").
  return { when: capitalize(`${formatDay(day, lang, "weekday")}, ${time}`), soon: null };
}

/** An instant as a tile shows it: the time today ("14:30"), else "Kecha, 14:30" / "Ertaga, 09:00" / the date. */
export function clockText(iso: string, timeZone: string, lang: Language, now: number): string {
  if (zonedDay(iso, timeZone) === todayIn(timeZone, now)) return formatInstant(iso, timeZone, lang, "time");
  return capitalize(formatRelative(iso, timeZone, lang, now));
}

/** Last run (when, how it went), next run, tokens this month (in / out) and the month's cost. */
export function agentKpis(agent: AgentDetail, ctx: KpiContext): AgentKpi[] {
  const { t, lang, timeZone, now } = ctx;
  const clock = (iso: string) => clockText(iso, timeZone, lang, now);

  // "3 min ago" under "14:49"; nothing more under "Kecha, 14:30", which already says it.
  const ago = (iso: string, shown: string) => {
    const relative = formatRelative(iso, timeZone, lang, now);
    return relative.toLocaleLowerCase() === shown.toLocaleLowerCase() ? null : relative;
  };
  const join = (...parts: (string | null)[]) => parts.filter(Boolean).join(" · ") || undefined;

  const run = agent.runs[0] ?? null;
  const last: AgentKpi = { id: "last", label: t("ai.agent.kpi.last"), value: "—", hint: t("ai.agent.kpi.never") };
  if (run) {
    last.value = clock(run.started_at);
    last.status = { tone: RUN_TONE[run.status], label: t(`ai.agent.run.${run.status}`), live: run.status === "running" };
    last.hint = join(ago(run.started_at, last.value), run.status !== "running" && run.duration_ms !== null ? durationText(run.duration_ms, lang) : null);
  } else if (agent.last_run_at) {
    last.value = clock(agent.last_run_at);
    last.hint = join(ago(agent.last_run_at, last.value));
  }

  const on = ctx.aiOn && agent.enabled;
  const nextAt = agent.next_run_at ?? agent.upcoming.find((item) => item.kind === "run" && item.at)?.at ?? null;
  const next: AgentKpi = { id: "next", label: t("ai.agent.kpi.next"), value: "—" };
  if (!on) next.hint = t("ai.agent.kpi.nextOff");
  else if (nextAt) {
    next.value = clock(nextAt);
    // Tomorrow's run says when it repeats instead ("Ish kunlari, soat 08:30").
    next.hint = ago(nextAt, next.value) ?? agent.schedule;
  } else if (!isScheduled(agent)) {
    next.value = t("ai.agent.kpi.onEvent");
    next.hint = agent.schedule;
  }

  const month = agent.usage.month;
  const tokens: AgentKpi = {
    id: "tokens",
    label: t("ai.agent.kpi.tokens"),
    value: tokensText(month.input_tokens, lang, true),
    secondary: `/ ${tokensText(month.output_tokens, lang, true)}`,
    hint: t("ai.agent.kpi.tokensHint", { n: month.calls }, month.calls),
  };

  const cost: AgentKpi = { id: "cost", label: t("ai.agent.kpi.cost"), value: usdText(month.cost_usd) ?? t("ai.agent.hidden") };
  if (month.cost_usd === null) {
    cost.hidden = true;
    cost.hint = t("ai.agent.kpi.costHidden");
  } else {
    const share = monthShare(agent.usage);
    if (share && share.share !== null) cost.hint = t("ai.agent.kpi.share", { share: shareText(share.share, lang) });
  }
  return [last, next, tokens, cost];
}
