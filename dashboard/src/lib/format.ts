/** Numbers, percentages, durations, names and phones, per language. Money is in lib/money.ts. */
import type { Language } from "@/api/types";
import { groupDigits, separators } from "@/lib/money";

const NBSP = " ";
const MINUS = "−";

/** "12 345", "12 345,5", "12,345.5". Accepts numbers or decimal strings. */
export function formatNumber(value: number | string | null | undefined, lang: Language, maxDecimals = 0): string {
  if (value === null || value === undefined || value === "") return "—";
  const number = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(number)) return "—";
  const { group, decimal } = separators(lang);
  const fixed = Math.abs(number).toFixed(maxDecimals);
  const [whole, fraction = ""] = fixed.split(".");
  const trimmed = fraction.replace(/0+$/, "");
  const sign = number < 0 && Number(fixed) !== 0 ? MINUS : "";
  return sign + groupDigits(whole!, group) + (trimmed ? decimal + trimmed : "");
}

/** "93%" (uz, en) or "93 %" (ru). `value` is already a percentage (93, not 0.93). */
export function formatPercent(value: number | null | undefined, lang: Language, maxDecimals = 0): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  const number = formatNumber(value, lang, maxDecimals);
  return lang === "ru" ? `${number}${NBSP}%` : `${number}%`;
}

/** Signed percentage for deltas: "+4,2%", "−12%". */
export function formatDelta(value: number | null | undefined, lang: Language, maxDecimals = 1): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  const text = formatPercent(Math.abs(value), lang, maxDecimals);
  if (value > 0) return `+${text}`;
  if (value < 0) return `${MINUS}${text}`;
  return text;
}

const DURATION: Record<Language, { h: string; m: string }> = {
  uz: { h: "soat", m: "daq" },
  ru: { h: "ч", m: "мин" },
  en: { h: "h", m: "m" },
};

/** Minutes as "3h 12m" / "3 soat 12 daq" / "3 ч 12 мин". */
export function formatDuration(minutes: number | null | undefined, lang: Language): string {
  if (minutes === null || minutes === undefined || !Number.isFinite(minutes)) return "—";
  const total = Math.max(0, Math.round(minutes));
  const hours = Math.floor(total / 60);
  const rest = total % 60;
  const unit = DURATION[lang];
  const join = (n: number, u: string) => (lang === "en" ? `${n}${u}` : `${n}${NBSP}${u}`);
  if (hours === 0) return join(rest, unit.m);
  if (rest === 0) return join(hours, unit.h);
  return `${join(hours, unit.h)} ${join(rest, unit.m)}`;
}

/** Badge counts: 0 stays 0, anything above `max` reads "99+". */
export function formatCount(count: number, max = 99): string {
  return count > max ? `${max}+` : String(Math.max(0, Math.floor(count)));
}

/** "Dilnoza Karimova" → "DK"; one word → its first two letters. */
export function initials(name: string | null | undefined): string {
  const words = (name ?? "").trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return "?";
  if (words.length === 1) return words[0]!.slice(0, 2).toUpperCase();
  return (words[0]![0]! + words[words.length - 1]![0]!).toUpperCase();
}

/** Uzbek numbers as people write them: "+998 90 123 45 67". Other numbers come back unchanged. */
export function formatPhone(phone: string | null | undefined): string {
  if (!phone) return "";
  const digits = phone.replace(/\D/g, "");
  if (digits.length === 12 && digits.startsWith("998")) {
    return `+998 ${digits.slice(3, 5)} ${digits.slice(5, 8)} ${digits.slice(8, 10)} ${digits.slice(10)}`;
  }
  return phone;
}

export function capitalize(text: string): string {
  return text ? text[0]!.toLocaleUpperCase() + text.slice(1) : text;
}

/** A stable small integer for a string, to pick avatar and logo colors. */
export function hashIndex(text: string, buckets: number): number {
  let hash = 0;
  for (let i = 0; i < text.length; i++) hash = (hash * 31 + text.charCodeAt(i)) | 0;
  return Math.abs(hash) % buckets;
}
