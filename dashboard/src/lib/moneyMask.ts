/**
 * The live grouping mask behind MoneyInput (plan §6.3): what the person types becomes grouped text
 * ("1 250 000" / "1,250,000") and the API's decimal string ("1250000.00"), and the caret stays after
 * the same digit. Pure string work on digits: no Number, no parseFloat, so no amount is ever rounded
 * by a float.
 */
import type { Language, Money } from "@/api/types";
import { groupDigits, separators, toCents } from "@/lib/money";

export interface MaskOptions {
  /** Fraction digits the field accepts (0 for so‘m, 2 for dollars). */
  decimals: number;
  /** Allow a leading minus (adjustments, corrections). */
  negative?: boolean;
  /** Whole-number digits accepted (default 15). */
  maxDigits?: number;
}

export interface MaskResult {
  /** What the field shows. */
  text: string;
  /** What the API gets: "1250000.00", or null when there are no digits. */
  value: Money | null;
  /** Where the caret goes in `text`. */
  caret: number;
}

const MINUS_CHARS = /[-−–]/;

/** Characters that mark the decimal point in this language: "." in English, "," or "." otherwise. */
function decimalMarks(lang: Language): string[] {
  return lang === "en" ? ["."] : [",", "."];
}

/**
 * Whether a character counts when locating the caret. Group separators never count, so typing or
 * deleting next to one keeps the caret beside the same digit.
 */
function significant(char: string, lang: Language): boolean {
  return /\d/.test(char) || MINUS_CHARS.test(char) || decimalMarks(lang).includes(char);
}

export function maskMoney(raw: string, caret: number, lang: Language, options: MaskOptions): MaskResult {
  const { decimal, group } = separators(lang);
  const marks = decimalMarks(lang);
  const maxDigits = options.maxDigits ?? 15;

  let negative = false;
  let whole = "";
  let fraction = "";
  let hasMark = false;
  // Significant characters before the caret, counted in the cleaned value.
  let before = 0;

  for (let i = 0; i < raw.length; i++) {
    const char = raw[i]!;
    const beforeCaret = i < caret;
    if (MINUS_CHARS.test(char)) {
      if (options.negative && !negative && whole === "" && !hasMark) {
        negative = true;
        if (beforeCaret) before += 1;
      }
      continue;
    }
    if (marks.includes(char)) {
      if (options.decimals > 0 && !hasMark) {
        hasMark = true;
        if (beforeCaret) before += 1;
      }
      continue;
    }
    if (!/\d/.test(char)) continue;
    if (hasMark) {
      if (fraction.length < options.decimals) {
        fraction += char;
        if (beforeCaret) before += 1;
      }
    } else if (whole.length < maxDigits) {
      whole += char;
      if (beforeCaret) before += 1;
    }
  }

  // Leading zeros go ("007" → "7"), but "0" and "0,5" stay. Count the zeros removed before the caret.
  const trimmed = whole.replace(/^0+(?=\d)/, "");
  const removed = whole.length - trimmed.length;
  if (removed > 0) {
    const signOffset = negative ? 1 : 0;
    before = Math.max(signOffset, before - Math.min(removed, Math.max(0, before - signOffset)));
  }
  whole = trimmed;

  const integerText = whole ? groupDigits(whole, group) : hasMark ? "0" : "";
  const text = (negative ? "−" : "") + integerText + (hasMark ? decimal + fraction : "");

  // Walk the new text to the same number of significant characters.
  let position = 0;
  let seen = 0;
  while (position < text.length && seen < before) {
    if (significant(text[position]!, lang) || text[position] === "−") seen += 1;
    position += 1;
  }
  // "0," was synthesized for a lone mark: keep the caret after the mark.
  if (!whole && hasMark && before > 0) position = Math.max(position, text.indexOf(decimal) + 1);

  const hasDigits = whole !== "" || fraction !== "";
  const value = hasDigits ? `${negative ? "-" : ""}${whole || "0"}.${fraction.padEnd(2, "0").slice(0, 2)}` : null;
  return { text, value: value === "-0.00" ? "0.00" : value, caret: Math.min(position, text.length) };
}

/** The text a field shows for an API value: "1250000.50" → "1 250 000,50" (uz), "1,250,000.50" (en). */
export function moneyToText(value: Money | null | undefined, lang: Language, decimals: number): string {
  const parsed = toCents(value ?? null);
  if (!parsed) return "";
  const { decimal, group } = separators(lang);
  const whole = groupDigits((parsed.cents / 100n).toString(), group);
  const cents = (parsed.cents % 100n).toString().padStart(2, "0");
  // A zero fraction is never shown; a real one always is ("12,50" in a dollar field, "12,5" otherwise).
  let fraction = "";
  if (cents !== "00") fraction = decimals >= 2 ? cents : cents.replace(/0$/, "");
  return (parsed.negative ? "−" : "") + whole + (fraction ? decimal + fraction : "");
}

/** Fraction digits a value carries ("12.50" → 2, "12.00" → 0), so a so‘m field never hides tiyins. */
export function fractionDigits(value: Money | null | undefined): number {
  const parsed = toCents(value ?? null);
  if (!parsed) return 0;
  const cents = parsed.cents % 100n;
  if (cents === 0n) return 0;
  return cents % 10n === 0n ? 1 : 2;
}
