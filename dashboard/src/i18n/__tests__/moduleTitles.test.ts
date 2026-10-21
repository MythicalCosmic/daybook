import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { allLanguages, loadModuleTitles } from "@/i18n";
import ruFinance from "@/modules/finance/i18n/ru.json";
import uzFinance from "@/modules/finance/i18n/uz.json";

import { collectModuleTitles } from "../../../scripts/moduleTitles.mjs";

// Vitest runs from the dashboard folder.
const modulesDir = resolve("src/modules");

describe("virtual:module-titles", () => {
  it("holds every module's sidebar titles in all three languages, and nothing else", () => {
    const titles = collectModuleTitles(modulesDir);
    for (const language of ["uz", "ru", "en"] as const) {
      expect(titles[language]["finance.title"]).toBeTruthy();
      expect(titles[language]["finance.nav.accounts"]).toBeTruthy();
      expect(titles[language]["tasks.title"]).toBeTruthy();
    }
    expect(titles.uz["finance.nav.accounts"]).toBe((uzFinance as Record<string, string>)["finance.nav.accounts"]);
    // Page texts stay in the module's own dictionary.
    const all = Object.keys(titles.en).length;
    expect(all).toBeGreaterThan(40);
    expect(all).toBeLessThan(Object.keys(ruFinance).length);
    for (const key of Object.keys(titles.en)) expect(key.split(".")[0]).toMatch(/^[a-z]+$/);
  });

  it("lets the palette match a title in a language whose dictionaries aren't loaded", async () => {
    expect(allLanguages("finance.nav.debts").ru).toBe("finance.nav.debts");
    await loadModuleTitles();
    expect(allLanguages("finance.nav.debts").ru).toBe((ruFinance as Record<string, string>)["finance.nav.debts"]);
  });
});
