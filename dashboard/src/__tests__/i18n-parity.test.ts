/**
 * Translations (plan §6.5): uz, ru and en have the same keys, no empty values, the same
 * placeholders, module keys stay in their module's namespace, and Uzbek uses the product's
 * letters: o‘ and g‘ with U+2018, the apostrophe with U+2019 (never ASCII ' or CLDR's ʻ).
 */
import { describe, expect, it } from "vitest";

import { STUB_TITLES, DEV_MESSAGES, stubMessages } from "@/dev/stubMessages";

import en from "../i18n/en.json";
import ru from "../i18n/ru.json";
import uz from "../i18n/uz.json";

type Dict = Record<string, string>;
type Set3 = Record<"uz" | "ru" | "en", Dict>;

const moduleDictionaries = import.meta.glob<{ default: Dict }>("../modules/*/i18n/*.json", { eager: true });

function placeholders(text: string): string[] {
  return [...text.matchAll(/\{(\w+)\}/g)].map((m) => m[1]!).sort();
}

/** Every problem in one set of three dictionaries. */
export function parityProblems(name: string, set: Set3, prefixes: string[]): string[] {
  const problems: string[] = [];
  const keys = new Set([...Object.keys(set.uz), ...Object.keys(set.ru), ...Object.keys(set.en)]);
  for (const key of keys) {
    if (!prefixes.some((prefix) => key.startsWith(prefix))) problems.push(`${name}: "${key}" is outside ${prefixes.join(" / ")}`);
    const values = { uz: set.uz[key], ru: set.ru[key], en: set.en[key] };
    for (const [lang, value] of Object.entries(values)) {
      if (value === undefined) problems.push(`${name}: "${key}" is missing in ${lang}`);
      else if (!value.trim()) problems.push(`${name}: "${key}" is empty in ${lang}`);
    }
    const shapes = Object.values(values).filter((v): v is string => v !== undefined).map((v) => placeholders(v).join(","));
    if (new Set(shapes).size > 1) problems.push(`${name}: "${key}" has different placeholders across languages`);
    const uzValue = values.uz ?? "";
    if (/[oOgG]['`ʻ]/.test(uzValue)) problems.push(`${name}: "${key}" (uz) writes o‘/g‘ with the wrong character`);
    if (/[A-Za-z]'[A-Za-z]/.test(uzValue)) problems.push(`${name}: "${key}" (uz) uses an ASCII apostrophe; use ’ (U+2019)`);
  }
  return problems;
}

describe("parity checker", () => {
  it("catches every kind of problem", () => {
    const problems = parityProblems(
      "fixture",
      {
        en: { "x.a": "Hi {name}", "x.b": "B", "y.c": "C" },
        ru: { "x.a": "Привет {who}", "x.b": " ", "y.c": "C" },
        uz: { "x.a": "Salom {name}", "x.b": "Yo'q", "y.c": "C" },
      },
      ["x."],
    );
    expect(problems).toEqual(
      expect.arrayContaining([
        'fixture: "x.a" has different placeholders across languages',
        'fixture: "x.b" is empty in ru',
        'fixture: "x.b" (uz) writes o‘/g‘ with the wrong character',
        'fixture: "y.c" is outside x.',
      ]),
    );
  });
});

describe("i18n parity", () => {
  it("shell dictionaries match", () => {
    expect(parityProblems("shell", { uz, ru, en }, ["common.", "shell."])).toEqual([]);
  });

  it("module dictionaries match and stay in their namespace", () => {
    const byModule = new Map<string, Partial<Set3>>();
    for (const [path, mod] of Object.entries(moduleDictionaries)) {
      const match = /modules\/([^/]+)\/i18n\/(uz|ru|en)\.json$/.exec(path);
      if (!match) continue;
      const entry = byModule.get(match[1]!) ?? {};
      entry[match[2] as "uz" | "ru" | "en"] = mod.default;
      byModule.set(match[1]!, entry);
    }
    const problems: string[] = [];
    for (const [id, set] of byModule) {
      if (!set.uz || !set.ru || !set.en) {
        problems.push(`${id}: needs uz.json, ru.json and en.json`);
        continue;
      }
      problems.push(...parityProblems(id, set as Set3, [`${id}.`]));
    }
    expect(problems).toEqual([]);
  });

  it("dev placeholder dictionaries match", () => {
    const problems = parityProblems("dev", DEV_MESSAGES, ["dev."]);
    for (const id of Object.keys(STUB_TITLES)) problems.push(...parityProblems(`stub:${id}`, stubMessages(id), [`${id}.`]));
    expect(problems).toEqual([]);
  });
});
