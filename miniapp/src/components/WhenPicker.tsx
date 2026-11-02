import { useState } from "react";

import { useI18n } from "../i18n";
import { addDays, clock, dayKey, hourIn, zonedInstant, type DayKey } from "../lib/time";
import { haptic } from "../telegram";
import { DateInput, TimeInput } from "../ui";

/**
 * "When" for a new task, as the (+) sheet asks it: Today, Tomorrow, Other day or No deadline,
 * then the day and the time. The AI review uses the same controls for each task it heard.
 */
export type WhenChoice = "today" | "tomorrow" | "date" | "none";
export type WhenValue = { when: WhenChoice; date: DayKey; time: string };

const CHOICES: readonly WhenChoice[] = ["today", "tomorrow", "date", "none"];
const LABEL = { today: "day.today", tomorrow: "day.tomorrow", date: "add.otherDay", none: "add.noDeadline" } as const;

/** A new task's default: the next full hour today, or tomorrow morning when the day is nearly over. */
export function defaultWhen(now: Date, timeZone: string): WhenValue {
  const hour = hourIn(now, timeZone);
  const date = addDays(dayKey(now, timeZone), 2);
  return hour < 22 ? { when: "today", time: `${String(hour + 1).padStart(2, "0")}:00`, date } : { when: "tomorrow", time: "09:00", date };
}

/** A deadline as the controls show it: today, tomorrow or another day at its time; none without one. */
export function whenOf(iso: string | null, now: Date, timeZone: string): WhenValue {
  if (!iso) return { ...defaultWhen(now, timeZone), when: "none" };
  const today = dayKey(now, timeZone);
  const day = dayKey(iso, timeZone);
  const time = clock(iso, timeZone, "en-GB");
  if (day === today) return { when: "today", time, date: addDays(today, 2) };
  if (day === addDays(today, 1)) return { when: "tomorrow", time, date: addDays(today, 2) };
  return { when: "date", time, date: day };
}

/**
 * The moment a When value means. A time today that has already passed rolls to tomorrow, and
 * `rolled` says so (as the bot does); no deadline, or another day not picked yet, is null.
 */
export function whenDue(value: WhenValue, now: Date, timeZone: string): { due: Date | null; rolled: boolean } {
  const today = dayKey(now, timeZone);
  const day = value.when === "today" ? today : value.when === "tomorrow" ? addDays(today, 1) : value.when === "date" ? value.date : null;
  if (!day || !value.time) return { due: null, rolled: false };
  const instant = zonedInstant(day, value.time, timeZone);
  const rolled = value.when === "today" && instant <= now;
  return { due: rolled ? zonedInstant(addDays(today, 1), value.time, timeZone) : instant, rolled };
}

/** The four choices, the day and time boxes under them, and the note when today's time has passed. */
export function WhenPicker({
  value,
  onChange,
  now,
  timeZone,
  labelledBy,
}: {
  value: WhenValue;
  onChange: (value: WhenValue) => void;
  now: Date;
  timeZone: string;
  /** The id of the visible label ("When") that names the choices. */
  labelledBy?: string;
}) {
  const { t, locale } = useI18n();
  const today = dayKey(now, timeZone);
  const { due, rolled } = whenDue(value, now, timeZone);
  const set = (patch: Partial<WhenValue>) => onChange({ ...value, ...patch });
  // "Other day" tapped: its calendar opens at once (a value that was already another day doesn't).
  const [askedForDay, setAskedForDay] = useState(false);
  return (
    <>
      <div className="ui-chips plus-days" role="group" aria-labelledby={labelledBy}>
        {CHOICES.map((option) => (
          <button
            key={option}
            type="button"
            className="ui-chip"
            aria-pressed={value.when === option}
            onClick={() => {
              haptic.select();
              setAskedForDay(option === "date" && value.when !== "date");
              set({ when: option });
            }}
          >
            <span>{t(LABEL[option])}</span>
          </button>
        ))}
      </div>
      {value.when !== "none" && (
        <div className="plus-when">
          {value.when === "date" && (
            <DateInput
              label={t("add.date")}
              min={addDays(today, 1)}
              today={today}
              value={value.date}
              defaultOpen={askedForDay}
              onChange={(date) => set({ date })}
            />
          )}
          <TimeInput label={t("add.time")} value={value.time} onChange={(time) => set({ time: time || value.time })} />
        </div>
      )}
      {rolled && due && <span className="field-note num">{t("add.rolled", { time: clock(due, timeZone, locale) })}</span>}
    </>
  );
}
