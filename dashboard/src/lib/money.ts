/**
 * Money display (plan §6.3): "1 250 000 so‘m" · "1 250 000 сум" · "UZS 1,250,000", compact
 * "12,5 mln" on small tiles, "≈ $98" hints. Amounts arrive as decimal strings and are formatted with
 * exact integer arithmetic (BigInt cents); nothing here ever goes through a float.
 * For client-side sums use lib/decimal.ts.
 */
import type { Currency, Language, Money } from "@/api/types";

const NBSP = " ";
const MINUS = "−";

export interface Separators {
  group: string;
  decimal: string;
}

export function separators(lang: Language): Separators {
  return lang === "en" ? { group: ",", decimal: "." } : { group: NBSP, decimal: "," };
}

/** An exact amount: sign and absolute value in cents. */
export interface Cents {
  negative: boolean;
  cents: bigint;
}

/** Parses "1250000.50", "-12.345" (rounded half up to cents) or a number. Returns null for junk. */
export function toCents(value: Money | number | null | undefined): Cents | null {
  if (value === null || value === undefined || value === "") return null;
  let text: string;
  if (typeof value === "number") {
    if (!Number.isFinite(value)) return null;
    text = value.toLocaleString("en-US", { useGrouping: false, maximumFractionDigits: 6 });
  } else {
    text = value.trim();
  }
  const match = /^([+-])?(\d*)(?:\.(\d*))?$/.exec(text);
  if (!match || (!match[2] && !match[3])) return null;
  const negative = match[1] === "-";
  const whole = match[2] || "0";
  const fraction = (match[3] ?? "").padEnd(3, "0");
  let cents = BigInt(whole) * 100n + BigInt(fraction.slice(0, 2));
  if (Number(fraction[2]) >= 5) cents += 1n;
  return { negative: negative && cents !== 0n, cents };
}

/** "1234567" → "1 234 567" with the given separator. */
export function groupDigits(digits: string, group: string): string {
  return digits.replace(/\B(?=(\d{3})+(?!\d))/g, group);
}

export type DecimalsMode = "auto" | "always" | "never";

/** The number alone, grouped for the language: "1 250 000", "1 250 000,50", "1,250,000.50". */
export function formatAmount(value: Money | number, lang: Language, decimals: DecimalsMode = "auto"): string {
  const parsed = toCents(value);
  if (!parsed) return "—";
  const { group, decimal } = separators(lang);
  let { cents } = parsed;
  if (decimals === "never") cents = ((cents + 50n) / 100n) * 100n;
  const whole = groupDigits((cents / 100n).toString(), group);
  const fraction = (cents % 100n).toString().padStart(2, "0");
  const showFraction = decimals === "always" || (decimals === "auto" && fraction !== "00");
  return (parsed.negative ? MINUS : "") + whole + (showFraction ? decimal + fraction : "");
}

const CURRENCY_WORD: Record<Currency, Record<Language, string>> = {
  UZS: { uz: "so‘m", ru: "сум", en: "UZS" },
  USD: { uz: "$", ru: "$", en: "$" },
};

export function currencyLabel(currency: Currency, lang: Language): string {
  return CURRENCY_WORD[currency][lang];
}

const COMPACT_UNITS: Record<Language, [thousand: string, million: string, billion: string]> = {
  uz: ["ming", "mln", "mlrd"],
  ru: ["тыс.", "млн", "млрд"],
  en: ["K", "M", "B"],
};

/** "12,5 mln" / "12,5 млн" / "12.5M": one decimal, half up, trailing ",0" dropped. */
export function formatCompact(value: Money | number, lang: Language): string {
  const parsed = toCents(value);
  if (!parsed) return "—";
  const units = COMPACT_UNITS[lang];
  const scales = [1_000_000_000n, 1_000_000n, 1_000n];
  for (let i = 0; i < scales.length; i++) {
    const scale = scales[i]! * 100n; // in cents
    if (parsed.cents < scale && i < scales.length - 1) continue;
    if (parsed.cents < scale) break;
    // Tenths of a unit, rounded half up.
    const tenths = (parsed.cents * 10n + scale / 2n) / scale;
    // 999 950 rounds to 1 000.0 thousand: promote to the next unit up.
    if (tenths >= 10_000n && i > 0) {
      const up = scales[i - 1]! * 100n;
      return compactText(parsed.negative, (parsed.cents * 10n + up / 2n) / up, units[2 - (i - 1)]!, lang);
    }
    return compactText(parsed.negative, tenths, units[2 - i]!, lang);
  }
  return formatAmount(value, lang, "never");
}

