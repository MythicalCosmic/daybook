/** How tasks read and sort: one order everywhere, the last-hour countdown, deadlines in a sentence. */
import { describe, expect, it } from "vitest";

import { giverMeta } from "../screens/Tasks";
import { ctxFor, makeTask, NOW } from "../test/harness";
import { blockerReason, byFocus, formatDue, groupByDay, groupTasks, minutesLeft, priorityLevel, rowMeta, rowRight, seenLabel } from "./taskView";

describe("one order everywhere (R2 T7)", () => {
  it("puts late work first, then sent back, then urgent, then the soonest deadline, undated last", () => {
    const late = makeTask({ title: "late", due_at: "2026-10-21T09:00:00+05:00" });
    const returned = makeTask({ title: "returned", status: "returned", due_at: "2026-10-21T17:00:00+05:00" });
    const urgent = makeTask({ title: "urgent", priority: "urgent", due_at: "2026-10-21T16:00:00+05:00" });
    const soon = makeTask({ title: "soon", due_at: "2026-10-21T12:00:00+05:00" });
    const undated = makeTask({ title: "undated", due_at: null });
    const sorted = [undated, soon, urgent, returned, late].sort(byFocus(NOW)).map((task) => task.title);
    expect(sorted).toEqual(["late", "returned", "urgent", "soon", "undated"]);
  });

  it("sorts urgent work first inside each group", () => {
    const groups = groupTasks(
      [
        makeTask({ title: "normal", due_at: "2026-10-21T11:00:00+05:00" }),
        makeTask({ title: "urgent", priority: "urgent", due_at: "2026-10-21T17:00:00+05:00" }),
      ],
      NOW,
    );
    expect(groups[0].tasks.map((task) => task.title)).toEqual(["urgent", "normal"]);
  });
});

describe("work by day (audit M-7)", () => {
  it("splits open work into today, tomorrow, the next few days, later and undated", () => {
    const groups = groupByDay(
      [
        makeTask({ title: "late", due_at: "2026-10-21T09:00:00+05:00" }),
        makeTask({ title: "today", due_at: "2026-10-21T18:00:00+05:00" }),
        makeTask({ title: "tomorrow", due_at: "2026-10-22T10:00:00+05:00" }),
        makeTask({ title: "friday", due_at: "2026-10-23T10:00:00+05:00" }),
        makeTask({ title: "count", due_at: "2026-11-14T10:00:00+05:00" }),
        makeTask({ title: "someday", due_at: null }),
        makeTask({ title: "checked", status: "review" }),
      ],
      ctxFor("en"),
    );
    expect(groups.map((group) => [group.key, group.tasks.map((task) => task.title)])).toEqual([
      ["attention", ["late"]],
      ["today", ["today"]],
      ["tomorrow", ["tomorrow"]],
      ["soon", ["friday"]],
      ["later", ["count"]],
      ["noDue", ["someday"]],
      ["review", ["checked"]],
    ]);
  });

  it("says when work is underway", () => {
    expect(rowMeta(makeTask({ status: "in_progress" }), ctxFor("uz"))).toBe("Jarayonda · Kimdan: Bekzod Mirzayev");
  });
});

describe("priority on a phone (R2 T19/T20)", () => {
  it("is Urgent, a quiet high, or nothing", () => {
    expect(priorityLevel({ priority: "urgent" })).toBe("urgent");
    expect(priorityLevel({ priority: "high" })).toBe("high");
    expect(priorityLevel({ priority: "normal" })).toBeNull();
    expect(priorityLevel({ priority: "low" })).toBeNull();
  });
});

