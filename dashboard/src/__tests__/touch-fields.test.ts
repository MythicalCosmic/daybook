/**
 * Fields on touch screens write at 16 px or more: iOS (Telegram's in-app browser included) zooms the
 * whole page into a field whose text is smaller when it takes focus, and leaves it zoomed. Design
 * system fields get it from `.ui-control` (styles/controls.css); a raw <input> or <textarea> styled
 * with a smaller text size must add `pointer-coarse:text-md`.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const SRC = resolve(dirname(fileURLToPath(import.meta.url)), "..");

function vueFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) return entry === "__tests__" || entry === "dev" ? [] : vueFiles(full);
    return entry.endsWith(".vue") ? [full] : [];
  });
}

describe("fields on touch screens", () => {
  it("write at 16 px through the design system", () => {
    const css = readFileSync(join(SRC, "styles/controls.css"), "utf8");
    expect(css).toMatch(/@media \(pointer: coarse\) \{\s*\.ui-control \{\s*font-size: var\(--text-md\);/);
  });

  it("raw inputs and textareas with small text say so for touch screens too", () => {
    const offenders: string[] = [];
    for (const file of vueFiles(SRC)) {
      const source = readFileSync(file, "utf8");
      for (const match of source.matchAll(/<(input|textarea)\b[^>]*?class="([^"]*)"[^>]*>/gs)) {
        const classes = match[2]!.split(/\s+/);
        const small = classes.some((name) => name === "text-sm" || name === "text-base" || name === "text-xs");
        if (small && !classes.includes("pointer-coarse:text-md")) offenders.push(`${relative(SRC, file)}: ${match[0].slice(0, 80)}`);
      }
    }
    expect(offenders).toEqual([]);
  });
});
