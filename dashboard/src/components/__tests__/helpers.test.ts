/** The small pure helpers behind TreeList, CalendarWeek, WidgetGrid, TimePicker and KpiCard. */
import { describe, expect, it } from "vitest";

import { itemDays, itemsByDay, layoutTimed, namesItem, withoutEcho, type CalendarItem } from "@/components/calendarItems";
import { iconForKind } from "@/components/kindIcons";
import { matchOption, normalize } from "@/components/options";
import { dropMove, flattenTree, keyboardMove, moveNode, zoneAt, type TreeNode } from "@/components/tree";
import { arrange, moveWidget, toggleWidget } from "@/components/widgetLayout";
import { parseTime } from "@/lib/time";
import { easeOutCubic } from "@/lib/useTween";
import { paramsDiffer } from "@/lib/useSavedViews";

const tree: TreeNode[] = [
  { id: "ops", label: "Operations", children: [{ id: "open", label: "Opening" }, { id: "close", label: "Closing", children: [{ id: "cash", label: "Cash count" }] }] },
  { id: "hr", label: "HR" },
  { id: "locked", label: "Archive", locked: true },
];

const ids = (nodes: TreeNode[]): unknown => nodes.map((n) => (n.children?.length ? { [String(n.id)]: ids(n.children) } : n.id));

describe("tree", () => {
  it("flattens only expanded branches, with depth and position", () => {
    const flat = flattenTree(tree, new Set(["ops"]));
    expect(flat.map((r) => [r.node.id, r.depth, r.index])).toEqual([
      ["ops", 0, 0],
      ["open", 1, 0],
      ["close", 1, 1],
      ["hr", 0, 1],
      ["locked", 0, 2],
    ]);
    expect(flat[2]!.hasChildren && !flat[2]!.expanded).toBe(true);
  });

  it("moves a node to another parent and reorders siblings", () => {
    expect(ids(moveNode(tree, { id: "hr", parentId: "ops", index: 0 }))).toEqual([{ ops: ["hr", "open", { close: ["cash"] }] }, "locked"]);
    expect(ids(moveNode(tree, { id: "close", parentId: null, index: 0 }))).toEqual([{ close: ["cash"] }, { ops: ["open"] }, "hr", "locked"]);
    // Never into its own subtree.
    expect(ids(moveNode(tree, { id: "ops", parentId: "cash", index: 0 }))).toEqual(ids(tree));
  });

  it("works out drops above, below and inside, refusing its own subtree, locked nodes and depth limits", () => {
    const flat = flattenTree(tree, new Set(["ops", "close"]));
    const row = (id: string) => flat.find((r) => r.node.id === id)!;
    expect(dropMove(tree, "hr", row("open"), "before")).toEqual({ id: "hr", parentId: "ops", index: 0 });
    expect(dropMove(tree, "open", row("close"), "after")).toEqual({ id: "open", parentId: "ops", index: 1 });
    expect(dropMove(tree, "hr", row("close"), "inside")).toEqual({ id: "hr", parentId: "close", index: 1 });
    expect(dropMove(tree, "ops", row("cash"), "inside")).toBeNull();
    expect(dropMove(tree, "hr", row("locked"), "inside")).toBeNull();
    expect(dropMove(tree, "close", row("hr"), "inside", 1)).toBeNull();
    expect(zoneAt(2, 32, true)).toBe("before");
    expect(zoneAt(16, 32, true)).toBe("inside");
    expect(zoneAt(16, 32, false)).toBe("after");
  });

  it("moves with the keyboard: up, down, indent and outdent", () => {
    expect(keyboardMove(tree, "hr", "up")).toEqual({ id: "hr", parentId: null, index: 0 });
    expect(keyboardMove(tree, "ops", "up")).toBeNull();
    expect(keyboardMove(tree, "hr", "indent")).toEqual({ id: "hr", parentId: "ops", index: 2 });
    expect(keyboardMove(tree, "cash", "outdent")).toEqual({ id: "cash", parentId: "ops", index: 2 });
    expect(keyboardMove(tree, "ops", "outdent")).toBeNull();
  });
});

