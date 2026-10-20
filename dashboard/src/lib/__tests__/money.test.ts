import { describe, expect, it } from "vitest";

import { formatAmount, formatApprox, formatCompact, formatMoney, moneySign, parseMoneyInput, toCents } from "@/lib/money";

const S = " "; // grouping and unit space
const M = "−"; // minus

describe("toCents", () => {
  it("reads API strings exactly and rounds half up to cents", () => {
    expect(toCents("1250000.00")).toEqual({ negative: false, cents: 125000000n });
    expect(toCents("12.345")).toEqual({ negative: false, cents: 1235n });
    expect(toCents("12.344")).toEqual({ negative: false, cents: 1234n });
    expect(toCents("-15000")).toEqual({ negative: true, cents: 1500000n });
    expect(toCents(".5")).toEqual({ negative: false, cents: 50n });
  });

  it("refuses junk and treats -0 as zero", () => {
    expect(toCents("abc")).toBeNull();
    expect(toCents("")).toBeNull();
    expect(toCents(null)).toBeNull();
    expect(toCents("1,5")).toBeNull();
    expect(toCents("-0.00")).toEqual({ negative: false, cents: 0n });
  });

  it("never loses precision on big amounts", () => {
    expect(toCents("98765432109876.55")?.cents).toBe(9876543210987655n);
  });
});

describe("formatMoney", () => {
  it("formats UZS per language (plan §6.3)", () => {
    expect(formatMoney("1250000.00", "UZS", "uz")).toBe(`1${S}250${S}000${S}so‘m`);
    expect(formatMoney("1250000.00", "UZS", "ru")).toBe(`1${S}250${S}000${S}сум`);
    expect(formatMoney("1250000.00", "UZS", "en")).toBe(`UZS${S}1,250,000`);
  });

  it("shows tiyins only when there are some", () => {
    expect(formatMoney("1250000.50", "UZS", "uz")).toBe(`1${S}250${S}000,50${S}so‘m`);
    expect(formatMoney("1250000.5", "UZS", "en")).toBe(`UZS${S}1,250,000.50`);
  });

  it("always shows cents for USD", () => {
    expect(formatMoney("1250", "USD", "en")).toBe("$1,250.00");
    expect(formatMoney("1250", "USD", "ru")).toBe(`1${S}250,00${S}$`);
    expect(formatMoney("1250.4", "USD", "uz")).toBe(`1${S}250,40${S}$`);
  });

  it("uses a real minus sign and optional plus", () => {
    expect(formatMoney("-15000", "UZS", "uz")).toBe(`${M}15${S}000${S}so‘m`);
    expect(formatMoney("-12.5", "USD", "en")).toBe(`${M}$12.50`);
    expect(formatMoney("300000", "UZS", "en", { sign: "always" })).toBe(`+UZS${S}300,000`);
    expect(formatMoney("0", "UZS", "en", { sign: "always" })).toBe(`UZS${S}0`);
  });

  it("can print just the number", () => {
    expect(formatMoney("1250000", "UZS", "ru", { currencyDisplay: "none" })).toBe(`1${S}250${S}000`);
  });

  it("formats compact amounts for small tiles", () => {
    expect(formatMoney("12500000", "UZS", "uz", { compact: true })).toBe(`12,5${S}mln${S}so‘m`);
    expect(formatMoney("12500000", "UZS", "ru", { compact: true })).toBe(`12,5${S}млн${S}сум`);
    expect(formatMoney("12500000", "UZS", "en", { compact: true })).toBe(`UZS${S}12.5M`);
    expect(formatMoney("-86420000", "UZS", "en", { compact: true })).toBe(`${M}UZS${S}86.4M`);
  });

  it("shows a dash for missing values", () => {
    expect(formatMoney(null, "UZS", "uz")).toBe("—");
    expect(formatMoney("oops", "UZS", "uz")).toBe("—");
  });
});

describe("formatCompact", () => {
  it("picks the unit and rounds half up to one decimal", () => {
    expect(formatCompact("1500", "uz")).toBe(`1,5${S}ming`);
    expect(formatCompact("1000", "en")).toBe("1K");
    expect(formatCompact("2340000000", "ru")).toBe(`2,3${S}млрд`);
    expect(formatCompact("12450000", "en")).toBe("12.5M");
    expect(formatCompact("950", "en")).toBe("950");
  });

  it("promotes 999 950 to a million instead of printing 1000K", () => {
    expect(formatCompact("999999", "en")).toBe("1M");
    expect(formatCompact("999950", "uz")).toBe(`1${S}mln`);
  });
});

describe("formatAmount", () => {
  it("rounds to whole units when asked", () => {
    expect(formatAmount("1234.50", "en", "never")).toBe("1,235");
    expect(formatAmount("1234.49", "en", "never")).toBe("1,234");
    expect(formatAmount("1234", "en", "always")).toBe("1,234.00");
  });
});

describe("formatApprox", () => {
  it("prints a rounded hint", () => {
    expect(formatApprox("98.40", "USD", "en")).toBe(`≈${S}$98`);
    expect(formatApprox("1250000", "UZS", "uz")).toBe(`≈${S}1,3${S}mln${S}so‘m`);
  });
});

describe("parseMoneyInput", () => {
  it("reads what people type in any language", () => {
    expect(parseMoneyInput("1 250 000")).toBe("1250000.00");
    expect(parseMoneyInput("1 250 000,5")).toBe("1250000.50");
    expect(parseMoneyInput("1,250,000.50")).toBe("1250000.50");
    expect(parseMoneyInput("12.5")).toBe("12.50");
    expect(parseMoneyInput("1.250")).toBe("1250.00");
    expect(parseMoneyInput("−300")).toBe("-300.00");
    expect(parseMoneyInput("007")).toBe("7.00");
  });

  it("refuses text that isn't an amount", () => {
    expect(parseMoneyInput("")).toBeNull();
    expect(parseMoneyInput("abc")).toBeNull();
    expect(parseMoneyInput("12a")).toBeNull();
  });
});

describe("moneySign", () => {
  it("compares without floats", () => {
    expect(moneySign("-0.01")).toBe(-1);
    expect(moneySign("0.00")).toBe(0);
    expect(moneySign("5")).toBe(1);
    expect(moneySign(undefined)).toBe(0);
  });
});
