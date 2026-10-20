import { describe, expect, it } from "vitest";

import {
  addDays,
  addMonths,
  compareRange,
  dayPart,
  diffDays,
  endOfMonth,
  formatDay,
  formatInstant,
  formatRange,
  formatRelative,
  presetRange,
  startOfWeek,
  todayIn,
  zonedDay,
} from "@/lib/dates";

const TZ = "Asia/Tashkent"; // UTC+5, no DST
// Wednesday 21 October 2026, 09:30 in Tashkent.
const NOW = Date.UTC(2026, 9, 21, 4, 30);

describe("company-local days", () => {
  it("uses the company's zone, not the browser's", () => {
    // 20:30 UTC is already 01:30 the next day in Tashkent.
    expect(todayIn(TZ, Date.UTC(2026, 9, 20, 20, 30))).toBe("2026-10-21");
    expect(todayIn("UTC", Date.UTC(2026, 9, 20, 20, 30))).toBe("2026-10-20");
    expect(zonedDay("2026-10-20T19:10:00Z", TZ)).toBe("2026-10-21");
  });

  it("does calendar arithmetic on days", () => {
    expect(addDays("2026-12-31", 1)).toBe("2027-01-01");
    expect(addDays("2026-03-01", -1)).toBe("2026-02-28");
    expect(addMonths("2026-01-31", 1)).toBe("2026-02-28");
    expect(addMonths("2024-01-31", 1)).toBe("2024-02-29");
    expect(diffDays("2026-10-01", "2026-10-21")).toBe(20);
    expect(startOfWeek("2026-10-21")).toBe("2026-10-19");
    expect(startOfWeek("2026-10-25")).toBe("2026-10-19");
    expect(endOfMonth("2026-02-10")).toBe("2026-02-28");
  });
});

describe("presets", () => {
  it("matches the backend's parse_range presets", () => {
    expect(presetRange("today", TZ, NOW)).toEqual({ from: "2026-10-21", to: "2026-10-21" });
    expect(presetRange("yesterday", TZ, NOW)).toEqual({ from: "2026-10-20", to: "2026-10-20" });
    expect(presetRange("week", TZ, NOW)).toEqual({ from: "2026-10-19", to: "2026-10-21" });
    expect(presetRange("last_week", TZ, NOW)).toEqual({ from: "2026-10-12", to: "2026-10-18" });
    expect(presetRange("month", TZ, NOW)).toEqual({ from: "2026-10-01", to: "2026-10-21" });
    expect(presetRange("last_month", TZ, NOW)).toEqual({ from: "2026-09-01", to: "2026-09-30" });
    expect(presetRange("last_30", TZ, NOW)).toEqual({ from: "2026-09-22", to: "2026-10-21" });
    expect(presetRange("quarter", TZ, NOW)).toEqual({ from: "2026-10-01", to: "2026-10-21" });
    expect(presetRange("year", TZ, NOW)).toEqual({ from: "2026-01-01", to: "2026-10-21" });
  });
});

describe("compareRange", () => {
  it("compares month to date with the same days of last month", () => {
    expect(compareRange({ from: "2026-10-01", to: "2026-10-21" }, "prev", "month")).toEqual({ from: "2026-09-01", to: "2026-09-21" });
  });

  it("compares a whole month with the whole previous month", () => {
    expect(compareRange({ from: "2026-09-01", to: "2026-09-30" }, "prev", "last_month")).toEqual({ from: "2026-08-01", to: "2026-08-31" });
    expect(compareRange({ from: "2026-03-01", to: "2026-03-31" }, "prev")).toEqual({ from: "2026-02-01", to: "2026-02-28" });
  });

  it("compares other ranges with the same number of days before", () => {
    expect(compareRange({ from: "2026-10-19", to: "2026-10-21" }, "prev", "week")).toEqual({ from: "2026-10-16", to: "2026-10-18" });
    expect(compareRange({ from: "2026-09-22", to: "2026-10-21" }, "prev", "last_30")).toEqual({ from: "2026-08-23", to: "2026-09-21" });
  });

  it("shifts quarters and years by whole periods", () => {
    expect(compareRange({ from: "2026-10-01", to: "2026-10-21" }, "prev", "quarter")).toEqual({ from: "2026-07-01", to: "2026-07-21" });
    expect(compareRange({ from: "2026-10-01", to: "2026-10-21" }, "year")).toEqual({ from: "2025-10-01", to: "2025-10-21" });
    expect(compareRange({ from: "2026-10-01", to: "2026-10-21" }, "none")).toBeNull();
  });
});

describe("formatting", () => {
  it("writes Uzbek dates by hand with the product's letters", () => {
    expect(formatDay("2026-10-20", "uz", "short")).toBe("20-okt");
    expect(formatDay("2026-10-20", "uz", "medium")).toBe("20-okt, 2026");
    expect(formatDay("2026-10-20", "uz", "weekday")).toBe("Seshanba, 20-oktabr");
    expect(formatDay("2026-10-20", "uz", "monthYear")).toBe("Oktabr, 2026");
  });

  it("formats Russian and English days with Intl", () => {
    expect(formatDay("2026-10-20", "en", "medium")).toBe("20 Oct 2026");
    expect(formatDay("2026-10-20", "ru", "long")).toMatch(/^20 октября 2026/);
  });

  it("shows instants in the company zone", () => {
    expect(formatInstant("2026-10-21T04:30:00Z", TZ, "en", "time")).toBe("09:30");
    expect(formatInstant("2026-10-20T20:30:00Z", TZ, "en", "datetime")).toBe("21 Oct 2026, 01:30");
    expect(formatInstant("not a date", TZ, "en")).toBe("—");
  });

  it("formats ranges compactly", () => {
    expect(formatRange({ from: "2026-10-01", to: "2026-10-21" }, "en")).toBe("1–21 Oct 2026");
    expect(formatRange({ from: "2026-09-28", to: "2026-10-04" }, "en")).toBe("28 Sept – 4 Oct 2026");
    expect(formatRange({ from: "2026-10-21", to: "2026-10-21" }, "uz")).toBe("21-okt, 2026");
  });

  it("writes relative times in three languages", () => {
    const ago = (minutes: number) => new Date(NOW - minutes * 60_000).toISOString();
    expect(formatRelative(ago(0.2), TZ, "en", NOW)).toBe("just now");
    expect(formatRelative(ago(5), TZ, "en", NOW)).toBe("5 min ago");
    expect(formatRelative(ago(5), TZ, "ru", NOW)).toBe("5 мин назад");
    expect(formatRelative(ago(5), TZ, "uz", NOW)).toBe("5 daqiqa oldin");
    expect(formatRelative(ago(180), TZ, "uz", NOW)).toBe("3 soat oldin");
    expect(formatRelative("2026-10-20T09:05:00Z", TZ, "en", NOW)).toBe("yesterday, 14:05");
    expect(formatRelative("2026-10-21T09:00:00Z", TZ, "ru", NOW)).toBe("через 5 ч");
    expect(formatRelative("2026-10-12T09:00:00Z", TZ, "uz", NOW)).toBe("12-okt");
    expect(formatRelative("2025-10-12T09:00:00Z", TZ, "en", NOW)).toBe("12 Oct 2025");
  });

  it("knows the part of the day in the company", () => {
    expect(dayPart(TZ, NOW)).toBe("morning");
    expect(dayPart(TZ, Date.UTC(2026, 9, 21, 14))).toBe("evening");
    expect(dayPart(TZ, Date.UTC(2026, 9, 21, 20))).toBe("night");
  });
});