describe("calendar items", () => {
  const tz = "Asia/Tashkent";
  it("spreads all-day items over their days and orders timed ones", () => {
    const items: CalendarItem[] = [
      { id: 1, title: "Leave", start: "2026-10-19", end: "2026-10-21", all_day: true },
      { id: 2, title: "Meeting", start: "2026-10-20T09:00:00+05:00", end: "2026-10-20T10:00:00+05:00" },
      { id: 3, title: "Early", start: "2026-10-20T03:00:00Z" },
    ];
    expect(itemDays(items[1]!, tz)).toEqual({ first: "2026-10-20", last: "2026-10-20" });
    const days = itemsByDay(items, ["2026-10-20", "2026-10-21", "2026-10-22"], tz);
    // 03:00 UTC is 08:00 in Tashkent, before the 09:00 meeting.
    expect(days.get("2026-10-20")!.map((p) => p.item.id)).toEqual([1, 3, 2]);
    expect(days.get("2026-10-20")![0]).toMatchObject({ fromBefore: true, toAfter: true });
    expect(days.get("2026-10-21")![0]).toMatchObject({ fromBefore: true, toAfter: false });
    expect(days.get("2026-10-22")).toEqual([]);
  });

  it("keeps items spanning several days in the top rows, earliest and longest first", () => {
    const items: CalendarItem[] = [
      { id: "due", title: "12 tasks due", start: "2026-10-20", all_day: true },
      { id: "short", title: "Madina · time off", start: "2026-10-20", end: "2026-10-21", all_day: true },
      { id: "long", title: "Jasur · time off", start: "2026-10-18", end: "2026-10-22", all_day: true },
      { id: "meeting", title: "Meeting", start: "2026-10-20T09:00:00+05:00" },
    ];
    const days = itemsByDay(items, ["2026-10-19", "2026-10-20", "2026-10-21"], tz);
    expect(days.get("2026-10-20")!.map((p) => p.item.id)).toEqual(["long", "short", "due", "meeting"]);
    expect(days.get("2026-10-21")!.map((p) => p.item.id)).toEqual(["long", "short"]);
  });

  it("names a continuing bar at the start of each week and after a day it had no room on", () => {
    const leave: CalendarItem = { id: 1, title: "Jasur · time off", start: "2026-10-16", end: "2026-10-20", all_day: true };
    const others = (n: number) => Array.from({ length: n }, (_, i): CalendarItem => ({ id: `o${i}`, title: `Other ${i}`, start: "2026-10-16", all_day: true }));
    const days = itemsByDay([leave], ["2026-10-16", "2026-10-17", "2026-10-18", "2026-10-19", "2026-10-20"], tz);
    const entry = (day: string) => days.get(day)!.find((p) => p.item === leave)!;
    // Its first day, and Monday 19 October, which starts a new week row.
    expect(namesItem(entry("2026-10-16"), "2026-10-16", "2026-10-12", undefined, 3, 0)).toBe(true);
    expect(namesItem(entry("2026-10-17"), "2026-10-17", "2026-10-12", days.get("2026-10-16"), 3, 0)).toBe(false);
    expect(namesItem(entry("2026-10-19"), "2026-10-19", "2026-10-19", days.get("2026-10-18"), 3, 0)).toBe(true);
    // The day before had four other items ahead of it and showed only three: name it here.
    const placed = (list: CalendarItem[]) => list.map((item) => ({ item, fromBefore: false, toAfter: false }));
    const crowded = [...placed(others(4)), entry("2026-10-16")];
    expect(namesItem(entry("2026-10-17"), "2026-10-17", "2026-10-12", crowded, 3, 0)).toBe(true);
    // The day before showed it one row lower (another bar ended): the bar starts again here, named.
    const lower = [...placed(others(1)), entry("2026-10-16")];
    expect(namesItem(entry("2026-10-17"), "2026-10-17", "2026-10-12", lower, 3, 0)).toBe(true);
    expect(namesItem(entry("2026-10-17"), "2026-10-17", "2026-10-12", lower, 3, 1)).toBe(false);
  });

  it("drops a second line that only repeats the title", () => {
    const item = (title: string, subtitle?: string): CalendarItem => ({ id: title, title, subtitle, start: "2026-10-21", all_day: true });
    expect(withoutEcho(item("Jasur Tursunov · time off", "Time off")).subtitle).toBeUndefined();
    expect(withoutEcho(item("18 tasks due", "Tasks due")).subtitle).toBeUndefined();
    expect(withoutEcho(item("Chilonzor: 2 on shift", "Shifts")).subtitle).toBeUndefined();
    expect(withoutEcho(item("GPP inspection visit", "Company events")).subtitle).toBe("Company events");
    expect(withoutEcho(item("Pharmacist training")).subtitle).toBeUndefined();
  });

  it("lays overlapping events side by side", () => {
    const item = (id: number): CalendarItem => ({ id, title: String(id), start: "" });
    const boxes = layoutTimed([
      { item: item(1), start: 540, end: 600 },
      { item: item(2), start: 555, end: 620 },
      { item: item(3), start: 610, end: 660 },
      { item: item(4), start: 700, end: 720 },
    ]);
    const byId = Object.fromEntries(boxes.map((b) => [b.item.id, [b.column, b.columns]]));
    expect(byId).toEqual({ 1: [0, 2], 2: [1, 2], 3: [0, 2], 4: [0, 1] });
  });
});

