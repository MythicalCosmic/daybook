import { describe, expect, it } from "vitest";

import { add, changePercent, compare, convert, divide, isNegative, isZero, multiply, percent, subtract, sum, toMoney } from "@/lib/decimal";

describe("decimal", () => {
  it("adds money without float drift", () => {
    expect(sum(["0.10", "0.20"])).toBe("0.30");
    expect(sum(["1250000.10", "-250000.05", null, undefined, ""])).toBe("1000000.05");
    expect(add("0.1", "0.2")).toBe("0.30");
    expect(subtract("100", "0.01")).toBe("99.99");
  });

  it("rounds half up to cents", () => {
    expect(toMoney("2.345")).toBe("2.35");
    expect(toMoney("-2.345")).toBe("-2.35");
    expect(multiply("33.333", "3")).toBe("100.00");
  });

  it("divides safely", () => {
    expect(divide("100", "3")).toBe("33.33");
    expect(divide("100", "0")).toBeNull();
  });

  it("compares and classifies", () => {
    expect(compare("10.00", "9.99")).toBe(1);
    expect(compare("1", "1.00")).toBe(0);
    expect(isZero("0.00")).toBe(true);
    expect(isNegative("-0.01")).toBe(true);
    expect(isNegative("0")).toBe(false);
  });

  it("computes shares and deltas", () => {
    expect(percent("38", "52")).toBe(73.1);
    expect(percent("1", "0")).toBeNull();
    expect(changePercent("14250000", "13170000")).toBe(8.2);
    expect(changePercent("50", "-100")).toBe(150);
    expect(changePercent("5", "0")).toBeNull();
  });

  it("converts with a UZS-per-unit rate", () => {
    expect(convert("98", "12750.50", "to_base")).toBe("1249549.00");
    expect(convert("1250000", "12750.50", "from_base")).toBe("98.04");
  });
});
