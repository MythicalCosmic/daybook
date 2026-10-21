import { afterEach, describe, expect, it, vi } from "vitest";

import { allLanguages, ensureModuleMessages, i18n, isLanguage, isShellKey, mergeModuleMessages, russianPlural, setLanguage, t } from "@/i18n";
import { defineModule } from "@/core/modules";

afterEach(() => setLanguage("en"));

describe("i18n", () => {
  it("resolves flat keys with dots", () => {
    setLanguage("ru");
    expect(t("shell.inbox.title")).toBe("Входящие");
    expect(t("shell.company.waiting", { n: 3 })).toBe("Ждут вас: 3");
    expect(document.documentElement.lang).toBe("ru");
  });

  it("picks Russian plural forms", () => {
    expect([1, 2, 5, 11, 21, 22, 25, 112].map((n) => russianPlural(n, 3))).toEqual([0, 1, 2, 2, 0, 1, 2, 2]);
    expect(russianPlural(1, 2)).toBe(0);
  });

  it("merges a module's messages only inside its namespace", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    mergeModuleMessages("tasks", {
      en: { "tasks.board.empty": "Nothing here", "finance.oops": "foreign" },
      ru: { "tasks.board.empty": "Пусто" },
      uz: { "tasks.board.empty": "Bo‘sh" },
    });
    setLanguage("uz");
    expect(t("tasks.board.empty")).toBe("Bo‘sh");
    expect(i18n.global.te("finance.oops", "en")).toBe(false);
    expect(warn).toHaveBeenCalled();
  });

  it("loads a module's messages once per language, only the language asked for", async () => {
    const texts = { en: { "kudos.title": "Kudos" }, ru: { "kudos.title": "Благодарности" }, uz: { "kudos.title": "Rahmatlar" } };
    // One JSON module per language, as `import(`./i18n/${language}.json`)` gives it.
    const messages = vi.fn((language: "uz" | "ru" | "en") => Promise.resolve({ default: texts[language] }));
    const module = defineModule({ id: "kudos", group: "people", order: 1, icon: {}, title: "kudos.title", routes: [], messages });
    await Promise.all([ensureModuleMessages(module), ensureModuleMessages(module)]);
    expect(messages).toHaveBeenCalledTimes(1);
    expect(messages).toHaveBeenCalledWith("en");
    expect(allLanguages("kudos.title")).toEqual({ uz: "kudos.title", ru: "kudos.title", en: "Kudos" });
    await ensureModuleMessages(module, "ru");
    expect(messages).toHaveBeenCalledTimes(2);
    expect(allLanguages("kudos.title").ru).toBe("Благодарности");
  });

  it("loads every requested module's new language before switching", async () => {
    let release: () => void = () => undefined;
    const gate = new Promise<void>((resolve) => (release = resolve));
    const texts = { en: { "cheers.title": "Cheers" }, ru: { "cheers.title": "Ура" }, uz: { "cheers.title": "Olqish" } };
    const messages = vi.fn(async (language: "uz" | "ru" | "en") => {
      if (language === "uz") await gate;
      return texts[language];
    });
    const module = defineModule({ id: "cheers", group: "people", order: 1, icon: {}, title: "cheers.title", routes: [], messages });
    await ensureModuleMessages(module, "en");
    const switching = setLanguage("uz");
    // The shell's Uzbek is here (tests preload it) but the module's isn't yet: no switch, no keys.
    expect(i18n.global.locale.value).toBe("en");
    expect(messages).toHaveBeenLastCalledWith("uz");
    release();
    await switching;
    expect(i18n.global.locale.value).toBe("uz");
    expect(t("cheers.title")).toBe("Olqish");
    // Back to a language already loaded: at once.
    void setLanguage("en");
    expect(i18n.global.locale.value).toBe("en");
    // Later tests switch to Russian synchronously.
    await ensureModuleMessages(module, "ru");
  });

  it("a later switch wins over one still loading", async () => {
    let release: () => void = () => undefined;
    const gate = new Promise<void>((resolve) => (release = resolve));
    const messages = vi.fn(async (language: "uz" | "ru" | "en") => {
      if (language === "ru") await gate;
      return { [`slow.title`]: language };
    });
    const module = defineModule({ id: "slow", group: "people", order: 1, icon: {}, title: "slow.title", routes: [], messages });
    await ensureModuleMessages(module, "en");
    await ensureModuleMessages(module, "uz");
    const toRussian = setLanguage("ru");
    await setLanguage("uz");
    release();
    await toRussian;
    expect(i18n.global.locale.value).toBe("uz");
  });

  it("compiles messages without vue-i18n's full compiler: named, list, literal and plural forms", () => {
    mergeModuleMessages("demo", {
      en: { "demo.hi": "Hi, {name}!", "demo.pair": "{0} of {1}", "demo.brace": "Use {'{'}n{'}'} here", "demo.tasks": "{n} task | {n} tasks", "demo.at": "Mail @ {who} for $5" },
      ru: { "demo.hi": "Привет, {name}!", "demo.pair": "{0} из {1}", "demo.brace": "{'{'}n{'}'}", "demo.tasks": "{n} задача | {n} задачи | {n} задач", "demo.at": "@ {who}" },
      uz: { "demo.hi": "Salom, {name}!", "demo.pair": "{1} tadan {0}", "demo.brace": "{'{'}n{'}'}", "demo.tasks": "{n} ta vazifa | {n} ta vazifa", "demo.at": "@ {who}" },
    });
    setLanguage("en");
    expect(t("demo.hi", { name: "Dilnoza" })).toBe("Hi, Dilnoza!");
    expect(i18n.global.t("demo.pair", [3, 5])).toBe("3 of 5");
    expect(t("demo.brace")).toBe("Use {n} here");
    expect(i18n.global.t("demo.tasks", { n: 1 }, 1)).toBe("1 task");
    expect(i18n.global.t("demo.tasks", { n: 4 }, 4)).toBe("4 tasks");
    // "@" and "$" are plain text, never linked-message syntax.
    expect(t("demo.at", { who: "Bekzod" })).toBe("Mail @ Bekzod for $5");
    setLanguage("ru");
    expect([1, 3, 5, 21].map((n) => i18n.global.t("demo.tasks", { n }, n))).toEqual(["1 задача", "3 задачи", "5 задач", "21 задача"]);
  });

  it("loads each language's shell dictionary on demand and switches once it has arrived", async () => {
    // A fresh copy of the module: nothing loaded yet, as in the app before main.ts runs.
    vi.resetModules();
    const fresh = await import("@/i18n");
    expect(fresh.t("shell.inbox.title")).toBe("shell.inbox.title");
    await fresh.setLanguage("ru");
    expect(fresh.currentLanguage()).toBe("ru");
    expect(fresh.t("shell.inbox.title")).toBe("Входящие");
    // Another language: the old one stays until the new dictionary is here.
    const switching = fresh.setLanguage("uz");
    expect(fresh.currentLanguage()).toBe("ru");
    await switching;
    expect(fresh.currentLanguage()).toBe("uz");
    expect(fresh.t("shell.inbox.title")).toBe("Kiruvchilar");
    // A module's keys merged before a shell dictionary survive it (merge, not replace).
    fresh.mergeModuleMessages("kudos", { en: { "kudos.title": "Kudos" }, ru: { "kudos.title": "Благодарности" }, uz: { "kudos.title": "Rahmatlar" } });
    await fresh.loadAllLanguages();
    expect(fresh.allLanguages("shell.inbox.title").en).toBe("Inbox");
    expect(fresh.allLanguages("kudos.title")).toEqual({ uz: "Rahmatlar", ru: "Благодарности", en: "Kudos" });
  });

  it("keeps loading pages in the language on screen when a switch's dictionary fails to arrive", async () => {
    vi.resetModules();
    vi.doMock("@/i18n/ru.json", () => {
      throw new Error("offline");
    });
    try {
      const fresh = await import("@/i18n");
      await fresh.setLanguage("en");
      await expect(fresh.setLanguage("ru")).rejects.toThrow();
      expect(fresh.currentLanguage()).toBe("en");
      const loader = vi.fn(async (language: "uz" | "ru" | "en") => ({ "late.title": `in ${language}` }));
      const late = defineModule({ id: "late", group: "work", order: 1, icon: {}, title: "late.title", routes: [], messages: loader });
      await fresh.ensureModuleMessages(late);
      expect(loader).toHaveBeenCalledWith("en");
      expect(fresh.t("late.title")).toBe("in en");
    } finally {
      vi.doUnmock("@/i18n/ru.json");
      vi.resetModules();
    }
  });

  it("has small guards", () => {
    expect(isLanguage("uz")).toBe(true);
    expect(isLanguage("de")).toBe(false);
    expect(isShellKey("common.save")).toBe(true);
    expect(isShellKey("tasks.title")).toBe(false);
  });
});
