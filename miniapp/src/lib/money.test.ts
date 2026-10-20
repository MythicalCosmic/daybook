import { describe, expect, it } from "vitest";

import {
  amountFromTyping,
  compareMoney,
  currencyLabel,
  formatAmount,
  formatMoney,
  formatTyping,
  fromMinor,
  groupDigits,
  isZero,
  moneyParts,
  multiplyMoney,
  normalizeAmount,
  parseMoney,
  sanitizeTyping,
  subtractMoney,
  sumMoney,
  toMinor,
} from "./money";

const NB = " ";
const MINUS = "−";

describe("money formatting", () => {
  it("groups so‘m the way each language writes them", () => {
    expect(formatMoney("12500000.00", "UZS", "uz")).toBe(`12${NB}500${NB}000${NB}so‘m`);
    expect(formatMoney("12500000.00", "UZS", "ru")).toBe(`12${NB}500${NB}000${NB}сум`);
    expect(formatMoney("12500000.00", "UZS", "en")).toBe(`12,500,000${NB}UZS`);
  });

  it("shows tiyin only when there are some, and always shows cents for dollars", () => {
    expect(formatMoney("1250000.50", "UZS", "uz")).toBe(`1${NB}250${NB}000,50${NB}so‘m`);
    expect(formatMoney("1250", "USD", "en")).toBe("$1,250.00");
    expect(formatMoney("1250.5", "USD", "ru")).toBe(`1${NB}250,50${NB}$`);
    expect(formatMoney("99.99", "UZS", "en", { cents: "never" })).toBe(`100${NB}UZS`);
    expect(formatMoney("5", "UZS", "en", { cents: "always" })).toBe(`5.00${NB}UZS`);
  });

  it("signs amounts with a real minus, and a plus on request", () => {
    expect(formatMoney("-35.5", "USD", "en")).toBe(`${MINUS}$35.50`);
    expect(formatMoney("-150000", "UZS", "uz")).toBe(`${MINUS}150${NB}000${NB}so‘m`);
    expect(formatMoney("300000", "UZS", "uz", { sign: "always" })).toBe(`+300${NB}000${NB}so‘m`);
    expect(formatMoney("0", "UZS", "uz", { sign: "always" })).toBe(`0${NB}so‘m`);
    expect(formatMoney("-5", "UZS", "en", { sign: "never" })).toBe(`5${NB}UZS`);
  });

  it("shortens big numbers for tight spots", () => {
    expect(formatMoney("1250000", "UZS", "uz", { compact: true })).toBe(`1,3${NB}mln${NB}so‘m`);
    expect(formatMoney("250000", "UZS", "ru", { compact: true })).toBe(`250${NB}тыс.${NB}сум`);
    expect(formatMoney("12500000", "UZS", "en", { compact: true })).toBe(`12.5M${NB}UZS`);
    expect(formatMoney("2340000000", "UZS", "uz", { compact: true })).toBe(`2,3${NB}mlrd${NB}so‘m`);
    expect(formatMoney("3000000", "UZS", "en", { compact: true })).toBe(`3M${NB}UZS`);
    expect(formatMoney("950", "UZS", "en", { compact: true })).toBe(`950${NB}UZS`);
  });

  it("reads missing amounts as a dash and unknown currencies by code", () => {
    expect(formatMoney(null, "UZS", "uz")).toBe("—");
    expect(formatMoney("", "UZS", "uz")).toBe("—");
    expect(formatMoney("10", "EUR", "en")).toBe(`10${NB}EUR`);
    expect(currencyLabel("UZS", "uz")).toBe("so‘m");
  });

  it("splits the parts for layouts with a small currency", () => {
    expect(moneyParts("1250.5", "USD", "en")).toEqual({ number: "1,250.50", currency: "$", currencyFirst: true });
    expect(moneyParts("1250000", "UZS", "uz")).toEqual({ number: `1${NB}250${NB}000`, currency: "so‘m", currencyFirst: false });
    expect(formatAmount("1250000", "ru")).toBe(`1${NB}250${NB}000`);
    expect(groupDigits("1000", "en")).toBe("1,000");
  });

  it("refuses strings that aren't amounts", () => {
    expect(() => formatMoney("12,5", "UZS", "en")).toThrow();
    expect(() => toMinor("1.234")).toThrow();
    expect(() => toMinor("abc")).toThrow();
  });
});

