/**
 * Uzbek never glues a case ending onto "AI": the rules (R-5) would allow "AIni", but in the
 * dashboard's font a capital I is drawn like an l, so "AIni yoqish" read as "Alni yoqish" on the
 * Turn on AI button and "AIdan so‘rash" as "Aldan so‘rash" in the top bar. The wording uses a
 * postposition ("AI bilan suhbat") or the carrier noun "AI xizmati" instead.
 */
import { describe, expect, it } from "vitest";

import shell from "@/i18n/uz.json";

import ai from "../i18n/uz.json";

const GLUED = /\bAI(?:ni|dan|ga|da|ning|lar|ning|dagi)\b/u;

describe("Uzbek wording around AI", () => {
  it("never glues a case ending onto AI in the module or the shell", () => {
    const glued = [...Object.entries(ai), ...Object.entries(shell)].filter(([, text]) => GLUED.test(String(text)));
    expect(glued).toEqual([]);
  });

  it("calls the chat the same everywhere it is offered", () => {
    expect(ai["ai.nav.ask"]).toBe("AI bilan suhbat");
    expect(ai["ai.chat.title"]).toBe(ai["ai.nav.ask"]);
    expect(shell["shell.topbar.askAi"]).toBe(ai["ai.nav.ask"]);
    expect(ai["ai.turnOn.button"]).toBe("AI xizmatini yoqish");
  });
});
