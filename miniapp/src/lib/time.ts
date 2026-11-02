/** Dates and times shown in the company's timezone, whatever the phone is set to. */

export type DayKey = string; // YYYY-MM-DD

const cache = new Map<string, Intl.DateTimeFormat>();

function formatter(locale: string, options: Intl.DateTimeFormatOptions): Intl.DateTimeFormat {
  const key = locale + JSON.stringify(options);
  let format = cache.get(key);
  if (!format) {
    format = new Intl.DateTimeFormat(locale, options);
    cache.set(key, format);
  }
  return format;
}

// Some browsers ship without Uzbek calendar names (Chromium prints "M10 20, Tue"), so Uzbek
// month and weekday names are spelled out here, in the forms ICU would use.
const UZ_MONTHS = ["yanvar", "fevral", "mart", "aprel", "may", "iyun", "iyul", "avgust", "sentabr", "oktabr", "noyabr", "dekabr"];
const UZ_MONTHS_SHORT = ["yan", "fev", "mar", "apr", "may", "iyn", "iyl", "avg", "sen", "okt", "noy", "dek"];
const UZ_WEEKDAYS = ["yakshanba", "dushanba", "seshanba", "chorshanba", "payshanba", "juma", "shanba"];
const UZ_WEEKDAYS_SHORT = ["Yak", "Dush", "Sesh", "Chor", "Pay", "Jum", "Shan"];
const EN_WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

const isUzbek = (locale: string) => locale.startsWith("uz");

const DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/;

/**
 * The instant to format and the zone to read it in. A calendar date without a time ("2026-11-02",
 * a holiday, a shift's day, a report's range) is that day everywhere: it's read at noon UTC, in
 * UTC, so no zone moves it to the day before or after (a bare "2026-11-02" parses as UTC
 * midnight, the evening before west of Greenwich).
 */
function at(moment: string | Date, timeZone: string): [Date, string] {
  if (typeof moment === "string" && DATE_ONLY.test(moment)) return [new Date(`${moment}T12:00:00Z`), "UTC"];
  return [new Date(moment), timeZone];
}

/** Day, month (0–11) and weekday (0 = Sunday) of a moment in `timeZone`. */
function calendar(moment: string | Date, timeZone: string) {
  const [instant, zone] = at(moment, timeZone);
  const parts = formatter("en-US", { timeZone: zone, day: "numeric", month: "numeric", weekday: "short" }).formatToParts(instant);
  const part = (type: string) => parts.find((item) => item.type === type)?.value ?? "";
  return {
    day: Number(part("day")),
    month: Number(part("month")) - 1,
    weekday: EN_WEEKDAYS.indexOf(part("weekday")),
  };
}

export function dayKey(moment: Date | string, timeZone: string): DayKey {
  const [instant, zone] = at(moment, timeZone);
  return formatter("en-CA", { timeZone: zone, year: "numeric", month: "2-digit", day: "2-digit" }).format(instant);
}

export function addDays(key: DayKey, days: number): DayKey {
  const [year, month, day] = key.split("-").map(Number);
  const date = new Date(Date.UTC(year, month - 1, day + days));
  return date.toISOString().slice(0, 10);
}

/** Whole days from today to the moment's day: 0 today, 1 tomorrow, -1 yesterday. */
export function daysFromToday(moment: string, now: Date, timeZone: string): number {
  const toUtc = (key: DayKey) => Date.parse(`${key}T00:00:00Z`);
  return Math.round((toUtc(dayKey(moment, timeZone)) - toUtc(dayKey(now, timeZone))) / 86_400_000);
}