describe("the time chip", () => {
  it("counts down in the last hour, in every language", () => {
    const task = makeTask({ due_at: "2026-10-21T10:25:00+05:00" });
    expect(minutesLeft(task, NOW)).toBe(25);
    expect(rowRight(task, ctxFor("en"))).toBe("25 min left");
    expect(rowRight(task, ctxFor("uz"))).toBe("25 daq qoldi");
    expect(rowRight(task, ctxFor("ru"))).toBe("осталось 25 мин");
    // Further out, the time; finished work never counts down.
    expect(rowRight(makeTask({ due_at: "2026-10-21T18:00:00+05:00" }), ctxFor("en"))).toBe("18:00");
    expect(minutesLeft(makeTask({ due_at: "2026-10-21T10:25:00+05:00", status: "done" }), NOW)).toBeNull();
  });

  it("spells the weekday out in Uzbek, where a short one reads as an English word", () => {
    const friday = makeTask({ due_at: "2026-10-23T18:00:00+05:00" });
    expect(rowRight(friday, ctxFor("uz"))).toBe("Juma");
    expect(rowRight(makeTask({ due_at: "2026-10-22T18:00:00+05:00" }), ctxFor("uz"))).toBe("Ertaga");
    expect(rowRight(friday, ctxFor("en"))).toBe("Fri");
  });
});

describe("a deadline as words", () => {
  it("starts a line with a capital and keeps it lowercase inside a sentence", () => {
    expect(formatDue("2026-10-21T18:00:00+05:00", ctxFor("uz"))).toBe("Bugun, 18:00");
    expect(formatDue("2026-10-21T18:00:00+05:00", ctxFor("uz"), true)).toBe("bugun, 18:00");
    expect(formatDue("2026-10-29T18:30:00+05:00", ctxFor("uz"))).toBe("Payshanba, 29-oktabr, 18:30");
    expect(formatDue("2026-10-29T18:30:00+05:00", ctxFor("ru"), true)).toBe("чт 29 окт., 18:30");
    expect(formatDue("2026-10-29T18:30:00+05:00", ctxFor("en"), true)).toBe("Thu 29 Oct, 18:30");
  });
});

describe("blocker reasons", () => {
  it("read as Other when the backend sends one this app doesn't know", () => {
    expect(blockerReason("no_stock", ctxFor("uz").t)).toBe("Tovar yo‘q");
    expect(blockerReason("sick", ctxFor("en").t)).toBe("Other");
  });
});

describe("seen receipts (R2 T36)", () => {
  it("say when the worker opened assigned work, and nothing when the backend can't tell", () => {
    expect(seenLabel(makeTask({ seen_at: "2026-10-21T09:12:00+05:00" }), ctxFor("uz"))).toBe("Ko‘rdi · 09:12");
    expect(seenLabel(makeTask({ seen_at: "2026-10-20T19:05:00+05:00" }), ctxFor("en"))).toBe("Seen 20 Oct, 19:05");
    expect(seenLabel(makeTask({ seen_at: null }), ctxFor("ru"))).toBe("Ещё не просмотрено");
    expect(seenLabel(makeTask(), ctxFor("en"))).toBeNull();
    expect(seenLabel(makeTask({ kind: "personal", seen_at: null }), ctxFor("en"))).toBeNull();
  });
});

describe("the line under work I gave", () => {
  it("names who has it and where it stands for me", () => {
    const ctx = ctxFor("en");
    expect(giverMeta(makeTask({ seen_at: "2026-10-21T09:12:00+05:00" }), ctx)).toBe("Alisher Valiyev · Seen 09:12");
    expect(giverMeta(makeTask({ due_at: "2026-10-21T09:30:00+05:00" }), ctx)).toBe("Alisher Valiyev · 30 min late");
    expect(giverMeta(makeTask({ blocker: { reason_code: "no_stock", note: "", at: NOW.toISOString() } }), ctx)).toBe(
      "Alisher Valiyev · Can't be done: out of stock",
    );
    expect(giverMeta(makeTask({ status: "review", completed_at: "2026-10-21T09:40:00+05:00" }), ctx)).toBe("Alisher Valiyev · finished 09:40");
    // Finished on another day: the day is there, and the wording still reads ("готово в 20 окт." didn't).
    const earlier = makeTask({ status: "review", completed_at: "2026-10-20T20:35:00+05:00" });
    expect(giverMeta(earlier, ctx)).toBe("Alisher Valiyev · finished 20 Oct, 20:35");
    expect(giverMeta(earlier, ctxFor("ru"))).toBe("Alisher Valiyev · выполнено: 20 окт., 20:35");
    expect(giverMeta(earlier, ctxFor("uz"))).toBe("Alisher Valiyev bajardi · 20-okt, 20:35");
    expect(giverMeta(makeTask({ status: "in_progress" }), ctx)).toBe("Alisher Valiyev · In progress");
  });
});
