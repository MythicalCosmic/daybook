/**
 * Money on the client: strings in, strings out.
 *
 * The API sends amounts as decimal strings ("1250000.00") with a currency code, and the client
 * never does money arithmetic in floating point. Formatting and parsing follow the person's
 * language; the few sums the UI needs for display (a running total while counting banknotes)
 * use exact integer arithmetic in tiyin/cents through BigInt. Totals that matter always come
 * from the server.
 */

import type { Lang } from "../i18n";

export type Currency = "UZS" | "USD";

/** "1250000" or "1250000.5": digits, an optional dot and at most two decimals, an optional sign. */
export type DecimalString = string;

const NBSP = " ";
const MINUS = "−";
const DECIMAL_RE = /^-?\d+(\.\d{1,2})?$/;
/** Decimal(18, 2) on the server: at most 16 digits before the point. */
const MAX_INTEGER_DIGITS = 16;

const GROUP: Record<Lang, string> = { en: ",", ru: NBSP, uz: NBSP };
const POINT: Record<Lang, string> = { en: ".", ru: ",", uz: "," };

const CURRENCY: Record<Currency, Record<Lang, { text: string; before: boolean }>> = {
  UZS: {
    uz: { text: "so‘m", before: false },
    ru: { text: "сум", before: false },
    en: { text: "UZS", before: false },
  },
  USD: {
    uz: { text: "$", before: false },
    ru: { text: "$", before: false },
    en: { text: "$", before: true },
  },
};

const COMPACT: Record<Lang, [thousand: string, million: string, billion: string]> = {
  uz: ["ming", "mln", "mlrd"],
  ru: ["тыс.", "млн", "млрд"],
  en: ["K", "M", "B"],
};

export type Cents = "auto" | "always" | "never";

export type MoneyFormat = {
  /** Show the fraction: always two digits, only when it isn't zero ("auto"), or never (rounded half up). */
  cents?: Cents;
  /** "always" puts a plus on positive amounts, as in "+300 000 so‘m". */
  sign?: "auto" | "always" | "never";
  /** Short form for tight spots: "1,2 mln so‘m", "250 тыс. сум", "1.2M UZS". */
  compact?: boolean;
  /** Leave the currency out (the label next to the number says it). */
  bare?: boolean;
};

/** UZS hides tiyin unless there are some; dollars always show cents, like the server's format_money. */
const DEFAULT_CENTS: Record<string, Cents> = { UZS: "auto", USD: "always" };

export function isDecimal(value: string): value is DecimalString {
  return DECIMAL_RE.test(value);
}

/** Integer amount in the minor unit (tiyin or cents). Throws on anything that isn't a decimal string. */
export function toMinor(amount: DecimalString): bigint {
  const value = amount.trim();
  if (!isDecimal(value)) throw new Error(`Not a money amount: "${amount}"`);
  const negative = value.startsWith("-");
  const [whole, fraction = ""] = value.replace("-", "").split(".");
  const minor = BigInt(whole) * 100n + BigInt((fraction + "00").slice(0, 2));
  return negative ? -minor : minor;
}

/** The server's canonical form, always with two decimals: 125000050n → "1250000.50". */
export function fromMinor(minor: bigint): DecimalString {
  const negative = minor < 0n;
  const absolute = negative ? -minor : minor;
  const whole = absolute / 100n;
  const fraction = String(absolute % 100n).padStart(2, "0");
  return `${negative ? "-" : ""}${whole}.${fraction}`;
}

/** "1250000" → "1250000.00", for request bodies. */
export function normalizeAmount(amount: DecimalString): DecimalString {
  return fromMinor(toMinor(amount));
}

/** Display-only sum (counting banknotes, a draft's running total). The server decides real totals. */
export function sumMoney(amounts: readonly DecimalString[]): DecimalString {
  return fromMinor(amounts.reduce((total, amount) => total + toMinor(amount), 0n));
}

export function subtractMoney(a: DecimalString, b: DecimalString): DecimalString {
  return fromMinor(toMinor(a) - toMinor(b));
}

/** Amount × a whole count, as in 37 notes of 50 000. */
export function multiplyMoney(amount: DecimalString, count: number): DecimalString {
  if (!Number.isInteger(count)) throw new Error(`Count must be a whole number: ${count}`);
  return fromMinor(toMinor(amount) * BigInt(count));
}

