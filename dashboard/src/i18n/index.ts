/**
 * vue-i18n setup (plan §6.5). Messages are flat ("tasks.board.empty": "…"): the shell's own
 * dictionaries here, merged with each module's `messages(language)` when that module is first
 * needed. Keys are namespaced by module id; shell keys use "common." and "shell.".
 *
 * Everything loads one language at a time. The shell dictionaries (~5–6 KB gzipped each): main.ts
 * loads the person's language before mounting. Module dictionaries: the shell asks for every
 * visible module's in the language being shown, and a module's page waits for its own.
 * `setLanguage` loads the new language of the shell and of every module asked for so far, then
 * switches, so a switch never shows keys. The palette matches page titles in all three languages:
 * it loads the other shell dictionaries and `virtual:module-titles` (every module's titles, one
 * small chunk built by scripts/moduleTitles.mjs) instead of every module's whole dictionaries.
 * Tests have all three shell dictionaries loaded up front (src/test/setup.ts).
 */
import { ref } from "vue";
import { createI18n } from "vue-i18n";

import { LANGUAGES, type Language } from "@/api/types";
import type { DashboardModule, Messages } from "@/core/modules";
import { readStored, writeStored } from "@/lib/storage";

import { compileMessage } from "./compile";

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
  messages: { uz: {}, ru: {}, en: {} } as Record<Language, Messages>,
  // Flat keys: a dot is part of the key, never a path.
  messageResolver: (messages, path) => {
    const value = (messages as Record<string, unknown>)[path];
    return typeof value === "string" ? value : null;
  },
  // The runtime build has no message compiler (vite.config.ts aliases it); this small one covers
  // the syntax the console uses: {named}, {0}, {'literal'} and "one | other" plurals.
  messageCompiler: compileMessage,
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

const SHELL_DICTIONARIES: Record<Language, () => Promise<{ default: Messages }>> = {
  uz: () => import("./uz.json"),
  ru: () => import("./ru.json"),
  en: () => import("./en.json"),
};
const shellLoaded = new Set<Language>();
const shellPending = new Map<Language, Promise<void>>();
/** Bumped when a shell dictionary arrives, so `allLanguages` readers recompute. */
const shellVersion = ref(0);

/** Every module whose messages were asked for: a language switch loads theirs first. */
const requested = new Map<string, DashboardModule>();
/** Module dictionaries by "<module>:<language>": in flight, and merged. */
const modulePending = new Map<string, Promise<void>>();
const moduleLoaded = new Set<string>();
const loadKey = (moduleId: string, language: Language) => `${moduleId}:${language}`;

/** Adds a language's shell dictionary (merged: module keys already there stay). */
export function addShellMessages(language: Language, messages: Messages): void {
  i18n.global.mergeLocaleMessage(language, messages);
  shellLoaded.add(language);
  shellVersion.value++;
}

/** Loads a language's shell dictionary once; later calls share the same promise. */
export function loadLanguage(language: Language): Promise<void> {
  if (shellLoaded.has(language)) return Promise.resolve();
  let pending = shellPending.get(language);
  if (!pending) {
    pending = SHELL_DICTIONARIES[language]()
      .then((module) => addShellMessages(language, module.default))
      .finally(() => shellPending.delete(language));
    shellPending.set(language, pending);
  }
  return pending;
}

/** All three shell dictionaries (the palette matches titles in any language). */
export function loadAllLanguages(): Promise<void> {
  return Promise.all(LANGUAGES.map(loadLanguage)).then(() => undefined);
}

/** The language a switch is loading (or the last one switched to): module dictionaries load in it. */
let target: Language | null = null;

/**
 * Switches the UI language: at once when its dictionaries are already here, else once the shell's
 * and every requested module's have loaded (a module that fails to load doesn't block the switch).
 */