describe("widget layout", () => {
  const widgets = [
    { id: "sales", span: 2 as const },
    { id: "tasks", span: 1 as const },
    { id: "cash", span: 1 as const },
  ];
  it("applies the saved order, appends new widgets and flags hidden ones", () => {
    const arranged = arrange(widgets, { order: ["cash", "gone", "sales"], hidden: ["tasks"] });
    expect(arranged.map((w) => [w.id, w.hidden])).toEqual([
      ["cash", false],
      ["sales", false],
      ["tasks", true],
    ]);
  });
  it("moves and toggles", () => {
    expect(moveWidget({ order: [], hidden: [] }, widgets, 0, 2).order).toEqual(["tasks", "cash", "sales"]);
    expect(toggleWidget(toggleWidget({ order: [], hidden: [] }, "cash"), "cash").hidden).toEqual([]);
  });
});

describe("small parsers", () => {
  it("reads times the quick way", () => {
    expect(parseTime("9")).toBe("09:00");
    expect(parseTime("930")).toBe("09:30");
    expect(parseTime("21.15")).toBe("21:15");
    expect(parseTime("9:5")).toBe("09:05");
    expect(parseTime("2400")).toBeNull();
    expect(parseTime("ab")).toBeNull();
  });

  it("matches options without accents or apostrophes", () => {
    expect(normalize("O‘zbekiston")).toBe("ozbekiston");
    expect(matchOption({ value: 1, label: "G‘ayrat Ro‘ziyev", description: "Kassir" }, "gayrat kass")).toBe(true);
    expect(matchOption({ value: 1, label: "Madina", keywords: ["CHL"] }, "chl")).toBe(true);
    expect(matchOption({ value: 1, label: "Madina" }, "aziz")).toBe(false);
  });

  it("eases and compares saved views", () => {
    expect(easeOutCubic(0)).toBe(0);
    expect(easeOutCubic(1)).toBe(1);
    expect(easeOutCubic(0.5)).toBeGreaterThan(0.5);
    expect(paramsDiffer({ status: ["late", "open"], q: "" }, { status: ["open", "late"] })).toBe(false);
    expect(paramsDiffer({ status: ["open"] }, { status: ["open"], branch: "1" })).toBe(true);
  });
});

describe("kind icons", () => {
  it("tells apart the queue kinds of one app that sit side by side in the Inbox", () => {
    const kinds = ["sales.verify", "sales.handover", "attendance.corrections", "attendance.overtime", "attendance.swaps", "timeoff.request", "tasks.review", "members.join"];
    expect(new Set(kinds.map((kind) => iconForKind(kind))).size).toBe(kinds.length);
    // Unknown kinds still fall back to their app's icon.
    expect(iconForKind("sales.something_new")).toBe(iconForKind("sales"));
  });
});
