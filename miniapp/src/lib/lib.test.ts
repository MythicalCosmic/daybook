import { describe, expect, it } from "vitest";

import type { Task, TimeOff } from "../api/types";
import en from "../i18n/en";
import { translate } from "../i18n";
import ru from "../i18n/ru";
import uz from "../i18n/uz";
import { glyph, groupTasks, repeatLabel, rowMeta, rowRight, type ViewContext } from "./taskView";
import { nameInitials, tone } from "./team";
import { cancellable, current } from "./timeOff";
import {
  addDays,
  clock,
  dayKey,
  dayMonth,
  daysFromToday,
  longDate,
  weekdayShort,
  zonedInstant,
} from "./time";

const TASHKENT = "Asia/Tashkent";
// 19 Oct 2026, 09:41 in Tashkent (UTC+5).
const NOW = new Date("2026-10-19T04:41:00Z");

function ctx(lang: "en" | "ru" | "uz" = "en"): ViewContext {
  return {
    t: (key, vars) => translate(lang, key, vars),
    timeZone: TASHKENT,
    locale: { en: "en-GB", ru: "ru-RU", uz: "uz-Latn-UZ" }[lang],
    now: NOW,
  };
}

function task(overrides: Partial<Task> = {}): Task {
  return {
    id: 1,
    kind: "personal",
    title: "Order receipt rolls",
    description: "",
    status: "todo",
    priority: "normal",
    due_at: null,
    for_date: null,
    proof: "none",
    needs_confirmation: false,
    proof_text: "",
    proof_photo: null,
    proof_thumb: null,
    reward: null,
    assignee: { id: 1, name: "Ali Valiyev", position: null },
    created_by: { id: 1, name: "Ali Valiyev", position: null },
    confirmed_by: null,
    checklist: [],
    reminder: null,
    repeat_weekdays: null,
    started_at: null,
    completed_at: null,
    confirmed_at: null,
    is_overdue: false,
    actions: ["start", "complete"],
    created_at: "2026-10-18T10:00:00Z",
    ...overrides,
  };
}

describe("time", () => {
  it("reads the day in the company's timezone, not the phone's", () => {
    expect(dayKey("2026-10-18T20:30:00Z", TASHKENT)).toBe("2026-10-19");
    expect(clock("2026-10-19T04:41:00Z", TASHKENT, "en-GB")).toBe("09:41");
  });

  it("turns a wall-clock time into the right instant", () => {
    expect(zonedInstant("2026-10-19", "18:00", TASHKENT).toISOString()).toBe("2026-10-19T13:00:00.000Z");
    expect(zonedInstant("2026-03-29", "12:00", "Europe/Berlin").toISOString()).toBe("2026-03-29T10:00:00.000Z");
  });

  it("counts days from today", () => {
    expect(daysFromToday("2026-10-19T19:30:00Z", NOW, TASHKENT)).toBe(1); // 00:30 tomorrow, local
    expect(daysFromToday("2026-10-19T18:00:00Z", NOW, TASHKENT)).toBe(0); // 23:00 tonight, local
    expect(daysFromToday("2026-10-18T19:30:00Z", NOW, TASHKENT)).toBe(0); // 00:30 local
    expect(addDays("2026-12-31", 1)).toBe("2027-01-01");
  });
});

describe("task view", () => {
  it("marks late and sent-back work for attention", () => {
    expect(glyph(task({ due_at: "2026-10-19T04:00:00Z" }), NOW)).toBe("late");
    expect(glyph(task({ status: "returned" }), NOW)).toBe("late");
    expect(glyph(task({ status: "in_progress" }), NOW)).toBe("progress");
    expect(glyph(task({ status: "review" }), NOW)).toBe("review");
    expect(glyph(task({ status: "done" }), NOW)).toBe("done");
  });

  it("explains each task in one line", () => {
    expect(rowMeta(task({ due_at: "2026-10-19T04:16:00Z" }), ctx())).toBe("25 min late");
    expect(rowMeta(task({ kind: "assigned", created_by: { id: 2, name: "Anna K.", position: null } }), ctx())).toBe(
      "From Anna K.",
    );
    expect(rowMeta(task({ kind: "daily", repeat_weekdays: [0, 1, 2, 3, 4] }), ctx())).toBe("Weekdays");
    expect(
      rowMeta(task({ status: "done", completed_at: "2026-10-19T04:05:00Z" }), ctx()),
    ).toBe("Done at 09:05");
  });

  it("shows today's time or the day", () => {
    expect(rowRight(task({ due_at: "2026-10-19T09:00:00Z" }), ctx())).toBe("14:00");
    expect(rowRight(task({ due_at: "2026-10-20T09:00:00Z" }), ctx())).toBe("Tomorrow");
    expect(rowRight(task(), ctx())).toBe("");
  });

  it("dates a chip more than a week away instead of naming a weekday that could be either", () => {
    expect(rowRight(task({ due_at: "2026-10-18T09:00:00Z" }), ctx())).toBe("Yesterday");
    expect(rowRight(task({ due_at: "2026-10-15T09:00:00Z" }), ctx())).toBe("Thu");
    expect(rowRight(task({ due_at: "2026-10-05T09:00:00Z" }), ctx())).toBe("5 Oct");
    expect(rowRight(task({ due_at: "2026-10-05T09:00:00Z" }), ctx("ru"))).toBe("5 окт.");
  });

  it("names repeats in the person's language", () => {
    expect(repeatLabel([0, 1, 2, 3, 4, 5, 6], ctx())).toBe("Every day");
    expect(repeatLabel([0], ctx())).toBe("Every Monday");
    expect(repeatLabel([0, 1, 2, 3, 4], ctx("ru"))).toBe("По будням");
    expect(repeatLabel(null, ctx())).toBeNull();
  });

  it("groups the board the way the design does", () => {
    const groups = groupTasks(
      [
        task({ id: 1, status: "done" }),
        task({ id: 2, due_at: "2026-10-19T03:00:00Z" }),
        task({ id: 3 }),
        task({ id: 4, status: "review" }),
      ],
      NOW,
    );
    expect(groups.map((group) => [group.key, group.tasks.map((t) => t.id)])).toEqual([
      ["attention", [2]],
      ["todo", [3]],
      ["review", [4]],
      ["done", [1]],
    ]);
  });
});

