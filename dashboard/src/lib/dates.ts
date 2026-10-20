/**
 * Dates in the COMPANY's timezone (from `me`), never the browser's (plan §6.3).
 *
 * Two kinds of values: a company-local day ("2026-10-20", what the API takes and returns for days)
 * and an instant (an ISO timestamp). Day arithmetic happens on the Y-M-D numbers in UTC, so the
 * browser's own zone and DST never shift a day; instants are shown with Intl in the company zone.
 */
import { TZDate } from "@date-fns/tz";

import type { Language, Range } from "@/api/types";

export type DatePreset = "today" | "yesterday" | "week" | "last_week" | "month" | "last_month" | "last_30" | "quarter" | "year";
export type CompareMode = "none" | "prev" | "year";

export const DATE_PRESETS: readonly DatePreset[] = ["today", "yesterday", "week", "last_week", "month", "last_month", "last_30", "quarter", "year"];

const DAY_MS = 86_400_000;

const INTL_LOCALE: Record<Language, string> = { uz: "uz-Latn-UZ", ru: "ru-RU", en: "en-GB" };

export function intlLocale(lang: Language): string {
  return INTL_LOCALE[lang];
}

/** Intl's Uzbek output uses ʻ/ʼ; the product writes o‘ and g‘ with U+2018 and the apostrophe U+2019. */
export function fixUzbek(text: string, lang: Language): string {
  return lang === "uz" ? text.replace(/ʻ/g, "‘").replace(/ʼ/g, "’") : text;
}

function pad(n: number, width = 2): string {
  return String(n).padStart(width, "0");
}

export function isDay(value: string): boolean {
  return /^\d{4}-\d{2}-\d{2}$/.test(value);
}

/** "2026-10-20" → UTC-midnight Date (for arithmetic and Intl with timeZone UTC). */
export function parseDay(day: string): Date {
  const [y, m, d] = day.split("-").map(Number) as [number, number, number];
  return new Date(Date.UTC(y, m - 1, d));
}

export function dayOf(date: Date): string {
  return `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())}`;
}

export function addDays(day: string, amount: number): string {
  return dayOf(new Date(parseDay(day).getTime() + amount * DAY_MS));
}

export function addMonths(day: string, amount: number): string {
  const date = parseDay(day);
  const target = new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth() + amount, 1));
  const lastDay = new Date(Date.UTC(target.getUTCFullYear(), target.getUTCMonth() + 1, 0)).getUTCDate();
  target.setUTCDate(Math.min(date.getUTCDate(), lastDay));
  return dayOf(target);
}

export function addYears(day: string, amount: number): string {
  return addMonths(day, amount * 12);
}

/** Whole days from a to b (b − a). */
export function diffDays(a: string, b: string): number {
  return Math.round((parseDay(b).getTime() - parseDay(a).getTime()) / DAY_MS);
}

/** Monday of the week containing `day`. */
export function startOfWeek(day: string): string {
  const weekday = (parseDay(day).getUTCDay() + 6) % 7; // Monday = 0
  return addDays(day, -weekday);
}

export function startOfMonth(day: string): string {
  return `${day.slice(0, 7)}-01`;
}

export function endOfMonth(day: string): string {
  return addDays(addMonths(startOfMonth(day), 1), -1);
}

export function startOfQuarter(day: string): string {
  const month = Number(day.slice(5, 7));
  return `${day.slice(0, 4)}-${pad(Math.floor((month - 1) / 3) * 3 + 1)}-01`;
}

/** The wall clock in `tz` at `now`. */
export function zonedNow(tz: string, now: Date | number = new Date()): TZDate {
  return new TZDate(typeof now === "number" ? now : now.getTime(), tz);
}

/** Today's date in the company: "2026-10-20". */
export function todayIn(tz: string, now: Date | number = new Date()): string {
  const zoned = zonedNow(tz, now);
  return `${zoned.getFullYear()}-${pad(zoned.getMonth() + 1)}-${pad(zoned.getDate())}`;
}

/** The company-local day an instant falls on. */
export function zonedDay(iso: string | Date, tz: string): string {
  return todayIn(tz, typeof iso === "string" ? new Date(iso) : iso);
}

/** Range for a preset, matching the backend's `apps.reports.periods.parse_range`. */
export function presetRange(preset: DatePreset, tz: string, now: Date | number = new Date()): Range {
  const today = todayIn(tz, now);
  switch (preset) {
    case "today":
      return { from: today, to: today };
    case "yesterday": {
      const day = addDays(today, -1);
      return { from: day, to: day };
    }
    case "week":
      return { from: startOfWeek(today), to: today };
    case "last_week": {
      const monday = addDays(startOfWeek(today), -7);
      return { from: monday, to: addDays(monday, 6) };
    }
    case "month":
      return { from: startOfMonth(today), to: today };
    case "last_month": {
      const first = addMonths(startOfMonth(today), -1);
      return { from: first, to: endOfMonth(first) };
    }
    case "last_30":
      return { from: addDays(today, -29), to: today };
    case "quarter":
      return { from: startOfQuarter(today), to: today };
    case "year":
      return { from: `${today.slice(0, 4)}-01-01`, to: today };
  }
}