export function setLanguage(language: Language): Promise<void> {
  target = language;
  const apply = () => {
    // A later switch won the race: that one applies its own language.
    if (target !== language) return;
    i18n.global.locale.value = language;
    writeStored("language", language);
    if (typeof document !== "undefined") document.documentElement.lang = language;
  };
  const missing = [...requested.values()].filter((module) => !moduleLoaded.has(loadKey(module.id, language)));
  if (shellLoaded.has(language) && !missing.length) {
    apply();
    return Promise.resolve();
  }
  return Promise.all([loadLanguage(language), ensureAllModuleMessages(missing, language)])
    .then(apply)
    .catch((error: unknown) => {
      // The language never arrived (offline): pages opened from now on load their dictionaries in
      // the language still on screen, not in the one that failed.
      if (target === language) target = null;
      throw error;
    });
}

/** Text of `key` in every language, for searching titles in uz, ru and en at once. */
export function allLanguages(key: string): Record<Language, string> {
  void shellVersion.value;
  const out = {} as Record<Language, string>;
  for (const language of LANGUAGES) {
    const messages = i18n.global.getLocaleMessage(language) as Record<string, unknown>;
    const value = messages[key];
    out[language] = typeof value === "string" ? value : key;
  }
  return out;
}

const SHELL_PREFIXES = ["common.", "shell."];

/**
 * Merges a module's dictionaries (any of the three languages); keys outside its namespace are
 * dropped (and reported in dev). A language merged here counts as loaded for that module.
 */
export function mergeModuleMessages(moduleId: string, messages: Partial<Record<Language, Messages>>): void {
  const prefix = `${moduleId}.`;
  for (const language of LANGUAGES) {
    const source = messages[language];
    if (!source) continue;
    const accepted: Messages = {};
    for (const [key, value] of Object.entries(source)) {
      if (key.startsWith(prefix)) accepted[key] = value;
      else if (import.meta.env.DEV) console.warn(`[i18n] ${moduleId}: key "${key}" is outside the "${prefix}" namespace`);
    }
    i18n.global.mergeLocaleMessage(language, accepted);
    moduleLoaded.add(loadKey(moduleId, language));
  }
}

/** A JSON module (`{ default }`) or a plain dictionary. */
function unwrap(loaded: Messages | { default: Messages }): Messages {
  const inner = (loaded as { default?: unknown }).default;
  return inner && typeof inner === "object" ? (inner as Messages) : (loaded as Messages);
}

/**
 * Loads a module's dictionary in one language (by default the one shown, or the one a switch is
 * loading) once; later calls share the same promise.
 */
export function ensureModuleMessages(module: DashboardModule, language: Language = target ?? currentLanguage()): Promise<void> {
  requested.set(module.id, module);
  const key = loadKey(module.id, language);
  let pending = modulePending.get(key);
  if (!pending) {
    pending = module
      .messages(language)
      .then((messages) => mergeModuleMessages(module.id, { [language]: unwrap(messages) }))
      .catch((error: unknown) => {
        modulePending.delete(key);
        throw error;
      });
    modulePending.set(key, pending);
  }
  return pending;
}

export function ensureAllModuleMessages(list: readonly DashboardModule[], language: Language = target ?? currentLanguage()): Promise<void> {
  return Promise.allSettled(list.map((module) => ensureModuleMessages(module, language))).then(() => undefined);
}

let titlesPending: Promise<void> | null = null;

/**
 * Every module's page and action titles in all three languages (one small chunk), so the palette
 * matches a title typed in any language without loading every module's whole dictionaries.
 */
export function loadModuleTitles(): Promise<void> {
  titlesPending ??= import("virtual:module-titles")
    .then(({ default: titles }) => {
      // Same texts as the full dictionaries, so merging over a loaded language changes nothing.
      for (const language of LANGUAGES) i18n.global.mergeLocaleMessage(language, titles[language] ?? {});
      shellVersion.value++;
    })
    .catch((error: unknown) => {
      titlesPending = null;
      throw error;
    });
  return titlesPending;
}

export function isShellKey(key: string): boolean {
  return SHELL_PREFIXES.some((prefix) => key.startsWith(prefix));
}
