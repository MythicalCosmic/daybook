import type { Plugin } from "vite";

export type Titles = Record<"uz" | "ru" | "en", Record<string, string>>;
export function collectModuleTitles(modulesDir: string, watch?: (file: string) => void): Titles;
export function moduleTitles(modulesDir: string): Plugin;
