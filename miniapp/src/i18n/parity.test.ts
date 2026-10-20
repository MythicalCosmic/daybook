/**
 * Every dictionary pair agrees: the app's own (en, ru, uz) and every feature folder's. Same keys,
 * no empty strings, the same {placeholders}, the plural forms each language needs, and Uzbek
 * written with ‘ (o‘, g‘) and ’ (the apostrophe) rather than ASCII quotes.
 */
import { describe, expect, it } from "vitest";

import { features } from "../features/registry";
import en from "./en";
import ru from "./ru";
import uz from "./uz";
import { LOCALES, type Dictionary, type Lang } from ".";

/** Words that stay the same in every language and fall back to English on purpose. */
const SAME_EVERYWHERE = new Set(["app.name"]);

const PLURAL = /_(zero|one|two|few|many|other)$/;
const base = (key: string) => key.replace(PLURAL, "");
const placeholders = (text: string) => [...text.matchAll(/\{(\w+)\}/g)].map((match) => match[1]).sort();

type Dictionaries = Record<Lang, Dictionary>;

/** Everything wrong with a set of dictionaries, as readable lines (empty when all is well). */
export function parityProblems(name: string, dictionaries: Dictionaries, sameEverywhere: ReadonlySet<string> = new Set()): string[] {
  const problems: string[] = [];
  const langs = Object.keys(dictionaries) as Lang[];
  const keysOf = (lang: Lang) => new Set(Object.keys(dictionaries[lang]).map(base));
  const english = keysOf("en");

  for (const lang of langs) {
    const keys = keysOf(lang);
    for (const key of english) if (!keys.has(key) && !sameEverywhere.has(key)) problems.push(`${name}/${lang}: missing "${key}"`);
    for (const key of keys) if (!english.has(key)) problems.push(`${name}/${lang}: "${key}" is not in English`);
    for (const [key, value] of Object.entries(dictionaries[lang])) {
      if (!value || !value.trim()) problems.push(`${name}/${lang}: "${key}" is empty`);
    }
  }

  // Plural keys need every form the language uses (Russian: one, few, many, other).
  const plurals = new Set(Object.keys(dictionaries.en).filter((key) => PLURAL.test(key)).map(base));
  for (const lang of langs) {
    const categories = new Intl.PluralRules(LOCALES[lang]).resolvedOptions().pluralCategories;
    for (const key of plurals) {
      if (sameEverywhere.has(key)) continue;
      // Wording that doesn't change with the number ("с опозданием: {count}") may give only
      // _one and _other: the missing forms fall back to _other, which reads the same.
      const forms = Object.entries(dictionaries[lang]).filter(([entry]) => base(entry) === key && PLURAL.test(entry));
      if (dictionaries[lang][`${key}_other`] !== undefined && new Set(forms.map(([, value]) => value)).size === 1) continue;
      for (const category of categories) {
        if (dictionaries[lang][`${key}_${category}`] === undefined) problems.push(`${name}/${lang}: "${key}" needs the _${category} form`);
      }
    }
  }

  // Same placeholders in every language and every plural form.
  for (const key of english) {
    const reference = new Set<string>();
    for (const [entry, value] of Object.entries(dictionaries.en)) if (base(entry) === key && value) placeholders(value).forEach((p) => reference.add(p));
    for (const lang of langs) {
      for (const [entry, value] of Object.entries(dictionaries[lang])) {
        if (base(entry) !== key || !value) continue;
        const found = placeholders(value);
        const expected = [...reference].sort();
        // A plural form may leave {count} out ("one task"), but must not invent or lose others.
        const relevant = found.filter((p) => p !== "count");
        const wanted = expected.filter((p) => p !== "count");
        if (relevant.join() !== wanted.join()) problems.push(`${name}/${lang}: "${entry}" has {${found.join("}, {")}} but English has {${expected.join("}, {")}}`);
      }
    }
  }

  // Uzbek Latin: o‘ and g‘ with U+2018, the apostrophe with U+2019, never ASCII quotes.
  for (const [key, value] of Object.entries(dictionaries.uz)) {
    if (!value) continue;
    if (/[`']/.test(value)) problems.push(`${name}/uz: "${key}" uses an ASCII quote; write ‘ in o‘/g‘ and ’ for the apostrophe`);
    if (/[oOgG][’ʻʼ]/.test(value)) problems.push(`${name}/uz: "${key}" spells o‘/g‘ with the wrong mark; use ‘ (U+2018)`);
  }
  return problems;
}

describe("dictionary parity", () => {
  it("holds for the app's own dictionaries", () => {
    expect(parityProblems("app", { en, ru, uz }, SAME_EVERYWHERE)).toEqual([]);
  });

  it("holds for every feature folder", () => {
    for (const feature of features) expect(parityProblems(feature.id, feature.messages)).toEqual([]);
  });

  it("catches what it is meant to catch", () => {
    const problems = parityProblems("sample", {
      en: { title: "Pay", "items_one": "{count} item", "items_other": "{count} items", hello: "Hi {name}", gone: "Gone" },
      ru: { title: "", "items_one": "{count} штука", "items_other": "{count} штуки", hello: "Привет {first}", extra: "Лишнее", gone: "Нет" },
      uz: { title: "Maosh", "items_one": "{count} ta", "items_other": "{count} ta", hello: "Salom {name}", gone: "Yo'q" },
    });
    expect(problems).toEqual(
      expect.arrayContaining([
        'sample/ru: "extra" is not in English',
        'sample/ru: "title" is empty',
        'sample/ru: "items" needs the _few form',
        'sample/ru: "items" needs the _many form',
        'sample/ru: "hello" has {first} but English has {name}',
        'sample/uz: "gone" uses an ASCII quote; write ‘ in o‘/g‘ and ’ for the apostrophe',
      ]),
    );
    expect(parityProblems("sample", { en: { a: "A", b: "B" }, ru: { a: "А" }, uz: { a: "A", b: "Bo’q" } })).toEqual([
      'sample/ru: missing "b"',
      'sample/uz: "b" spells o‘/g‘ with the wrong mark; use ‘ (U+2018)',
    ]);
  });
});
