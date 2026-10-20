import { describe, expect, it } from "vitest";

import { capitalize, formatCount, formatDelta, formatDuration, formatNumber, formatPercent, formatPhone, hashIndex, initials } from "@/lib/format";

const S = " ";

describe("format", () => {
  it("groups numbers per language", () => {
    expect(formatNumber(1234567, "uz")).toBe(`1${S}234${S}567`);
    expect(formatNumber(1234567, "en")).toBe("1,234,567");
    expect(formatNumber("1234.5", "ru", 2)).toBe(`1${S}234,5`);
    expect(formatNumber(-3, "en")).toBe("−3");
    expect(formatNumber(null, "en")).toBe("—");
    expect(formatNumber("x", "en")).toBe("—");
  });

  it("writes percentages and deltas", () => {
    expect(formatPercent(93, "uz")).toBe("93%");
    expect(formatPercent(93, "ru")).toBe(`93${S}%`);
    expect(formatPercent(93.25, "en", 1)).toBe("93.3%");
    expect(formatDelta(8.2, "en")).toBe("+8.2%");
    expect(formatDelta(-12, "uz")).toBe("−12%");
    expect(formatDelta(0, "en")).toBe("0%");
    expect(formatDelta(null, "en")).toBe("—");
  });

  it("writes durations", () => {
    expect(formatDuration(192, "en")).toBe("3h 12m");
    expect(formatDuration(192, "uz")).toBe(`3${S}soat 12${S}daq`);
    expect(formatDuration(180, "ru")).toBe(`3${S}ч`);
    expect(formatDuration(45, "ru")).toBe(`45${S}мин`);
  });

  it("caps badge counts", () => {
    expect(formatCount(7)).toBe("7");
    expect(formatCount(120)).toBe("99+");
    expect(formatCount(-2)).toBe("0");
  });

  it("makes initials and phone numbers", () => {
    expect(initials("Dilnoza Karimova")).toBe("DK");
    expect(initials("  madina  ")).toBe("MA");
    expect(initials("Aziz Abdulla o‘g‘li Karimov")).toBe("AK");
    expect(initials("")).toBe("?");
    expect(formatPhone("+998901234567")).toBe("+998 90 123 45 67");
    expect(formatPhone("998901234567")).toBe("+998 90 123 45 67");
    expect(formatPhone("+7 912 000")).toBe("+7 912 000");
  });

  it("has small helpers", () => {
    expect(capitalize("dushanba")).toBe("Dushanba");
    expect(hashIndex("Dilnoza Karimova", 7)).toBe(hashIndex("Dilnoza Karimova", 7));
    expect(hashIndex("x", 7)).toBeGreaterThanOrEqual(0);
    expect(hashIndex("x", 7)).toBeLessThan(7);
  });
});
