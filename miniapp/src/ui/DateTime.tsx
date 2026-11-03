import { CalendarDays, ChevronLeft, ChevronRight, Clock } from "lucide-react";
import { useId, useLayoutEffect, useRef, useState, type KeyboardEvent } from "react";

import { useI18n } from "../i18n";
import { addDays, capitalise, dayKey, dayMonth, dayMonthLong, dayMonthYear, monthYear, weekdayLong, weekdayShort, type DayKey } from "../lib/time";
import { haptic } from "../telegram";
import { cx } from "./cx";
import { useFieldControl } from "./Field";

/**
 * The app's own time and day pickers. A native `<input type="time|date">` follows the phone, not
 * the app: on a phone set to English it shows "04:00 AM" in a 24-hour country, and its calendar
 * speaks the phone's language. These always show 24-hour times and the app's month and weekday
 * names. The time is two native lists (hours 00–23, minutes), so the phone's own wheel or list
 * opens with our numbers; the day opens a month calendar under the field.
 */

const TIME = /^([01]\d|2[0-3]):([0-5]\d)(?::[0-5]\d)?$/;
const pad = (value: number) => String(value).padStart(2, "0");

/** "18:30" → ["18", "30"]; an empty or malformed value → ["", ""]. */
export function splitTime(value: string): [string, string] {
  const match = TIME.exec(value);
  return match ? [match[1], match[2]] : ["", ""];
}

export const HOURS: readonly string[] = Array.from({ length: 24 }, (_, hour) => pad(hour));

/** Every `step` minutes from :00, plus the value's own minute when it falls between them. */
export function minuteOptions(step: number, current: string): string[] {
  const minutes = new Set<number>();
  for (let minute = 0; minute < 60; minute += Math.max(1, step)) minutes.add(minute);
  if (/^[0-5]\d$/.test(current)) minutes.add(Number(current));
  return [...minutes].sort((a, b) => a - b).map(pad);
}

