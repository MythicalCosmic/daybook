/** Rules for the app's style sheets that a phone inside Telegram needs. */
import { readdirSync, readFileSync } from "node:fs";
import { join, relative } from "node:path";

import { describe, expect, it } from "vitest";

// Read from disk (the runner hands CSS imports over empty); tests run from the mini app folder.
const SRC = join(process.cwd(), "src");
const files = (dir: string): string[] =>
  readdirSync(dir, { withFileTypes: true }).flatMap((entry) => (entry.isDirectory() ? files(join(dir, entry.name)) : [join(dir, entry.name)]));
const sheets = Object.fromEntries(
  files(SRC)
    .filter((path) => path.endsWith(".css"))
    .map((path) => [relative(SRC, path), readFileSync(path, "utf8")]),
);

type Rule = { selector: string; within: string[]; declarations: string };

/** Every selector with its declarations and the at-rules around it ("@media (hover: hover)"). */
function rules(css: string): Rule[] {
  const found: Rule[] = [];
  const stack: string[] = [];
  let open: Rule[] = [];
  let text = "";
  for (const char of css.replace(/\/\*[\s\S]*?\*\//g, "")) {
    if (char === "{") {
      const head = text.trim();
      if (head.startsWith("@")) stack.push(head);
      else {
        open = head.split(",").map((selector) => ({ selector: selector.trim(), within: [...stack], declarations: "" }));
        stack.push("rule");
      }
      text = "";
    } else if (char === "}") {
      if (stack.pop() === "rule") {
        for (const rule of open) found.push({ ...rule, declarations: text.trim() });
        open = [];
      }
      text = "";
    } else {
      text += char;
    }
  }
  return found;
}

const all = Object.entries(sheets).flatMap(([path, css]) => rules(css).map((rule) => ({ path, ...rule })));
const declarationsOf = (selector: string) => all.filter((rule) => rule.selector === selector).map((rule) => rule.declarations).join(";");

describe("style sheets", () => {
  it("are all found", () => {
    expect(Object.keys(sheets)).toEqual(expect.arrayContaining(["styles/app.css", "ui/ui.css"]));
    expect(sheets["styles/app.css"].length).toBeGreaterThan(10_000);
  });

  it("style hover only where there is a mouse: a tap on a phone leaves no row or button looking pressed", () => {
    const stuck = all
      .filter(({ selector, within }) => selector.includes(":hover") && !within.some((at) => /^@media[^{]*\(hover:\s*hover\)/.test(at)))
      .map(({ path, selector }) => `${path}: ${selector}`);
    expect(stuck).toEqual([]);
  });

  it("give buttons a finger's width: 40 px at least", () => {
    const px = (selector: string, property: string) => {
      const match = new RegExp(`(?:^|;)\\s*${property}:\\s*(\\d+)px`).exec(declarationsOf(selector));
      return match ? Number(match[1]) : 0;
    };
    // Every pill button (a lone line of text came to 36 px), the quick-add "Not a date", and the
    // banknote steppers of the till.
    expect(px(".btn", "min-height")).toBeGreaterThanOrEqual(40);
    expect(px(".qa-read-undo", "min-height")).toBeGreaterThanOrEqual(40);
    expect(px(".ui-stepper--sm .ui-stepper-btn", "width")).toBeGreaterThanOrEqual(40);
    expect(px(".ui-stepper--sm .ui-stepper-btn", "height")).toBeGreaterThanOrEqual(40);
    expect(px(".ui-stepper--sm .ui-stepper-input", "height")).toBeGreaterThanOrEqual(40);
  });

  it("give calendar days a finger's width", () => {
    // The calendar's week strip: only the seven days in the row (with the two arrows in it too,
    // a day was 32 px wide on a 360 px phone).
    expect(declarationsOf(".agm-week")).toMatch(/grid-template-columns:\s*repeat\(7, minmax\(0, 1fr\)\);/);
    // The attendance month: a day is 36-39 px with 6 px between days; a tap in between lands on
    // the nearer day instead of nowhere.
    expect(declarationsOf(".att-cal")).toMatch(/gap:\s*6px/);
    expect(declarationsOf("button.att-cal-day::before")).toMatch(/inset:\s*-3px/);
  });

  it("put the till's Open shift button under its words on a phone, not beside them", () => {
    // Beside them, Russian read "Касса / закрыта" and "Пересчита…" on a 390 px phone.
    expect(declarationsOf(".kassa-hero--closed")).toMatch(/container-type:\s*inline-size/);
    const narrow = all.find((rule) => rule.selector === ".kassa-hero-cta" && rule.within.some((at) => at.startsWith("@container")));
    expect(narrow?.declarations).toMatch(/grid-column:\s*2 \/ -1/);
  });

  it("keep the recorder's Cancel and Done in sight on a short phone", () => {
    // At 360 × 740 in Telegram the stage and the example pushed both below the fold while recording.
    const buttons = declarationsOf(".ai-rec-buttons");
    expect(buttons).toMatch(/position:\s*sticky/);
    // Stuck at the sheet's own foot, as a sheet's action bar is (past its bottom padding).
    expect(buttons).toMatch(/bottom:\s*calc\(-1 \* \(var\(--bottom-inset\) \+ 32px\)\)/);
    expect(buttons).toMatch(/background:\s*var\(--color-bg\)/);
  });

  it("keep the offline pill on one line and the screens clear of it", () => {
    const pill = declarationsOf(".offline-banner");
    // Placed at left: 50%, the box could only grow to half the screen: the sentence broke in two.
    expect(pill).not.toMatch(/left:\s*50%/);
    expect(pill).toMatch(/width:\s*fit-content/);
    // While it shows, every screen's top inset grows by its height, so it covers no title.
    expect(declarationsOf(".app:has(> .offline-banner)")).toMatch(/--top-inset:/);
  });
});
