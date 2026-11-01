/**
 * The (+) sheet's "When", shared with the AI review: the default for a new task, a deadline shown
 * as the controls show it, and a past time today rolling to tomorrow.
 */
import { describe, expect, it } from "vitest";

import { defaultWhen, whenDue, whenOf } from "./WhenPicker";

const TZ = "Asia/Tashkent";
const at = (iso: string) => new Date(iso);

describe("When", () => {
  it("defaults to the next full hour today, or tomorrow morning late in the day", () => {
    expect(defaultWhen(at("2026-11-02T09:20:00+05:00"), TZ)).toEqual({ when: "today", time: "10:00", date: "2026-11-04" });
    expect(defaultWhen(at("2026-11-02T22:10:00+05:00"), TZ)).toEqual({ when: "tomorrow", time: "09:00", date: "2026-11-04" });
  });

  it("shows a deadline as today, tomorrow or another day at its time, and none without one", () => {
    const now = at("2026-11-02T09:00:00+05:00");
    expect(whenOf("2026-11-02T18:00:00+05:00", now, TZ)).toMatchObject({ when: "today", time: "18:00" });
    expect(whenOf("2026-11-03T10:00:00+05:00", now, TZ)).toMatchObject({ when: "tomorrow", time: "10:00" });
    expect(whenOf("2026-11-06T08:30:00+05:00", now, TZ)).toEqual({ when: "date", time: "08:30", date: "2026-11-06" });
    expect(whenOf(null, now, TZ).when).toBe("none");
  });

  it("rolls a time today that has passed to tomorrow, and says so", () => {
    const now = at("2026-11-02T15:00:00+05:00");
    expect(whenDue({ when: "today", time: "18:00", date: "" }, now, TZ)).toEqual({ due: at("2026-11-02T18:00:00+05:00"), rolled: false });
    expect(whenDue({ when: "today", time: "09:00", date: "" }, now, TZ)).toEqual({ due: at("2026-11-03T09:00:00+05:00"), rolled: true });
    expect(whenDue({ when: "date", time: "09:00", date: "2026-11-02" }, now, TZ)).toEqual({ due: at("2026-11-02T09:00:00+05:00"), rolled: false });
    expect(whenDue({ when: "date", time: "09:00", date: "" }, now, TZ)).toEqual({ due: null, rolled: false });
    expect(whenDue({ when: "none", time: "09:00", date: "2026-11-05" }, now, TZ)).toEqual({ due: null, rolled: false });
  });
});
