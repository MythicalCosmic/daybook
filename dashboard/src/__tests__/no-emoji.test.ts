// The owner's rule (2026-10-25): no emoji characters in the dashboard's texts. Icons are SVG
// components; every dictionary, the shell's and each module's, in all three languages, is plain.
import { describe, expect, it } from "vitest";

const EMOJI = /[\p{Extended_Pictographic}\u{FE0F}\u{20E3}]/u;
const dictionaries = import.meta.glob<Record<string, string>>(["../i18n/*.json", "../modules/*/i18n/*.json"], { eager: true, import: "default" });

describe("dictionaries", () => {
  it("are all found", () => {
    expect(Object.keys(dictionaries).length).toBeGreaterThan(30);
  });

  it("carry no emoji in any language", () => {
    const found = Object.entries(dictionaries).flatMap(([file, messages]) =>
      Object.entries(messages)
        .filter(([, text]) => typeof text === "string" && EMOJI.test(text))
        .map(([key, text]) => `${file} ${key}: ${text}`),
    );
    expect(found).toEqual([]);
  });
});
