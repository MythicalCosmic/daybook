/**
 * Moments the composer picks as a company-local day and time ("2026-10-24" + "09:00"), turned into
 * the ISO instants the API takes, and back.
 */
import { TZDate } from "@date-fns/tz";

import { addDays, todayIn, zonedDay } from "@/lib/dates";

// One helper for every module (lib/dates); the compose pages import it from here.
export { zonedIso } from "@/lib/dates";

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
