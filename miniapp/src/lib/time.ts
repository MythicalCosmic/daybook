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

/** Day, month (0–11) and weekday (0 = Sunday) of a moment in `timeZone`. */
function calendar(moment: string | Date, timeZone: string) {
  const parts = formatter("en-US", { timeZone, day: "numeric", month: "numeric", weekday: "short" })
    .formatToParts(new Date(moment));
  const part = (type: string) => parts.find((item) => item.type === type)?.value ?? "";
  return {
    day: Number(part("day")),
    month: Number(part("month")) - 1,
    weekday: EN_WEEKDAYS.indexOf(part("weekday")),
  };
}

export function dayKey(moment: Date | string, timeZone: string): DayKey {
  return formatter("en-CA", { timeZone, year: "numeric", month: "2-digit", day: "2-digit" }).format(
    new Date(moment),
  );
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

export function weekdayShort(moment: string | Date, timeZone: string, locale: string): string {
  if (isUzbek(locale)) return UZ_WEEKDAYS_SHORT[calendar(moment, timeZone).weekday];
  return formatter(locale, { timeZone, weekday: "short" }).format(new Date(moment));
}

export function weekdayLong(moment: string | Date, timeZone: string, locale: string): string {
  if (isUzbek(locale)) return UZ_WEEKDAYS[calendar(moment, timeZone).weekday];
  return formatter(locale, { timeZone, weekday: "long" }).format(new Date(moment));
}

export function dayMonth(moment: string | Date, timeZone: string, locale: string): string {
  if (isUzbek(locale)) {
    const { day, month } = calendar(moment, timeZone);
    return `${day}-${UZ_MONTHS_SHORT[month]}`;
  }
  return formatter(locale, { timeZone, day: "numeric", month: "short" }).format(new Date(moment));
}

export function longDate(moment: Date, timeZone: string, locale: string): string {
  if (isUzbek(locale)) {
    const { day, month, weekday } = calendar(moment, timeZone);
    return `${UZ_WEEKDAYS[weekday]}, ${day}-${UZ_MONTHS[month]}`;
  }
  return formatter(locale, { timeZone, weekday: "long", day: "numeric", month: "long" }).format(
    moment,
  );
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
