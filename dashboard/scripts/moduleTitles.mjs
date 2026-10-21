// Vite plugin behind `virtual:module-titles` (src/i18n/index.ts `loadModuleTitles`): every module's
// titles in uz, ru and en, so the command palette matches a page typed in any language without
// downloading every module's whole dictionaries (they load one language at a time).
//
// A "title" is any key of the module's namespace written as a string in its index.ts: the module's
// name, its sidebar items, settings panels, Person 360 tabs and palette actions. The result is a
// few KB; it is its own chunk and only the palette loads it.
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

const ID = "virtual:module-titles";
const RESOLVED = `\0${ID}`;
const LANGUAGES = ["uz", "ru", "en"];
const KEY = /["'`]([a-z][\w-]*(?:\.[\w-]+)+)["'`]/g;

/** The titles of every module folder under `modulesDir`, per language. */
export function collectModuleTitles(modulesDir, watch = () => undefined) {
  const out = Object.fromEntries(LANGUAGES.map((language) => [language, {}]));
  for (const id of readdirSync(modulesDir).sort()) {
    const index = join(modulesDir, id, "index.ts");
    if (!existsSync(index)) continue;
    watch(index);
    const keys = new Set([...readFileSync(index, "utf8").matchAll(KEY)].map((match) => match[1]).filter((key) => key.startsWith(`${id}.`)));
    for (const language of LANGUAGES) {
      const file = join(modulesDir, id, "i18n", `${language}.json`);
      if (!existsSync(file)) continue;
      watch(file);
      const dictionary = JSON.parse(readFileSync(file, "utf8"));
      for (const key of keys) if (typeof dictionary[key] === "string") out[language][key] = dictionary[key];
    }
  }
  return out;
}

export function moduleTitles(modulesDir) {
  return {
    name: "daybook:module-titles",
    resolveId(id) {
      return id === ID ? RESOLVED : null;
    },
    load(id) {
      if (id !== RESOLVED) return null;
      const titles = collectModuleTitles(modulesDir, (file) => this.addWatchFile(file));
      return `export default ${JSON.stringify(titles)};`;
    },
  };
}
