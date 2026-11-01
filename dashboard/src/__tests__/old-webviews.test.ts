/**
 * The console runs in Telegram's in-app browser, which on older iPhones is Safari before 16.4: a
 * RegExp lookbehind is a SyntaxError there (Markdown record chips used one, so every Markdown view
 * failed on those phones).
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { renderMarkdown } from "@/lib/markdown";

const SRC = resolve(dirname(fileURLToPath(import.meta.url)), "..");

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) return entry === "__tests__" ? [] : sources(full);
    return /\.(ts|vue)$/.test(entry) ? [full] : [];
  });
}

describe("older Telegram webviews", () => {
  it("get no RegExp lookbehind", () => {
    const found = sources(SRC)
      .filter((file) => !file.includes("/modules/ai/"))
      .filter((file) => /\(\?<[!=]/.test(readFileSync(file, "utf8")))
      .map((file) => relative(SRC, file));
    expect(found).toEqual([]);
  });

  it("still turns bare references into chips, and leaves paths and words alone", () => {
    const html = renderMarkdown("Look at task:3 and task:4, not http://x.uz/task:5 or mytask:6.", { base: "/dashboard/c/1", label: (kind, id) => `${kind} #${id}` });
    expect(html).toContain("task #3");
    expect(html).toContain("task #4");
    expect(html).not.toContain("task #5");
    expect(html).not.toContain("task #6");
  });
});
