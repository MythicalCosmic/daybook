// The first-load budget (plan §6.5, README "Budgets"), measured on a production build:
//
//   npm run build && node scripts/budget.mjs        # exits 1 when over budget
//
// "Initial" is the entry chunk plus everything it imports statically, gzip -9. The shell's
// dictionary for one language (fetched before the first paint) and the Overview page (the company
// index, lazy) are added on top, because a person opening the console downloads all of that.
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { gzipSync } from "node:zlib";

const BUDGET_KB = 180;
const dist = join(dirname(fileURLToPath(import.meta.url)), "..", "dist");
const assets = join(dist, "assets");
const files = readdirSync(assets);
const html = readFileSync(join(dist, "index.html"), "utf8");
const entry = /src="\/dashboard\/assets\/([^"]+\.js)"/.exec(html)[1];
const STATIC_IMPORT = /(?:^|[;\n}])\s*import\s*(?:[^"'();]*?from\s*)?["']\.\/([^"']+\.js)["']/g;

const gz = (file) => gzipSync(readFileSync(join(assets, file)), { level: 9 }).length / 1024;
function closure(starts, seen = new Set()) {
  const stack = [...starts];
  while (stack.length) {
    const file = stack.pop();
    if (seen.has(file)) continue;
    seen.add(file);
    for (const match of readFileSync(join(assets, file), "utf8").matchAll(STATIC_IMPORT)) stack.push(match[1]);
  }
  return seen;
}
const total = (set) => [...set].reduce((sum, file) => sum + gz(file), 0);

const initial = closure([entry]);
const initialKb = total(initial);
const overviewChunk = files.find((f) => f.startsWith("OverviewPage-") && f.endsWith(".js"));
const overviewKb = overviewChunk ? total(closure([overviewChunk], new Set(initial))) - initialKb : 0;
// The shell dictionaries: the {lang}-*.js chunks that hold shell keys.
const dictionaries = Object.fromEntries(
  ["uz", "ru", "en"].map((lang) => {
    const file = files.find((f) => f.startsWith(`${lang}-`) && f.endsWith(".js") && readFileSync(join(assets, f), "utf8").includes('"shell.inbox.title"'));
    return [lang, file ? gz(file) : 0];
  }),
);
const largest = Math.max(...Object.values(dictionaries));

const row = (label, kb) => console.log(`${label.padEnd(44)} ${kb.toFixed(1).padStart(6)} KB`);
row("Initial JS (entry + static imports)", initialKb);
for (const [lang, kb] of Object.entries(dictionaries)) row(`  + shell dictionary (${lang})`, kb);
row("  + Overview page (lazy, the company index)", overviewKb);
const firstLoad = initialKb + largest;
const withOverview = firstLoad + overviewKb;
row("First load (initial + largest dictionary)", firstLoad);
row("Shell + Overview (+ largest dictionary)", withOverview);
console.log(`Budget ${BUDGET_KB} KB: ${withOverview <= BUDGET_KB ? "OK" : "OVER"} (${(BUDGET_KB - withOverview).toFixed(1)} KB left)`);
process.exit(withOverview <= BUDGET_KB ? 0 : 1);
