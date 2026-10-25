/**
 * The owner's rule (2026-10-25): no emoji characters in the app's texts. Icons are SVG; the app's
 * dictionaries and every feature's, in all three languages, are plain words. Uzbek comes first in
 * the language list.
 */
import { describe, expect, it } from "vitest";

import { DICTIONARIES, LANGUAGES } from ".";

const EMOJI = /[\p{Extended_Pictographic}\u{FE0F}\u{20E3}]/u;
const features = import.meta.glob<Record<string, unknown>>(["../features/*/messages.ts", "../features/*/pageMessages.ts"], { eager: true });

function strings(value: unknown, path: string, out: [string, string][]): [string, string][] {
  if (typeof value === "string") out.push([path, value]);
  else if (value && typeof value === "object") for (const [key, inner] of Object.entries(value)) strings(inner, `${path}.${key}`, out);
  return out;
}

describe("texts", () => {
  it("list O‘zbekcha first", () => {
    expect(LANGUAGES.map((language) => language.name)).toEqual(["O‘zbekcha", "Русский", "English"]);
  });

  it("carry no emoji in the app's dictionaries", () => {
    const found = Object.entries(DICTIONARIES).flatMap(([lang, dictionary]) => strings(dictionary, lang, []).filter(([, text]) => EMOJI.test(text)));
    expect(found).toEqual([]);
  });

  it("carry no emoji in any feature's dictionaries", () => {
    expect(Object.keys(features).length).toBeGreaterThan(3);
    const found = Object.entries(features).flatMap(([file, module]) => strings(module, file, []).filter(([, text]) => EMOJI.test(text)));
    expect(found).toEqual([]);
  });
});
