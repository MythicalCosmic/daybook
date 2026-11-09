// The Team pages' pure helpers and their dictionaries.
import { describe, expect, it } from "vitest";

import {
  branchNames,
  centred,
  clampOffset,
  coverScale,
  FACE_NUMBER,
  hoursOf,
  importTemplate,
  IMPORT_COLUMNS,
  initials,
  monthOf,
  shiftMonth,
  sourceSquare,
  splitFaceNumbers,
  weekdayIndex,
  zoomAround,
} from "../components/team/team";
import { branchesOf } from "../components/team/teamApi";
import en from "../i18n/parts/team.en.json";
import ru from "../i18n/parts/team.ru.json";
import uz from "../i18n/parts/team.uz.json";

describe("face numbers", () => {
  it("splits what is typed or pasted, without repeats", () => {
    expect(splitFaceNumbers(" 00000002, 15  0031;15\n")).toEqual(["00000002", "15", "0031"]);
    expect(splitFaceNumbers("   ")).toEqual([]);
  });

  it("accepts what a terminal can hold, nothing else", () => {
    for (const ok of ["00000002", "A-17", "emp_9", "x".repeat(32)]) expect(FACE_NUMBER.test(ok), ok).toBe(true);
    for (const bad of ["", "12 3", "№5", "x".repeat(33), "ab/c"]) expect(FACE_NUMBER.test(bad), bad).toBe(false);
  });
});

describe("names and places", () => {
  it("lists an employee's locations in the company's order", () => {
    const branches = [
      { id: 1, name: "Main" },
      { id: 2, name: "Yunusobod" },
      { id: 3, name: "Sergeli" },
    ];
    expect(branchNames([3, 1], branches)).toEqual(["Main", "Sergeli"]);
    expect(branchNames([], branches)).toEqual([]);
  });

  it("makes initials for Latin and Cyrillic names", () => {
    expect(initials("Aziza Karimova")).toBe("AK");
    expect(initials("Шахзод")).toBe("ША");
    expect(initials("  ")).toBe("?");
  });
});

describe("months", () => {
  it("moves between months and finds weekdays (Monday first)", () => {
    expect(monthOf("2026-11-10")).toBe("2026-11");
    expect(shiftMonth("2026-01", -1)).toBe("2025-12");
    expect(shiftMonth("2026-12", 1)).toBe("2027-01");
    expect(weekdayIndex("2026-11-09")).toBe(0);
    expect(weekdayIndex("2026-11-15")).toBe(6);
    expect(hoursOf(545)).toBe(9.1);
  });
});

describe("the import template", () => {
  it("has the columns the server reads and quotes what needs it", () => {
    const csv = importTemplate(["Aziza", "Karimova", "+998", "Sales, North", "", "", "00000002"]);
    const [header, row] = csv.replace("﻿", "").trim().split("\n");
    expect(header).toBe(IMPORT_COLUMNS.join(","));
    expect(row).toBe('Aziza,Karimova,+998,"Sales, North",,,00000002');
    expect(csv.startsWith("﻿")).toBe(true);
  });
});

describe("the photo cropper's arithmetic", () => {
  const frame = 280;

  it("covers the frame with the image's shorter side and centres it", () => {
    const scale = coverScale(1000, 500, frame);
    expect(scale).toBeCloseTo(0.56);
    expect(centred(1000, 500, frame, scale)).toEqual({ x: (280 - 560) / 2, y: 0 });
  });

  it("never lets an edge come inside the frame", () => {
    const scale = coverScale(1000, 500, frame);
    expect(clampOffset(1000, 500, frame, scale, 50, 30)).toEqual({ x: 0, y: 0 });
    expect(clampOffset(1000, 500, frame, scale, -900, -30)).toEqual({ x: -280, y: 0 });
  });

  it("zooms around the frame's centre and crops the square it shows", () => {
    const base = coverScale(800, 800, frame);
    const start = centred(800, 800, frame, base);
    const zoomed = zoomAround(800, 800, frame, { scale: base, ...start }, base * 2);
    expect(zoomed.x).toBeCloseTo(-140);
    expect(zoomed.y).toBeCloseTo(-140);
    const square = sourceSquare(frame, base * 2, zoomed.x, zoomed.y);
    expect(square.size).toBeCloseTo(400);
    expect(square.sx).toBeCloseTo(200);
    expect(square.sy).toBeCloseTo(200);
  });
});

describe("the board's locations", () => {
  it("reads the numbers per location when the board sends them", () => {
    expect(branchesOf(undefined)).toEqual([]);
    const board = { date: "2026-11-10", is_today: true, now: "", holiday: null, totals: {} as never, people: [], branches: [{ id: 1, name: "Main", rostered: 10, checked_in: 7, first_check_in: null }] };
    expect(branchesOf(board)).toHaveLength(1);
  });
});

describe("dictionaries", () => {
  it("say everything in all three languages, plurals in the house shape", () => {
    const keys = Object.keys(en).sort();
    expect(Object.keys(uz).sort()).toEqual(keys);
    expect(Object.keys(ru).sort()).toEqual(keys);
    for (const dictionary of [en, uz, ru] as Record<string, string>[]) {
      for (const [key, value] of Object.entries(dictionary)) {
        expect(key.startsWith("davomat."), key).toBe(true);
        expect(value.trim(), key).not.toBe("");
        const forms = value.split(" | ");
        if (forms.length > 1) {
          expect(forms.length, key).toBe(3);
          const placeholders = forms.map((form) => [...form.matchAll(/\{(\w+)\}/g)].map((match) => match[1]).sort().join(","));
          expect(new Set(placeholders).size, key).toBe(1);
        }
      }
    }
    for (const value of Object.values(uz as Record<string, string>)) expect(value).not.toMatch(/[a-z]['`ʻ][a-z]/i);
  });
});