describe("translations", () => {
  it("only translate keys that exist in English", () => {
    const known = new Set(Object.keys(en).map((key) => key.replace(/_(one|few|many|other)$/, "")));
    for (const dictionary of [ru, uz]) {
      for (const key of Object.keys(dictionary)) {
        expect(known.has(key.replace(/_(one|few|many|other)$/, ""))).toBe(true);
      }
    }
  });

  it("pick Russian plural forms", () => {
    expect(translate("ru", "home.late", { count: 1 })).toBe("1 задача просрочена");
    expect(translate("ru", "home.late", { count: 3 })).toBe("3 задачи просрочены");
    expect(translate("ru", "home.late", { count: 5 })).toBe("5 задач просрочено");
  });

  it("fall back to English for anything missing", () => {
    expect(translate("uz", "app.name")).toBe("Daybook");
  });
});

describe("team scores", () => {
  it("reads an on-time rate at a glance", () => {
    expect(tone({ on_time_percent: 100 })).toBe("good");
    expect(tone({ on_time_percent: 90 })).toBe("good");
    expect(tone({ on_time_percent: 89 })).toBe("fair");
    expect(tone({ on_time_percent: 70 })).toBe("fair");
    expect(tone({ on_time_percent: 69 })).toBe("poor");
    expect(tone({ on_time_percent: null })).toBe("none");
  });

  it("makes avatar initials from a name", () => {
    expect(nameInitials("Ali Valiyev")).toBe("AV");
    expect(nameInitials("  dilnoza  ")).toBe("D");
    expect(nameInitials("")).toBe("?");
  });
});

describe("Uzbek dates", () => {
  // 20 Oct 2026 23:30 UTC is already Wednesday the 21st in Tashkent.
  const moment = "2026-10-20T23:30:00Z";

  it("are spelled out whatever the browser knows", () => {
    expect(dayMonth(moment, "Asia/Tashkent", "uz-Latn-UZ")).toBe("21-okt");
    expect(longDate(new Date(moment), "Asia/Tashkent", "uz-Latn-UZ")).toBe("chorshanba, 21-oktabr");
    expect(weekdayShort(moment, "Asia/Tashkent", "uz-Latn-UZ")).toBe("Chor");
    expect(dayMonth(moment, "UTC", "uz-Latn-UZ")).toBe("20-okt");
  });

  it("leave other languages to the browser", () => {
    expect(dayMonth(moment, "Asia/Tashkent", "en-GB")).toBe("21 Oct");
  });
});

describe("time off", () => {
  const today = "2026-10-21";
  const item = (fields: Partial<TimeOff>): TimeOff => ({
    id: 1,
    first_day: "2026-10-22",
    last_day: "2026-10-23",
    reason: "",
    status: "pending",
    days: 2,
    decided_by: null,
    created_at: "2026-10-20T10:00:00Z",
    ...fields,
  });

  it("can be taken back until approved days begin", () => {
    expect(cancellable(item({ status: "pending", first_day: today }), today)).toBe(true);
    expect(cancellable(item({ status: "approved" }), today)).toBe(true);
    expect(cancellable(item({ status: "approved", first_day: today }), today)).toBe(false);
    expect(cancellable(item({ status: "rejected" }), today)).toBe(false);
  });

  it("lists what isn't over or cancelled", () => {
    const kept = item({ id: 1 });
    const over = item({ id: 2, first_day: "2026-10-10", last_day: "2026-10-20" });
    const cancelled = item({ id: 3, status: "cancelled" });
    expect(current([kept, over, cancelled], today)).toEqual([kept]);
  });
});