/** A 24-hour time ("HH:MM") as two lists: hours and minutes. `optional` allows no time (""). */
export function TimeInput({
  value,
  onChange,
  label,
  step = 5,
  optional = false,
  id,
  invalid,
  className,
}: {
  value: string;
  onChange: (value: string) => void;
  /** What the time is ("Time", "Arrived"): names the pair for screen readers. */
  label: string;
  /** Minutes between choices; the current minute is always offered. */
  step?: number;
  optional?: boolean;
  id?: string;
  invalid?: boolean;
  className?: string;
}) {
  const { t } = useI18n();
  const control = useFieldControl({ id, invalid });
  const [hour, minute] = splitTime(value);
  const pick = (next: string) => {
    haptic.select();
    onChange(next);
  };
  return (
    <div className={cx("input ui-time num", className)} role="group" aria-label={label}>
      <span className="ui-time-part ui-time-part--hour">
        <Clock className="ui-time-icon" size={18} strokeWidth={2.4} aria-hidden />
        <span className="ui-time-text" aria-hidden>
          {hour || "––"}
        </span>
        <select
          {...control}
          aria-label={t("ui.time.hour")}
          value={hour}
          onChange={(event) => {
            const next = event.target.value;
            pick(next ? `${next}:${minute || "00"}` : "");
          }}
        >
          {(optional || !hour) && <option value="">––</option>}
          {HOURS.map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>
      </span>
      <span className="ui-time-colon" aria-hidden>
        :
      </span>
      <span className="ui-time-part ui-time-part--minute">
        <span className="ui-time-text" aria-hidden>
          {minute || "––"}
        </span>
        <select aria-label={t("ui.time.minute")} value={minute} disabled={!hour} onChange={(event) => pick(`${hour}:${event.target.value}`)}>
          {!minute && <option value="">––</option>}
          {minuteOptions(step, minute).map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>
      </span>
    </div>
  );
}

// — the day —

export type MonthKey = string; // YYYY-MM

export const monthOf = (day: DayKey): MonthKey => day.slice(0, 7);

export function shiftMonth(month: MonthKey, by: number): MonthKey {
  const [year, number] = month.split("-").map(Number);
  return new Date(Date.UTC(year, number - 1 + by, 1)).toISOString().slice(0, 7);
}

/** Monday 0 … Sunday 6: weeks start on Monday in Uzbekistan. */
const weekdayIndex = (day: DayKey) => (new Date(`${day}T12:00:00Z`).getUTCDay() + 6) % 7;

/** The month's days in weeks from Monday; null fills the first and last week. */
export function monthWeeks(month: MonthKey): (DayKey | null)[][] {
  const first = `${month}-01`;
  const [year, number] = month.split("-").map(Number);
  const length = new Date(Date.UTC(year, number, 0)).getUTCDate();
  const cells: (DayKey | null)[] = [
    ...Array<null>(weekdayIndex(first)).fill(null),
    ...Array.from({ length }, (_, index) => addDays(first, index)),
  ];
  while (cells.length % 7) cells.push(null);
  return Array.from({ length: cells.length / 7 }, (_, week) => cells.slice(week * 7, week * 7 + 7));
}

export function clampDay(day: DayKey, min?: DayKey, max?: DayKey): DayKey {
  if (min && day < min) return min;
  if (max && day > max) return max;
  return day;
}

/** The same day of another month, or that month's last day ("31 Jan" + 1 → "28 Feb"). */
function sameDayIn(day: DayKey, by: number): DayKey {
  const month = shiftMonth(monthOf(day), by);
  const [year, number] = month.split("-").map(Number);
  const last = new Date(Date.UTC(year, number, 0)).getUTCDate();
  return `${month}-${pad(Math.min(Number(day.slice(8)), last))}`;
}

/** Where a key moves the focused day in the calendar (the grid pattern's keys). */
export function moveDay(day: DayKey, key: string): DayKey | null {
  switch (key) {
    case "ArrowLeft":
      return addDays(day, -1);
    case "ArrowRight":
      return addDays(day, 1);
    case "ArrowUp":
      return addDays(day, -7);
    case "ArrowDown":
      return addDays(day, 7);
    case "Home":
      return addDays(day, -weekdayIndex(day));
    case "End":
      return addDays(day, 6 - weekdayIndex(day));
    case "PageUp":
      return sameDayIn(day, -1);
    case "PageDown":
      return sameDayIn(day, 1);
    default:
      return null;
  }
}

// A known Monday-to-Sunday week, for the calendar's column heads.
const WEEK = Array.from({ length: 7 }, (_, index) => addDays("2024-01-01", index));

/**
 * A day ("YYYY-MM-DD"): a field showing "Sesh, 3-noy" that opens a month calendar under it.
 * Inside a two-column `.plus-when` row the calendar takes the whole row under both fields.
 */
export function DateInput({
  value,
  onChange,
  label,
  min,
  max,
  today,
  long = false,
  defaultOpen = false,
  id,
  className,
}: {
  value: DayKey;
  onChange: (value: DayKey) => void;
  /** What the day is ("Day", "From"): named with the date for screen readers. */
  label: string;
  min?: DayKey;
  max?: DayKey;
  /** Marked in the calendar (the company's today). */
  today?: DayKey;
  /** "Seshanba, 3-noyabr" where the field has the whole line. */
  long?: boolean;
  /** Open the calendar as the field appears (the person just asked for another day). */
  defaultOpen?: boolean;
  id?: string;
  className?: string;
}) {
  const { locale } = useI18n();
  const control = useFieldControl({ id });
  const panelId = useId();
  const trigger = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(defaultOpen);
  // A day in another year says its year ("a year from today" must not read as today).
  const otherYear = Boolean(value) && value.slice(0, 4) !== (today ?? dayKey(new Date(), "UTC")).slice(0, 4);
  const dayText = (short: boolean) =>
    otherYear ? dayMonthYear(value, "UTC", locale) : short ? dayMonth(value, "UTC", locale) : dayMonthLong(value, "UTC", locale);
  const shown = value ? capitalise(long ? `${weekdayLong(value, "UTC", locale)}, ${dayText(false)}` : `${weekdayShort(value, "UTC", locale)}, ${dayText(true)}`) : "";
  const spoken = value ? `${label}: ${weekdayLong(value, "UTC", locale)}, ${dayText(false)}` : label;
  const close = () => {
    setOpen(false);
    trigger.current?.focus({ preventScroll: true });
  };
  return (
    <>
      <button
        {...control}
        ref={trigger}
        type="button"
        className={cx("input ui-date num", className)}
        aria-label={spoken}
        aria-expanded={open}
        aria-controls={open ? panelId : undefined}
        onClick={() => {
          haptic.select();
          setOpen(!open);
        }}
      >
        <CalendarDays className="ui-date-icon" size={18} strokeWidth={2.4} aria-hidden />
        <span className="ui-date-text">{shown}</span>
      </button>
      {open && (
        <Calendar
          id={panelId}
          value={value}
          min={min}
          max={max}
          today={today}
          onPick={(day) => {
            haptic.select();
            onChange(day);
            close();
          }}
          onClose={close}
        />
      )}
    </>
  );
}

function Calendar({
  id,
  value,
  min,
  max,
  today,
  onPick,
  onClose,
}: {
  id: string;
  value: DayKey;
  min?: DayKey;
  max?: DayKey;
  today?: DayKey;
  onPick: (day: DayKey) => void;
  onClose: () => void;
}) {
  const { t, locale } = useI18n();
  const headingId = useId();
  const panel = useRef<HTMLDivElement>(null);
  const [focused, setFocused] = useState(() => clampDay(value || today || WEEK[0], min, max));
  const [month, setMonth] = useState(() => monthOf(focused));
  // Focus follows the keys; on opening it goes to the chosen day (for keyboards and screen readers).
  const moveFocus = useRef(true);
  const inRange = (day: DayKey) => (!min || day >= min) && (!max || day <= max);
  const days = monthWeeks(month).flat();
  // The one day Tab reaches: the focused day while its month shows, else the month's first open day.
  const tabbable = monthOf(focused) === month ? focused : (days.find((day): day is DayKey => day !== null && inRange(day)) ?? null);

  useLayoutEffect(() => {
    if (!moveFocus.current) return;
    moveFocus.current = false;
    panel.current?.querySelector<HTMLButtonElement>(`[data-day="${focused}"]`)?.focus({ preventScroll: true });
  });
  // Opened near the bottom of a sheet: bring the whole calendar into view.
  useLayoutEffect(() => {
    panel.current?.scrollIntoView?.({ block: "nearest", behavior: "smooth" });
  }, []);

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape") {
      // Closes the calendar, not the sheet around it (the sheet skips handled keys).
      event.preventDefault();
      onClose();
      return;
    }
    if (!(event.target instanceof HTMLElement) || !event.target.dataset.day) return;
    const next = moveDay(focused, event.key);
    if (!next) return;
    event.preventDefault();
    const day = clampDay(next, min, max);
    moveFocus.current = true;
    setFocused(day);
    setMonth(monthOf(day));
  };
  const canPrev = !min || shiftMonth(month, -1) >= monthOf(min);
  const canNext = !max || shiftMonth(month, 1) <= monthOf(max);
  const turn = (by: number) => {
    haptic.select();
    setMonth(shiftMonth(month, by));
  };

  return (
    <div ref={panel} id={id} className="ui-cal fade-in" onKeyDown={onKeyDown}>
      <div className="ui-cal-head">
        <button type="button" className="ui-cal-nav" aria-label={t("ui.date.prevMonth")} disabled={!canPrev} onClick={() => turn(-1)}>
          <ChevronLeft size={20} strokeWidth={2.6} aria-hidden />
        </button>
        <div id={headingId} className="ui-cal-title" aria-live="polite">
          {monthYear(month, locale)}
        </div>
        <button type="button" className="ui-cal-nav" aria-label={t("ui.date.nextMonth")} disabled={!canNext} onClick={() => turn(1)}>
          <ChevronRight size={20} strokeWidth={2.6} aria-hidden />
        </button>
      </div>
      <table className="ui-cal-grid num" role="grid" aria-labelledby={headingId}>
        <thead>
          <tr>
            {WEEK.map((day) => (
              <th key={day} scope="col" abbr={capitalise(weekdayLong(day, "UTC", locale))}>
                {capitalise(weekdayShort(day, "UTC", locale))}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {monthWeeks(month).map((week) => (
            <tr key={week.find(Boolean) ?? month}>
              {week.map((day, column) => (
                <td key={day ?? `${month}-${column}`}>
                  {day && (
                    <button
                      type="button"
                      className="ui-cal-day"
                      data-day={day}
                      tabIndex={day === tabbable ? 0 : -1}
                      disabled={!inRange(day)}
                      aria-pressed={day === value}
                      aria-current={day === today ? "date" : undefined}
                      aria-label={capitalise(`${weekdayLong(day, "UTC", locale)}, ${dayMonthLong(day, "UTC", locale)}`)}
                      onClick={() => onPick(day)}
                      onFocus={() => setFocused(day)}
                    >
                      {Number(day.slice(8))}
                    </button>
                  )}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