/** Shifts a range by whole months, keeping "to the end of the month" at the end of the month. */
function shiftMonths(range: Range, months: number): Range {
  const from = addMonths(range.from, months);
  const toEnd = range.to === endOfMonth(range.to);
  const shifted = addMonths(range.to, months);
  return { from, to: toEnd ? endOfMonth(shifted) : shifted };
}

/**
 * The comparison period. "year": the same dates a year earlier. "prev": the period right before,
 * shifted by whole months for month, quarter and year presets (October 1–20 compares with
 * September 1–20, not with the 20 days before), otherwise by the range's own length.
 */
export function compareRange(range: Range, mode: CompareMode, preset?: DatePreset): Range | null {
  if (mode === "none") return null;
  if (mode === "year") return shiftMonths(range, -12);
  if (preset === "quarter") return shiftMonths(range, -3);
  if (preset === "year") return shiftMonths(range, -12);
  const monthAligned = range.from === startOfMonth(range.from) && range.from.slice(0, 7) === range.to.slice(0, 7);
  if (preset === "month" || preset === "last_month" || (preset === undefined && monthAligned)) return shiftMonths(range, -1);
  const length = diffDays(range.from, range.to) + 1;
  const to = addDays(range.from, -1);
  return { from: addDays(to, -(length - 1)), to };
}

export type DayStyle = "short" | "medium" | "long" | "weekday" | "weekdayShort" | "monthYear";

const DAY_FORMATS: Record<DayStyle, Intl.DateTimeFormatOptions> = {
  short: { day: "numeric", month: "short" },
  medium: { day: "numeric", month: "short", year: "numeric" },
  long: { day: "numeric", month: "long", year: "numeric" },
  weekday: { weekday: "long", day: "numeric", month: "long" },
  weekdayShort: { weekday: "short", day: "numeric", month: "short" },
  monthYear: { month: "long", year: "numeric" },
};

/*
 * Uzbek is written by hand: browsers and Telegram webviews often ship without Uzbek ICU data
 * (Chromium prints "M10 20, Tue"), and CLDR's ʻ would differ from the product's o‘ anyway.
 */
const UZ_MONTHS = ["yanvar", "fevral", "mart", "aprel", "may", "iyun", "iyul", "avgust", "sentabr", "oktabr", "noyabr", "dekabr"];
const UZ_MONTHS_SHORT = ["yan", "fev", "mar", "apr", "may", "iyn", "iyl", "avg", "sen", "okt", "noy", "dek"];
const UZ_WEEKDAYS = ["yakshanba", "dushanba", "seshanba", "chorshanba", "payshanba", "juma", "shanba"];
const UZ_WEEKDAYS_SHORT = ["Ya", "Du", "Se", "Ch", "Pa", "Ju", "Sh"];

const capital = (text: string) => text.charAt(0).toUpperCase() + text.slice(1);

function formatUzbekDay(date: Date, style: DayStyle): string {
  const day = date.getUTCDate();
  const month = date.getUTCMonth();
  const year = date.getUTCFullYear();
  const weekday = date.getUTCDay();
  switch (style) {
    case "short":
      return `${day}-${UZ_MONTHS_SHORT[month]}`;
    case "medium":
      return `${day}-${UZ_MONTHS_SHORT[month]}, ${year}`;
    case "long":
      return `${day}-${UZ_MONTHS[month]}, ${year}`;
    case "weekday":
      return `${capital(UZ_WEEKDAYS[weekday]!)}, ${day}-${UZ_MONTHS[month]}`;
    case "weekdayShort":
      return `${UZ_WEEKDAYS_SHORT[weekday]}, ${day}-${UZ_MONTHS_SHORT[month]}`;
    case "monthYear":
      return `${capital(UZ_MONTHS[month]!)}, ${year}`;
  }
}

const formatters = new Map<string, Intl.DateTimeFormat>();

function formatter(lang: Language, options: Intl.DateTimeFormatOptions, timeZone: string): Intl.DateTimeFormat {
  const key = `${lang}|${timeZone}|${JSON.stringify(options)}`;
  let found = formatters.get(key);
  if (!found) {
    found = new Intl.DateTimeFormat(INTL_LOCALE[lang], { ...options, timeZone });
    formatters.set(key, found);
  }
  return found;
}