export function compareMoney(a: DecimalString, b: DecimalString): -1 | 0 | 1 {
  const difference = toMinor(a) - toMinor(b);
  return difference === 0n ? 0 : difference < 0n ? -1 : 1;
}

export function isZero(amount: DecimalString): boolean {
  return toMinor(amount) === 0n;
}

/** "1250000" → "1 250 000" (non-breaking spaces) or "1,250,000" in English. */
export function groupDigits(digits: string, lang: Lang): string {
  return digits.replace(/\B(?=(\d{3})+(?!\d))/g, GROUP[lang]);
}

export function currencyLabel(currency: Currency | string, lang: Lang): string {
  return CURRENCY[currency as Currency]?.[lang].text ?? currency;
}

function withCurrency(number: string, currency: Currency | string, lang: Lang): string {
  const look = CURRENCY[currency as Currency]?.[lang] ?? { text: currency, before: false };
  return look.before ? `${look.text}${number}` : `${number}${NBSP}${look.text}`;
}

/** Number part only: grouping, decimals and sign for the language, no currency. */
export function formatAmount(amount: DecimalString, lang: Lang, options: Omit<MoneyFormat, "bare"> & { currency?: string } = {}): string {
  let minor = toMinor(amount);
  const negative = minor < 0n;
  if (negative) minor = -minor;
  const cents = options.cents ?? DEFAULT_CENTS[options.currency ?? "UZS"] ?? "auto";
  const sign = options.sign ?? "auto";
  const signText = sign === "never" ? "" : negative ? MINUS : sign === "always" && minor > 0n ? "+" : "";

  if (options.compact) return signText + compactNumber(minor, lang);

  let whole = minor / 100n;
  let fraction = minor % 100n;
  if (cents === "never" && fraction > 0n) {
    if (fraction >= 50n) whole += 1n;
    fraction = 0n;
  }
  const showFraction = cents === "always" || (cents === "auto" && fraction > 0n);
  const fractionText = showFraction ? POINT[lang] + String(fraction).padStart(2, "0") : "";
  return signText + groupDigits(String(whole), lang) + fractionText;
}

/** 1 250 000 → "1,3 mln", 250 000 → "250 ming", 950 → "950". One decimal, dropped when zero. */
function compactNumber(minor: bigint, lang: Lang): string {
  const whole = minor / 100n;
  const steps: [bigint, number][] = [
    [1_000_000_000n, 2],
    [1_000_000n, 1],
    [1_000n, 0],
  ];
  for (const [unit, index] of steps) {
    if (whole >= unit) {
      // One decimal, rounded half up, in integer arithmetic.
      const tenths = (whole * 10n + unit / 2n) / unit;
      const integer = tenths / 10n;
      const decimal = tenths % 10n;
      const number = groupDigits(String(integer), lang) + (decimal > 0n ? POINT[lang] + String(decimal) : "");
      const word = COMPACT[lang][index];
      return lang === "en" ? `${number}${word}` : `${number}${NBSP}${word}`;
    }
  }
  return String(whole);
}

/**
 * "1250000.00", "UZS", "uz" → "1 250 000 so‘m"; "-35.5", "USD", "en" → "−$35.50".
 * Empty or missing amounts read as an em dash.
 */
export function formatMoney(
  amount: DecimalString | null | undefined,
  currency: Currency | string,
  lang: Lang,
  options: MoneyFormat = {},
): string {
  if (amount === null || amount === undefined || amount === "") return "—";
  const number = formatAmount(amount, lang, { ...options, currency });
  if (options.bare) return number;
  // The sign goes in front of a leading symbol: "−$35.50", not "$−35.50".
  const signed = /^[+−]/.exec(number);
  const unsigned = signed ? number.slice(1) : number;
  return (signed ? signed[0] : "") + withCurrency(unsigned, currency, lang);
}

/** The pieces of a formatted amount, for layouts that style the currency apart from the number. */
export function moneyParts(
  amount: DecimalString,
  currency: Currency | string,
  lang: Lang,
  options: Omit<MoneyFormat, "bare"> = {},
): { number: string; currency: string; currencyFirst: boolean } {
  const look = CURRENCY[currency as Currency]?.[lang] ?? { text: currency, before: false };
  return { number: formatAmount(amount, lang, { ...options, currency }), currency: look.text, currencyFirst: look.before };
}