describe("money arithmetic for display", () => {
  it("converts exactly between decimal strings and minor units", () => {
    expect(toMinor("1250000.50")).toBe(125000050n);
    expect(toMinor("-0.5")).toBe(-50n);
    expect(fromMinor(125000050n)).toBe("1250000.50");
    expect(fromMinor(-5n)).toBe("-0.05");
    expect(normalizeAmount("1250000")).toBe("1250000.00");
  });

  it("adds without floating point error", () => {
    expect(sumMoney(["0.10", "0.20"])).toBe("0.30");
    expect(sumMoney(["99999999999999.99", "0.01"])).toBe("100000000000000.00");
    expect(sumMoney([])).toBe("0.00");
    expect(subtractMoney("100", "0.01")).toBe("99.99");
    expect(multiplyMoney("200000", 37)).toBe("7400000.00");
    expect(() => multiplyMoney("1", 1.5)).toThrow();
  });

  it("compares", () => {
    expect(compareMoney("10.00", "10")).toBe(0);
    expect(compareMoney("9.99", "10")).toBe(-1);
    expect(compareMoney("-1", "-2")).toBe(1);
    expect(isZero("0.00")).toBe(true);
  });
});

describe("reading typed money", () => {
  it("accepts every common way of writing an amount", () => {
    expect(parseMoney("1 250 000", "uz")).toBe("1250000");
    expect(parseMoney(`1${NB}250${NB}000,50`, "ru")).toBe("1250000.5");
    expect(parseMoney("1,250,000.50", "en")).toBe("1250000.5");
    expect(parseMoney("1.250.000", "ru")).toBe("1250000");
    expect(parseMoney("12500 so‘m", "uz")).toBe("12500");
    expect(parseMoney("$35.5", "en")).toBe("35.5");
    expect(parseMoney("1’250’000", "en")).toBe("1250000");
    expect(parseMoney("−150 000", "uz")).toBe("-150000");
    expect(parseMoney("007", "en")).toBe("7");
    expect(parseMoney("0,50", "uz")).toBe("0.5");
  });

  it("tells a decimal comma from a grouping comma", () => {
    expect(parseMoney("1,5", "ru")).toBe("1.5");
    expect(parseMoney("1,5", "en")).toBe("1.5");
    expect(parseMoney("1,250", "en")).toBe("1250");
    expect(parseMoney("1,250", "uz")).toBe("1250");
  });

  it("returns null for anything that isn't an amount", () => {
    expect(parseMoney("", "en")).toBeNull();
    expect(parseMoney("abc", "en")).toBeNull();
    expect(parseMoney("1.234", "en")).toBe("1234");
    expect(parseMoney("1,2345", "ru")).toBeNull();
    expect(parseMoney("12345678901234567", "en")).toBeNull();
  });
});

describe("typing into a money field", () => {
  it("keeps digits, one decimal point and two decimals", () => {
    expect(sanitizeTyping(`1${NB}250${NB}000`, "uz")).toBe("1250000");
    expect(sanitizeTyping("0012", "uz")).toBe("12");
    expect(sanitizeTyping("12,5", "ru", { decimals: true })).toBe("12.5");
    expect(sanitizeTyping("12.567", "en", { decimals: true })).toBe("12.56");
    expect(sanitizeTyping("1,250.5", "en", { decimals: true })).toBe("1250.5");
    expect(sanitizeTyping("12,5", "uz")).toBe("125");
    expect(sanitizeTyping(",5", "uz", { decimals: true })).toBe("0.5");
    expect(sanitizeTyping("123456", "en", { maxDigits: 4 })).toBe("1234");
  });

  it("groups as you type and keeps a trailing separator", () => {
    expect(formatTyping("1250000", "uz")).toBe(`1${NB}250${NB}000`);
    expect(formatTyping("1250000.", "ru")).toBe(`1${NB}250${NB}000,`);
    expect(formatTyping("1250.5", "en")).toBe("1,250.5");
    expect(formatTyping("", "en")).toBe("");
  });

  it("turns the typing state into an amount", () => {
    expect(amountFromTyping("1250000.")).toBe("1250000");
    expect(amountFromTyping("35.5")).toBe("35.5");
    expect(amountFromTyping("")).toBeNull();
  });
});
