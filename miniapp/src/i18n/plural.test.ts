/** Plural forms: right per language, and cheap enough to call on every row of every list. */
import { afterEach, describe, expect, it, vi } from "vitest";

import { translate } from ".";

afterEach(() => vi.restoreAllMocks());

describe("plurals", () => {
  it("pick each language's form", () => {
    expect(translate("en", "home.late", { count: 1 })).toBe("1 task is late");
    expect(translate("en", "home.late", { count: 3 })).toBe("3 tasks are late");
    expect(translate("ru", "home.late", { count: 1 })).toMatch(/^1 задача/);
    expect(translate("ru", "home.late", { count: 3 })).toMatch(/^3 задачи/);
    expect(translate("ru", "home.late", { count: 5 })).toMatch(/^5 задач /);
  });

  it("build the language's plural rules once, not on every string (a list of 200 rows asks thousands of times)", () => {
    translate("uz", "home.late", { count: 1 });
    const built = vi.spyOn(Intl, "PluralRules");
    for (let count = 0; count < 50; count += 1) {
      translate("uz", "home.late", { count });
      translate("ru", "home.late", { count });
    }
    // Russian was never asked before in this file: its rules are built once, Uzbek's not again.
    expect(built.mock.calls.length).toBeLessThanOrEqual(1);
  });
});
