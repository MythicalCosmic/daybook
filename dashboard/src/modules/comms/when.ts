/**
 * Moments the composer picks as a company-local day and time ("2026-10-24" + "09:00"), turned into
 * the ISO instants the API takes, and back.
 */
import { TZDate } from "@date-fns/tz";

import { addDays, todayIn, zonedDay } from "@/lib/dates";

/** "2026-10-24" + "09:00" in `tz` → "2026-10-24T04:00:00.000Z". */
export function zonedIso(day: string, time: string, tz: string): string {
  const [y, m, d] = day.split("-").map(Number) as [number, number, number];
  const [hh, mm] = time.split(":").map(Number) as [number, number];
  return new Date(new TZDate(y, m - 1, d, hh, mm, 0, tz).getTime()).toISOString();
}

/** An ISO instant as the company-local day and "HH:MM". */
export function splitIso(iso: string, tz: string): { day: string; time: string } {
  const zoned = new TZDate(new Date(iso).getTime(), tz);
  const pad = (n: number) => String(n).padStart(2, "0");
  return { day: zonedDay(iso, tz), time: `${pad(zoned.getHours())}:${pad(zoned.getMinutes())}` };
}

/** The next sensible send time: tomorrow at 09:00 in the company. */
export function nextMorning(tz: string): { day: string; time: string } {
  return { day: addDays(todayIn(tz), 1), time: "09:00" };
}
