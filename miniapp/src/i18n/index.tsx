import { createContext, useContext, useMemo, type ReactNode } from "react";

import en, { type Key } from "./en";
import ru from "./ru";
import uz from "./uz";

export type Lang = "en" | "ru" | "uz";

export const LANGUAGES: { code: Lang; name: string }[] = [
  { code: "uz", name: "O‘zbekcha" },
  { code: "ru", name: "Русский" },
  { code: "en", name: "English" },
];

const DICTIONARIES: Record<Lang, Partial<Record<string, string>>> = { en, ru, uz };

/** Locale for Intl formatting: 24-hour time and day-before-month everywhere. */
const LOCALES: Record<Lang, string> = { en: "en-GB", ru: "ru-RU", uz: "uz-Latn-UZ" };

type Vars = Record<string, string | number>;
type PluralBase<K> = K extends `${infer Base}_other` ? Base : never;
type PluralKey = PluralBase<Key>;
export type Translate = (key: Key | PluralKey, vars?: Vars) => string;

export function translate(lang: Lang, key: string, vars?: Vars): string {
  const dictionary = DICTIONARIES[lang];
  const fallback = DICTIONARIES.en;
  let template: string | undefined;
  if (typeof vars?.count === "number") {
    const rule = new Intl.PluralRules(LOCALES[lang]).select(vars.count);
    template =
      dictionary[`${key}_${rule}`] ??
      dictionary[`${key}_other`] ??
      fallback[`${key}_${rule}`] ??
      fallback[`${key}_other`];
  }
  template ??= dictionary[key] ?? fallback[key] ?? key;
  return template.replace(/\{(\w+)\}/g, (_, name: string) => String(vars?.[name] ?? ""));
}

type I18n = { lang: Lang; locale: string; t: Translate };

const I18nContext = createContext<I18n | null>(null);

export function I18nProvider({ lang, children }: { lang: Lang; children: ReactNode }) {
  const value = useMemo<I18n>(
    () => ({
      lang,
      locale: LOCALES[lang],
      t: (key, vars) => translate(lang, key, vars),
    }),
    [lang],
  );
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18n {
  const value = useContext(I18nContext);
  if (!value) throw new Error("useI18n outside I18nProvider");
  return value;
}

export function asLang(code: string | undefined): Lang {
  return code === "ru" || code === "uz" || code === "en" ? code : "uz";
}
