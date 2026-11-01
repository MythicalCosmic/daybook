/**
 * Helpers every module needs live once. `useCompanyId` was written out in 18 module api.ts files
 * and inline in six more places; it is `@/stores/company`'s now.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const SRC = resolve(dirname(fileURLToPath(import.meta.url)), "..");

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) return entry === "__tests__" ? [] : sources(full);
    return /\.(ts|vue)$/.test(entry) ? [full] : [];
  });
}

describe("one helper, one place", () => {
  it("defines the current company's id once", () => {
    const copies = sources(SRC)
      .filter((file) => !file.includes("/modules/ai/"))
      .filter((file) => {
        const text = readFileSync(file, "utf8");
        return /function useCompanyId\(/.test(text) || /computed\(\(\) => company\.currentId \?\? 0\)/.test(text);
      })
      .map((file) => relative(SRC, file));
    expect(copies).toEqual(["stores/company.ts"]);
  });
});