/** A company-local day: "20 Oct", "20 Oct 2026", "Tuesday, 20 October". */
export function formatDay(day: string, lang: Language, style: DayStyle = "medium"): string {
  if (lang === "uz") return formatUzbekDay(parseDay(day), style);
  return formatter(lang, DAY_FORMATS[style], "UTC").format(parseDay(day));
}

export type InstantStyle = "time" | "date" | "datetime" | "short";

/** An instant in the company zone: "14:05", "20 Oct 2026", "20 Oct 2026, 14:05", "20 Oct, 14:05". */
export function formatInstant(iso: string | Date, tz: string, lang: Language, style: InstantStyle = "datetime"): string {
  const date = typeof iso === "string" ? new Date(iso) : iso;
  if (Number.isNaN(date.getTime())) return "—";
  const time = formatter(lang, { hour: "2-digit", minute: "2-digit", hourCycle: "h23" }, tz).format(date);
  if (style === "time") return time;
  const day = zonedDay(date, tz);
  const dayText = formatDay(day, lang, style === "short" ? "short" : "medium");
  return style === "date" ? dayText : `${dayText}, ${time}`;
}

/** "1–20 Oct 2026", "28 Sep – 4 Oct 2026", "20 Oct 2026". */
export function formatRange(range: Range, lang: Language): string {
  if (range.from === range.to) return formatDay(range.from, lang, "medium");
  const sameYear = range.from.slice(0, 4) === range.to.slice(0, 4);
  const sameMonth = sameYear && range.from.slice(0, 7) === range.to.slice(0, 7);
  if (sameMonth && lang !== "uz") {
    return `${Number(range.from.slice(8))}–${formatDay(range.to, lang, "medium")}`;
  }
  const start = formatDay(range.from, lang, sameYear ? "short" : "medium");
  return `${start} – ${formatDay(range.to, lang, "medium")}`;
}

const RELATIVE: Record<Language, { now: string; minAgo: string; hourAgo: string; inMin: string; inHour: string; yesterday: string; tomorrow: string }> = {
  uz: {
    now: "hozirgina",
    minAgo: "{n} daqiqa oldin",
    hourAgo: "{n} soat oldin",
    inMin: "{n} daqiqadan keyin",
    inHour: "{n} soatdan keyin",
    yesterday: "kecha, {time}",
    tomorrow: "ertaga, {time}",
  },
  ru: {
    now: "только что",
    minAgo: "{n} мин назад",
    hourAgo: "{n} ч назад",
    inMin: "через {n} мин",
    inHour: "через {n} ч",
    yesterday: "вчера, {time}",
    tomorrow: "завтра, {time}",
  },
  en: {
    now: "just now",
    minAgo: "{n} min ago",
    hourAgo: "{n} h ago",
    inMin: "in {n} min",
    inHour: "in {n} h",
    yesterday: "yesterday, {time}",
    tomorrow: "tomorrow, {time}",
  },
};

/**
 * "just now", "5 min ago", "3 h ago", "yesterday, 14:05", then the date ("12 Oct", or "12 Oct 2025"
 * in another year). Future instants read "in 5 min", "tomorrow, 09:00".
 */
export function formatRelative(iso: string | Date, tz: string, lang: Language, now: Date | number = Date.now()): string {
  const date = typeof iso === "string" ? new Date(iso) : iso;
  if (Number.isNaN(date.getTime())) return "—";
  const nowMs = typeof now === "number" ? now : now.getTime();
  const words = RELATIVE[lang];
  const diff = nowMs - date.getTime();
  const abs = Math.abs(diff);
  const fill = (template: string, n: number | string) => template.replace("{n}", String(n)).replace("{time}", String(n));
  if (abs < 45_000) return words.now;
  const today = todayIn(tz, nowMs);
  const day = zonedDay(date, tz);
  if (abs < 3_600_000) return fill(diff > 0 ? words.minAgo : words.inMin, Math.max(1, Math.round(abs / 60_000)));
  if (day === today && abs < 12 * 3_600_000) return fill(diff > 0 ? words.hourAgo : words.inHour, Math.round(abs / 3_600_000));
  const time = formatInstant(date, tz, lang, "time");
  if (day === today) return time;
  if (day === addDays(today, -1)) return fill(words.yesterday, time);
  if (day === addDays(today, 1)) return fill(words.tomorrow, time);
  return formatDay(day, lang, day.slice(0, 4) === today.slice(0, 4) ? "short" : "medium");
}

/** Part of the day in the company, for greetings. */
export function dayPart(tz: string, now: Date | number = new Date()): "morning" | "afternoon" | "evening" | "night" {
  const hour = zonedNow(tz, now).getHours();
  if (hour >= 5 && hour < 12) return "morning";
  if (hour >= 12 && hour < 17) return "afternoon";
  if (hour >= 17 && hour < 23) return "evening";
  return "night";
}
