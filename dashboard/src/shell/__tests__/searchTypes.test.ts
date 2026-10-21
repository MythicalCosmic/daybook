// The registry first, as in the app: it is what loads every module's index.ts (see core/modules.ts).
import "@/core/modules";

import { readdirSync, readFileSync, existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { modules } from "@/core/modules";
import en from "@/i18n/en.json";
import ru from "@/i18n/ru.json";
import uz from "@/i18n/uz.json";

import { searchTypeKey, searchTypeKeys } from "../searchTypes";

const APPS = resolve(dirname(fileURLToPath(import.meta.url)), "../../../../backend/apps");

/** Every type the backend registers with `register_search("<type>", …)`, read from the apps' hooks. */
function backendSearchTypes(): string[] {
  const types: string[] = [];
  for (const app of readdirSync(APPS)) {
    const hooks = join(APPS, app, "hooks.py");
    if (!existsSync(hooks)) continue;
    for (const match of readFileSync(hooks, "utf8").matchAll(/register_search\(\s*"([^"]+)"/g)) types.push(match[1]!);
  }
  return types;
}

const dictionaries: Record<string, Record<string, string>> = { en, uz, ru };

describe("search type labels", () => {
  it("tries the whole type, its last part, that part in the plural, then the app", () => {
    expect(searchTypeKeys("finance.counterparty")).toEqual([
      "shell.searchType.finance.counterparty",
      "shell.searchType.counterparty",
      "shell.searchType.counterparties",
      "shell.searchType.finance",
    ]);
    expect(searchTypeKeys("companies.branches")).toContain("shell.searchType.branches");
    expect(searchTypeKeys("sales.shift")).toContain("shell.searchType.shifts");
    expect(searchTypeKeys("people")).toEqual(["shell.searchType.people"]);
  });

  it("names the group of every search type the backend and the modules register, in every language", () => {
    const backend = backendSearchTypes();
    // Sanity: the scan found the W0/W1 providers (a moved file would otherwise pass silently).
    expect(backend).toEqual(expect.arrayContaining(["companies.branches", "members.person", "tasks.task", "finance.transaction"]));
    const rendered = modules.flatMap((m) => Object.keys(m.searchResults ?? {}));
    const missing: string[] = [];
    for (const type of new Set([...backend, ...rendered])) {
      for (const [language, messages] of Object.entries(dictionaries)) {
        if (!searchTypeKey(type, (key) => typeof messages[key] === "string")) missing.push(`${type} (${language})`);
      }
    }
    // Add "shell.searchType.<plural noun>" to src/i18n/{en,uz,ru}.json for each one listed here.
    expect(missing).toEqual([]);
  });

  it("labels branches and calendar events instead of grouping them under Other", () => {
    const has = (key: string) => key in en;
    expect(searchTypeKey("companies.branches", has)).toBe("shell.searchType.branches");
    expect(en["shell.searchType.branches"]).toBe("Branches");
    expect(uz["shell.searchType.branches"]).toBe("Filiallar");
    expect(ru["shell.searchType.branches"]).toBe("Филиалы");
    expect(searchTypeKey("agenda.event", has)).toBe("shell.searchType.events");
  });
});