function compactText(negative: boolean, tenths: bigint, unit: string, lang: Language): string {
  const { group, decimal } = separators(lang);
  const whole = groupDigits((tenths / 10n).toString(), group);
  const digit = tenths % 10n;
  const number = digit === 0n ? whole : `${whole}${decimal}${digit}`;
  const sign = negative ? MINUS : "";
  return lang === "en" ? `${sign}${number}${unit}` : `${sign}${number}${NBSP}${unit}`;
}

export interface MoneyFormatOptions {
  /** "12,5 mln so‘m" instead of the full amount. */
  compact?: boolean;
  /** "always" adds "+" to positive amounts (deltas, income rows). */
  sign?: "auto" | "always";
  /** "none" prints only the number. */
  currencyDisplay?: "label" | "none";
  /** Default: "auto" for UZS (",50" only when there are tiyins), "always" for USD. */
  decimals?: DecimalsMode;
}

/** `formatMoney("1250000.00", "UZS", "uz")` → "1 250 000 so‘m". */
export function formatMoney(value: Money | number | null | undefined, currency: Currency, lang: Language, options: MoneyFormatOptions = {}): string {
  const parsed = toCents(value ?? null);
  if (!parsed) return "—";
  const decimals = options.decimals ?? (currency === "USD" ? "always" : "auto");
  const body = options.compact ? formatCompact(value as Money | number, lang) : formatAmount(value as Money | number, lang, decimals);
  const unsigned = body.startsWith(MINUS) ? body.slice(1) : body;
  const sign = parsed.negative ? MINUS : options.sign === "always" && parsed.cents > 0n ? "+" : "";
  if (options.currencyDisplay === "none") return sign + unsigned;
  const label = currencyLabel(currency, lang);
  if (currency === "USD") return lang === "en" ? `${sign}$${unsigned}` : `${sign}${unsigned}${NBSP}$`;
  return lang === "en" ? `${sign}${label}${NBSP}${unsigned}` : `${sign}${unsigned}${NBSP}${label}`;
}

/** "≈ $98" / "≈ 1,2 mln so‘m": a rounded hint for an amount already converted by the caller. */
export function formatApprox(converted: Money | number, currency: Currency, lang: Language): string {
  const parsed = toCents(converted);
  if (!parsed) return "";
  const large = parsed.cents >= 10_000_00n;
  return `≈${NBSP}${formatMoney(converted, currency, lang, { compact: large, decimals: "never" })}`;
}

/**
 * Reads what a person typed into a money field: "1 250 000", "1,250,000.50", "1250000,5".
 * Returns the API string ("1250000.50") or null. A lone comma or dot followed by one or two digits
 * at the end is the decimal mark; every other separator is grouping.
 */
export function parseMoneyInput(text: string): Money | null {
  const cleaned = text.replace(/[\s  ']/g, "").replace(/[−–]/g, "-");
  if (!cleaned) return null;
  const match = /^(-)?([\d.,]*?)(?:[.,](\d{1,2}))?$/.exec(cleaned);
  if (!match) return null;
  const whole = (match[2] ?? "").replace(/[.,]/g, "");
  if (!/^\d*$/.test(whole) || (!whole && !match[3])) return null;
  const fraction = (match[3] ?? "").padEnd(2, "0");
  const normalizedWhole = whole.replace(/^0+(?=\d)/, "") || "0";
  return `${match[1] ?? ""}${normalizedWhole}.${fraction}`;
}

/** Sign of an amount without floats: -1, 0 or 1. */
export function moneySign(value: Money | number | null | undefined): -1 | 0 | 1 {
  const parsed = toCents(value ?? null);
  if (!parsed || parsed.cents === 0n) return 0;
  return parsed.negative ? -1 : 1;
}
