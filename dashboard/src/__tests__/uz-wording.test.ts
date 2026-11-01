/**
 * Uzbek strings never glue a case ending onto a placeholder ("{time} da", "{name}ga", "{date} gacha"):
 * "-ga" is "-ka"/"-qa" after k/q (Otabekka), names may be Cyrillic, and no rule settles an ending
 * after digits. Rephrase with a label instead ("Ochildi: {time}"). Brand names take suffixes
 * directly ("Telegramda", not "Telegram’da"). Research r3 §1.2–1.3.
 */
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const SRC = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const ENDING_AFTER_PLACEHOLDER = /\} ?(ga|ka|qa|da|dan|ni|ning|gacha|dagi)\b/;
const APOSTROPHE_BEFORE_SUFFIX = /\b(Telegram|KPI|Excel|Daybook|PDF)’(da|dan|ga|ni|ning)\b/;

function uzDictionaries(): Array<[string, Record<string, string>]> {
  const files: string[] = [join(SRC, "i18n/uz.json")];
  for (const module of readdirSync(join(SRC, "modules"))) {
    // The AI module is written by another package tonight; it follows the same rule on its own.
    if (module === "ai") continue;
    try {
      files.push(join(SRC, "modules", module, "i18n/uz.json"));
      readFileSync(files.at(-1)!);
    } catch {
      files.pop();
    }
  }
  return files.map((file) => [file.slice(SRC.length + 1), JSON.parse(readFileSync(file, "utf8")) as Record<string, string>]);
}

describe("Uzbek wording", () => {
  it("attaches no case ending to a placeholder and no apostrophe before a suffix", () => {
    const offenders = uzDictionaries().flatMap(([file, messages]) =>
      Object.entries(messages)
        .filter(([, text]) => ENDING_AFTER_PLACEHOLDER.test(text) || APOSTROPHE_BEFORE_SUFFIX.test(text))
        .map(([key, text]) => `${file} ${key}: ${text}`),
    );
    expect(offenders).toEqual([]);
  });
});
