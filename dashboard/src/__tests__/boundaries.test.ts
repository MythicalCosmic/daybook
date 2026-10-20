/**
 * Module boundaries (plan §6.6): files under modules/<x>/ may import only from @/components,
 * @/lib, @/api, @/core, @/stores, @/i18n, their own folder and npm packages — never from another
 * module, the shell, the app wiring or dev tooling. The design system stays independent too.
 * Cross-module needs go through the registry or plain links.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, normalize, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const SRC = resolve(dirname(fileURLToPath(import.meta.url)), "..");

const MODULE_ALLOWED = ["@/components", "@/lib", "@/api", "@/core", "@/stores", "@/i18n"];
const COMPONENTS_ALLOWED = ["@/components", "@/lib", "@/api", "@/core", "@/stores", "@/i18n"];

function walk(dir: string): string[] {
  let out: string[] = [];
  let entries: string[] = [];
  try {
    entries = readdirSync(dir);
  } catch {
    return out;
  }
  for (const entry of entries) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) out = out.concat(walk(full));
    else if (/\.(ts|vue)$/.test(entry)) out.push(full);
  }
  return out;
}

/** Every import specifier in a file: static, dynamic, re-exports and side-effect imports. */
export function importsOf(source: string): string[] {
  const found = new Set<string>();
  const patterns = [
    /\bimport\s+(?:type\s+)?[^"'`]*?\bfrom\s*["']([^"']+)["']/g,
    /\bexport\s+(?:type\s+)?[^"'`]*?\bfrom\s*["']([^"']+)["']/g,
    /\bimport\s*["']([^"']+)["']/g,
    /\bimport\s*\(\s*["']([^"']+)["']\s*\)/g,
  ];
  for (const pattern of patterns) for (const match of source.matchAll(pattern)) found.add(match[1]!);
  return [...found];
}

/**
 * Violations for one file. `root` is the folder the file must not leave with relative imports
 * (its module folder), `allowed` the @/ prefixes it may use.
 */
export function violations(file: string, source: string, root: string, allowed: string[]): string[] {
  const problems: string[] = [];
  for (const specifier of importsOf(source)) {
    if (specifier.startsWith("@/")) {
      const ok = allowed.some((prefix) => specifier === prefix || specifier.startsWith(`${prefix}/`));
      const own = specifier.startsWith(`@/${relative(SRC, root).split("\\").join("/")}/`);
      if (!ok && !own) problems.push(`${relative(SRC, file)} imports ${specifier}`);
    } else if (specifier.startsWith(".")) {
      const target = normalize(join(dirname(file), specifier));
      if (!target.startsWith(root)) problems.push(`${relative(SRC, file)} reaches outside its folder: ${specifier}`);
    }
  }
  return problems;
}

describe("import scanner", () => {
  const root = join(SRC, "modules", "finance");
  const file = join(root, "pages", "Transactions.vue");

  it("finds every kind of import", () => {
    const source = `
      import { ref } from "vue";
      import type { Page } from "@/api/types";
      import Thing, { other } from '../components/Thing.vue';
      export { x } from "./x";
      import "./side-effect.css";
      const lazy = () => import("@/shell/AppShell.vue");
    `;
    expect(importsOf(source).sort()).toEqual(["../components/Thing.vue", "./side-effect.css", "./x", "@/api/types", "@/shell/AppShell.vue", "vue"].sort());
  });

  it("allows the shared layers, the module's own folder and packages", () => {
    const source = `import UiButton from "@/components/UiButton.vue"; import { qk } from "@/api/keys";
      import { useForm } from "@/lib/useForm"; import { z } from "zod"; import Row from "../components/Row.vue";
      import { listTransactions } from "@/modules/finance/api";`;
    expect(violations(file, source, root, MODULE_ALLOWED)).toEqual([]);
  });

  it("refuses other modules, the shell, the app and dev tooling", () => {
    const source = `import { useShifts } from "@/modules/sales/api"; import AppShell from "@/shell/AppShell.vue";
      import { createAppRouter } from "@/app/router"; import { installMock } from "@/dev/mock";
      import Shift from "../../sales/components/Shift.vue";`;
    expect(violations(file, source, root, MODULE_ALLOWED)).toHaveLength(5);
  });
});

describe("boundaries", () => {
  it("modules import only from shared layers and their own folder", () => {
    const problems: string[] = [];
    const modulesDir = join(SRC, "modules");
    let folders: string[] = [];
    try {
      folders = readdirSync(modulesDir).filter((name) => statSync(join(modulesDir, name)).isDirectory());
    } catch {
      folders = [];
    }
    for (const folder of folders) {
      const root = join(modulesDir, folder);
      for (const file of walk(root)) problems.push(...violations(file, readFileSync(file, "utf8"), root, MODULE_ALLOWED));
    }
    expect(problems).toEqual([]);
  });

  it("the design system doesn't depend on the shell, the app, modules or dev tooling", () => {
    const root = join(SRC, "components");
    const problems = walk(root).flatMap((file) => violations(file, readFileSync(file, "utf8"), root, COMPONENTS_ALLOWED));
    expect(problems).toEqual([]);
  });

  it("nothing outside src/dev and main.ts imports the dev tooling", () => {
    const problems = walk(SRC)
      .filter((file) => !file.startsWith(join(SRC, "dev")) && !file.includes("__tests__") && !file.endsWith("main.ts"))
      .filter((file) => importsOf(readFileSync(file, "utf8")).some((s) => s.startsWith("@/dev") || /(^|\/)dev\//.test(s)))
      .map((file) => relative(SRC, file));
    expect(problems).toEqual([]);
  });

  it("main.ts loads the dev tooling only behind import.meta.env.DEV", () => {
    const main = readFileSync(join(SRC, "main.ts"), "utf8");
    const guard = main.indexOf("import.meta.env.DEV");
    expect(guard).toBeGreaterThan(-1);
    expect(main.indexOf('import("./dev/mock")')).toBeGreaterThan(guard);
    expect(main).not.toMatch(/^import .*["']\.\/dev\//m);
  });
});
