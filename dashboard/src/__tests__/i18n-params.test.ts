/**
 * Shared messages with a placeholder are called with it: `common.file.remove` is "Remove {name}",
 * and the receipt buttons called it bare, so they read "Remove " (the name left blank).
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import en from "@/i18n/en.json";

const SRC = resolve(dirname(fileURLToPath(import.meta.url)), "..");

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) return entry === "__tests__" ? [] : sources(full);
    return /\.(ts|vue)$/.test(entry) ? [full] : [];
  });
}

describe("shared messages with placeholders", () => {
  it("are never called without their values", () => {
    const withPlaceholders = Object.entries(en as Record<string, string>)
      .filter(([, text]) => /\{\w+\}/.test(text))
      .map(([key]) => key);
    const bare = sources(SRC).flatMap((file) => {
      const text = readFileSync(file, "utf8");
      return withPlaceholders.filter((key) => text.includes(`t("${key}")`) || text.includes(`t('${key}')`)).map((key) => `${relative(SRC, file)}: ${key}`);
    });
    expect(bare).toEqual([]);
  });
});