export function clock(moment: string | Date, timeZone: string, locale: string): string {
  return formatter(locale, { timeZone, hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).format(
    new Date(moment),
  );
}

export function hourIn(now: Date, timeZone: string): number {
  return Number(formatter("en-GB", { timeZone, hour: "2-digit", hourCycle: "h23" }).format(now));
}

/** `moment` in `timeZone` (a calendar date: as that very day) with these fields, in `locale`. */
function format(moment: string | Date, timeZone: string, locale: string, options: Intl.DateTimeFormatOptions): string {
  const [instant, zone] = at(moment, timeZone);
  return formatter(locale, { timeZone: zone, ...options }).format(instant);
}

/** The functions below take a moment (ISO string or Date, read in `timeZone`) or a calendar date
 * ("2026-11-02", the same day in every zone). */
export function weekdayShort(moment: string | Date, timeZone: string, locale: string): string {
  if (isUzbek(locale)) return UZ_WEEKDAYS_SHORT[calendar(moment, timeZone).weekday];
  return format(moment, timeZone, locale, { weekday: "short" });
}

export function weekdayLong(moment: string | Date, timeZone: string, locale: string): string {
  if (isUzbek(locale)) return UZ_WEEKDAYS[calendar(moment, timeZone).weekday];
  return format(moment, timeZone, locale, { weekday: "long" });
}

export function dayMonth(moment: string | Date, timeZone: string, locale: string): string {
  if (isUzbek(locale)) {
    const { day, month } = calendar(moment, timeZone);
    return `${day}-${UZ_MONTHS_SHORT[month]}`;
  }
  return format(moment, timeZone, locale, { day: "numeric", month: "short" });
}

/** "26 October", "26 октября", "26-oktabr": a date inside a sentence, where a shortened month's dot
 * would run into the sentence's own ("до 26 окт.."). */
export function dayMonthLong(moment: string | Date, timeZone: string, locale: string): string {
  if (isUzbek(locale)) {
    const { day, month } = calendar(moment, timeZone);
    return `${day}-${UZ_MONTHS[month]}`;
  }
  return format(moment, timeZone, locale, { day: "numeric", month: "long" });
}

/**
 * A day with its year: "2027-yil 30-aprel" (as Uzbek documents write it), "30 апреля 2027 г.",
 * "30 April 2027". `sameYearAs` leaves the year out when it is that moment's year ("30-aprel").
 */
export function dayMonthYear(moment: string | Date, timeZone: string, locale: string, sameYearAs?: Date): string {
  const year = dayKey(moment, timeZone).slice(0, 4);
  if (sameYearAs && dayKey(sameYearAs, timeZone).slice(0, 4) === year) return dayMonthLong(moment, timeZone, locale);
  if (isUzbek(locale)) return `${year}-yil ${dayMonthLong(moment, timeZone, locale)}`;
  return format(moment, timeZone, locale, { day: "numeric", month: "long", year: "numeric" });
}

/** "Yakshanba, 25-oktabr", "Воскресенье, 25 октября": a date that starts a line, so capitalised
 * (inside a sentence Uzbek and Russian weekdays are lowercase). */
export function longDate(moment: Date, timeZone: string, locale: string): string {
  if (isUzbek(locale)) {
    const { day, month, weekday } = calendar(moment, timeZone);
    return capitalise(`${UZ_WEEKDAYS[weekday]}, ${day}-${UZ_MONTHS[month]}`);
  }
  return capitalise(formatter(locale, { timeZone, weekday: "long", day: "numeric", month: "long" }).format(moment));
}

/** "Oktabr 2026", "Октябрь 2026 г.", "October 2026" for "2026-10" (Uzbek names spelled out). */
export function monthYear(month: string, locale: string): string {
  const [year, number] = month.split("-").map(Number);
  if (isUzbek(locale)) return capitalise(`${UZ_MONTHS[number - 1]} ${year}`);
  return capitalise(formatter(locale, { month: "long", year: "numeric", timeZone: "UTC" }).format(new Date(Date.UTC(year, number - 1, 15))));
}

/** Whole minutes from `from` to `to` (never negative). */
export function minutesBetween(from: string | Date, to: string | Date): number {
  return Math.max(0, Math.floor((new Date(to).getTime() - new Date(from).getTime()) / 60_000));
}

/** The first letter up: a date or weekday that starts a line. */
export function capitalise(text: string): string {
  return text.charAt(0).toLocaleUpperCase() + text.slice(1);
}

/** The instant a wall-clock time on a given day happens in `timeZone`. */
export function zonedInstant(key: DayKey, time: string, timeZone: string): Date {
  const [year, month, day] = key.split("-").map(Number);
  const [hour, minute] = time.split(":").map(Number);
  const wall = Date.UTC(year, month - 1, day, hour, minute);
  // Correct by the zone's offset at that moment; twice, in case the guess crossed a DST switch.
  let instant = wall - offset(wall, timeZone);
  instant = wall - offset(instant, timeZone);
  return new Date(instant);
}

function offset(instant: number, timeZone: string): number {
  const parts = formatter("en-US", {
    timeZone,
    hourCycle: "h23",
    year: "numeric",
    month: "numeric",
    day: "numeric",
    hour: "numeric",
    minute: "numeric",
    second: "numeric",
  }).formatToParts(new Date(instant));
  const get = (type: string) => Number(parts.find((part) => part.type === type)?.value);
  const asUtc = Date.UTC(get("year"), get("month") - 1, get("day"), get("hour"), get("minute"), get("second"));
  return asUtc - Math.floor(instant / 1000) * 1000;
}
