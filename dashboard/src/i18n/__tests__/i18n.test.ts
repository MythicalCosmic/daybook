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

  it("loads a module's messages once", async () => {
    const messages = vi.fn(() => Promise.resolve({ en: { "kudos.title": "Kudos" }, ru: { "kudos.title": "Благодарности" }, uz: { "kudos.title": "Rahmatlar" } }));
    const module = defineModule({ id: "kudos", group: "people", order: 1, icon: {}, title: "kudos.title", routes: [], messages });
    await Promise.all([ensureModuleMessages(module), ensureModuleMessages(module)]);
    expect(messages).toHaveBeenCalledTimes(1);
    expect(allLanguages("kudos.title")).toEqual({ uz: "Rahmatlar", ru: "Благодарности", en: "Kudos" });
  });

  it("has small guards", () => {
    expect(isLanguage("uz")).toBe(true);
    expect(isLanguage("de")).toBe(false);
    expect(isShellKey("common.save")).toBe(true);
    expect(isShellKey("tasks.title")).toBe(false);
  });
});
