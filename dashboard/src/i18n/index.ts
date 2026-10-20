/**
 * vue-i18n setup (plan §6.5). Messages are flat ("tasks.board.empty": "…"): the shell's own
 * dictionaries here, merged with each module's `messages()` when that module is first needed.
 * Keys are namespaced by module id; shell keys use "common." and "shell.".
 */
import { createI18n } from "vue-i18n";

import { LANGUAGES, type Language } from "@/api/types";
import type { DashboardModule, Messages } from "@/core/modules";
import { readStored, writeStored } from "@/lib/storage";

import en from "./en.json";
import ru from "./ru.json";
import uz from "./uz.json";

export type { Language };

/** Russian: one / few / many (1 задача, 2 задачи, 5 задач). */
export function russianPlural(choice: number, choicesLength: number): number {
  if (choicesLength < 3) return choice === 1 ? 0 : 1;
  const n = Math.abs(choice);
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return 0;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return 1;
  return 2;
}

/** English and Uzbek: "one | other" (Uzbek nouns don't change after numbers, both forms read the same). */
function twoFormPlural(choice: number, choicesLength: number): number {
  if (choicesLength === 3) return choice === 0 ? 0 : choice === 1 ? 1 : 2;
  return Math.abs(choice) === 1 ? 0 : 1;
}

export function isLanguage(value: unknown): value is Language {
  return typeof value === "string" && (LANGUAGES as readonly string[]).includes(value);
}

/** Before `me` arrives: the last choice in this browser, else the browser's language, else Uzbek. */
export function initialLanguage(): Language {
  const saved = readStored<Language | null>("language", null, (v): v is Language | null => v === null || isLanguage(v));
  if (saved) return saved;
  const browser = typeof navigator !== "undefined" ? navigator.language.slice(0, 2).toLowerCase() : "uz";
  return isLanguage(browser) ? browser : "uz";
}

export const i18n = createI18n({
  legacy: false,
  globalInjection: true,
  locale: initialLanguage(),
  fallbackLocale: "en",
  messages: { uz, ru, en } as Record<Language, Messages>,
  // Flat keys: a dot is part of the key, never a path.
  messageResolver: (messages, path) => {
    const value = (messages as Record<string, unknown>)[path];
    return typeof value === "string" ? value : null;
  },
  pluralRules: { ru: russianPlural, uz: twoFormPlural, en: twoFormPlural },
  missingWarn: import.meta.env.DEV,
  fallbackWarn: false,
  warnHtmlMessage: false,
});

export const t = (key: string, params?: Record<string, unknown>): string =>
  params ? i18n.global.t(key, params) : i18n.global.t(key);

export function currentLanguage(): Language {
  const locale = i18n.global.locale.value;
  return isLanguage(locale) ? locale : "uz";
}

export function setLanguage(language: Language): void {
  i18n.global.locale.value = language;
  writeStored("language", language);
  if (typeof document !== "undefined") document.documentElement.lang = language;
}

/** Text of `key` in every language, for searching titles in uz, ru and en at once. */
export function allLanguages(key: string): Record<Language, string> {
  const out = {} as Record<Language, string>;
  for (const language of LANGUAGES) {
    const messages = i18n.global.getLocaleMessage(language) as Record<string, unknown>;
    const value = messages[key];
    out[language] = typeof value === "string" ? value : key;
  }
  return out;
}

const SHELL_PREFIXES = ["common.", "shell."];

/** Merges a module's dictionaries; keys outside its namespace are dropped (and reported in dev). */
export function mergeModuleMessages(moduleId: string, messages: Partial<Record<Language, Messages>>): void {
  const prefix = `${moduleId}.`;
  for (const language of LANGUAGES) {
    const source = messages[language] ?? {};
    const accepted: Messages = {};
    for (const [key, value] of Object.entries(source)) {
      if (key.startsWith(prefix)) accepted[key] = value;
      else if (import.meta.env.DEV) console.warn(`[i18n] ${moduleId}: key "${key}" is outside the "${prefix}" namespace`);
    }
    i18n.global.mergeLocaleMessage(language, accepted);
  }
}

const loaded = new Map<string, Promise<void>>();

/** Loads a module's messages once; later calls share the same promise. */
export function ensureModuleMessages(module: DashboardModule): Promise<void> {
  let pending = loaded.get(module.id);
  if (!pending) {
    pending = module
      .messages()
      .then((messages) => mergeModuleMessages(module.id, messages))
      .catch((error: unknown) => {
        loaded.delete(module.id);
        throw error;
      });
    loaded.set(module.id, pending);
  }
  return pending;
}

export function ensureAllModuleMessages(list: readonly DashboardModule[]): Promise<void> {
  return Promise.allSettled(list.map(ensureModuleMessages)).then(() => undefined);
}

export function isShellKey(key: string): boolean {
  return SHELL_PREFIXES.some((prefix) => key.startsWith(prefix));
}
