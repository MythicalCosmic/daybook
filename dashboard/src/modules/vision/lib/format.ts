/** Durations as Ko‘z says them: "2 daq 10 s", "2 мин 10 с", "2 min 10 s"; "1 soat 5 daq". */
import type { Language } from "@/api/types";

const NBSP = " ";

const UNITS: Record<Language, { h: string; m: string; s: string }> = {
  uz: { h: "soat", m: "daq", s: "s" },
  ru: { h: "ч", m: "мин", s: "с" },
  en: { h: "h", m: "min", s: "s" },
};

export function formatSeconds(seconds: number | null | undefined, lang: Language): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return "—";
  const total = Math.max(0, Math.round(seconds));
  const unit = UNITS[lang];
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const part = (n: number, u: string) => `${n}${NBSP}${u}`;
  if (h) return m ? `${part(h, unit.h)} ${part(m, unit.m)}` : part(h, unit.h);
  if (m) return s ? `${part(m, unit.m)} ${part(s, unit.s)}` : part(m, unit.m);
  return part(s, unit.s);
}

/** Whole minutes for settings and hints: "2 daq", "90 s" stays "1 daq 30 s". */
export function formatMinutes(minutes: number | null | undefined, lang: Language): string {
  if (minutes === null || minutes === undefined || !Number.isFinite(minutes)) return "—";
  return formatSeconds(minutes * 60, lang);
}