/**
 * What a person typed into a money field, as a decimal string, or null when it isn't an amount.
 * Accepts grouping with spaces, commas, dots or apostrophes, and either decimal separator:
 * "1 250 000", "1,250,000.50", "1 250 000,5", "1.250.000", "12500 so‘m".
 */
export function parseMoney(input: string, lang: Lang = "en"): DecimalString | null {
  let text = input.trim().replace(/[\s  '’‘`]/g, "");
  const negative = /^[-−]/.test(text);
  text = text.replace(/^[-−+]/, "").replace(/[^\d.,]/g, "");
  if (!text || !/\d/.test(text)) return null;

  const lastDot = text.lastIndexOf(".");
  const lastComma = text.lastIndexOf(",");
  let decimalAt = -1;
  if (lastDot >= 0 && lastComma >= 0) {
    decimalAt = Math.max(lastDot, lastComma);
  } else if (lastDot >= 0 || lastComma >= 0) {
    const separator = lastDot >= 0 ? "." : ",";
    const at = Math.max(lastDot, lastComma);
    const occurrences = text.split(separator).length - 1;
    const after = text.length - at - 1;
    // One separator followed by one or two digits is a decimal point. Exactly three digits is
    // grouping, except that a lone comma in Russian or Uzbek is always the decimal comma.
    const isDecimal = occurrences === 1 && (after <= 2 || (separator === "," && lang !== "en" && after !== 3));
    if (isDecimal) decimalAt = at;
  }

  const wholeDigits = (decimalAt >= 0 ? text.slice(0, decimalAt) : text).replace(/[.,]/g, "");
  const fractionDigits = decimalAt >= 0 ? text.slice(decimalAt + 1).replace(/[.,]/g, "") : "";
  if (fractionDigits.length > 2) return null;
  const whole = wholeDigits.replace(/^0+(?=\d)/, "") || "0";
  if (whole.length > MAX_INTEGER_DIGITS) return null;
  const fraction = fractionDigits.replace(/0+$/, "");
  const value = fraction ? `${whole}.${fraction}` : whole;
  return negative && /[1-9]/.test(value) ? `-${value}` : value;
}

/**
 * Live grouping while typing: keeps a trailing decimal separator and the decimals typed so far,
 * so "1250000," shows as "1 250 000," and the caret can stay put.
 */
export function formatTyping(raw: DecimalString | "", lang: Lang): string {
  if (!raw) return "";
  const [whole, fraction] = raw.split(".");
  return groupDigits(whole, lang) + (fraction !== undefined ? POINT[lang] + fraction : "");
}

/**
 * Turn whatever is in a money field into the typing state: digits, at most one "." and two
 * decimals, no leading zeros. In English "," is grouping and ignored; in Russian and Uzbek both
 * "," and "." mean the decimal point (phones show either on the number pad).
 */
export function sanitizeTyping(raw: string, lang: Lang, options: { decimals?: boolean; maxDigits?: number } = {}): string {
  const maxDigits = options.maxDigits ?? MAX_INTEGER_DIGITS;
  const decimalChars = lang === "en" ? "." : ".,";
  let whole = "";
  let fraction: string | null = null;
  for (const char of raw) {
    if (char >= "0" && char <= "9") {
      if (fraction === null) {
        if (whole.length < maxDigits) whole += char;
      } else if (fraction.length < 2) fraction += char;
    } else if (options.decimals && fraction === null && decimalChars.includes(char)) {
      fraction = "";
    }
  }
  whole = whole.replace(/^0+(?=\d)/, "");
  if (fraction !== null) return `${whole || "0"}.${fraction}`;
  return whole;
}

/** The decimal string a typing state stands for ("1250000." → "1250000"), or null when empty. */
export function amountFromTyping(value: string): DecimalString | null {
  if (!value) return null;
  const trimmed = value.endsWith(".") ? value.slice(0, -1) : value;
  return isDecimal(trimmed) ? trimmed : null;
}

/** The decimal separator for a language: "." in English, "," in Russian and Uzbek. */
export function decimalPoint(lang: Lang): string {
  return POINT[lang];
}
