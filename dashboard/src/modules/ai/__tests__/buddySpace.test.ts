// The registry first, as in the app: it is what loads every module's index.ts (see core/modules.ts).
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { defineComponent, h } from "vue";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { mergeModuleMessages } from "@/i18n";
import { json } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

import AiBuddyStage from "../components/AiBuddyStage.vue";
import BuddyCompanion from "../components/BuddyCompanion.vue";
import { buddyEverywhere } from "../components/buddyPrefs";
import { dockedBars, dockedPart, overlayOpen, pressableBoxes, spotClear } from "../components/buddySpace";
import en from "../i18n/en.json";
import { buddyBox, figureBox, floorAt, overlaps, spotsFrom } from "../lib";

function reducedMotion(on: boolean): void {
  document.documentElement.dataset.motion = on ? "reduced" : "full";
}

function rect(left: number, top: number, width: number, height: number): DOMRect {
  return { left, top, width, height, right: left + width, bottom: top + height, x: left, y: top, toJSON: () => ({}) } as DOMRect;
}

/** Elements say where they are with `data-rect="left,top,width,height"`; `main` fills the window. */
function layout(): void {
  vi.spyOn(Element.prototype, "getBoundingClientRect").mockImplementation(function (this: Element) {
    const spec = (this as HTMLElement).dataset?.rect;
    if (spec) {
      const [left, top, width, height] = spec.split(",").map(Number) as [number, number, number, number];
      return rect(left, top, width, height);
    }
    if (this.tagName === "MAIN") return rect(0, 0, 1024, 768);
    return rect(0, 0, 0, 0);
  });
}

beforeEach(() => {
  mergeModuleMessages("ai", { en, ru: en, uz: en });
  reducedMotion(false);
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

describe("keeping clear: the arithmetic", () => {
  it("covers its body and props, not the shadow under its feet", () => {
    const { feet } = buddyBox(60);
    expect(figureBox(100, 200, 60)).toEqual({ left: 104, top: 200, width: 52, height: feet - 2 });
  });

  it("counts an overlap only past a margin", () => {
    const a = { left: 0, top: 0, width: 50, height: 50 };
    expect(overlaps(a, { left: 48, top: 10, width: 20, height: 20 })).toBe(false); // 2 px: touching
    expect(overlaps(a, { left: 40, top: 10, width: 20, height: 20 })).toBe(true);
    expect(overlaps(a, { left: 10, top: 60, width: 20, height: 20 })).toBe(false);
  });

  it("tries the nearest places first, both ways, and both ends last", () => {
    expect(spotsFrom(100, 0, 200, 50)).toEqual([100, 150, 50, 200, 0]);
    expect(spotsFrom(500, 0, 120, 50)).toEqual([120, 70, 20, 0]); // kept inside, then down to the end
    expect(spotsFrom(10, 10, 10)).toEqual([10]);
  });

  it("stands up on a bar docked above the floor, and on the floor beside it", () => {
    const bars = [{ left: 200, top: 700, width: 400, height: 56 }];
    expect(floorAt(758, bars, 300, 60)).toBe(700);
    expect(floorAt(758, bars, 160, 60)).toBe(700); // half on it is on it
    expect(floorAt(758, bars, 100, 60)).toBe(758);
    expect(floorAt(758, [...bars, { left: 250, top: 640, width: 100, height: 50 }], 300, 60)).toBe(640);
  });
});

describe("keeping clear: what is on the page", () => {
  it("knows what one presses, and leaves itself out", () => {
    layout();
    document.body.innerHTML = '<main><button data-rect="100,700,80,40">Save</button><a href="/x" data-rect="0,0,0,0">gone</a><div id="mine"><button data-rect="10,10,20,20">me</button></div></main>';
    const mine = document.getElementById("mine");
    expect(pressableBoxes(mine)).toEqual([{ left: 100, top: 700, width: 80, height: 40 }]);
    expect(spotClear({ left: 120, top: 690, width: 52, height: 48 }, mine)).toBe(false);
    expect(spotClear({ left: 300, top: 690, width: 52, height: 48 }, mine)).toBe(true);
    // Off the window is never a place to stand.
    expect(spotClear({ left: 1000, top: 690, width: 52, height: 48 }, mine)).toBe(false);
  });

  it("sees an open dialog, sheet or drawer", () => {
    layout();
    document.body.innerHTML = '<div role="dialog" data-rect="0,0,0,0"></div>';
    expect(overlayOpen()).toBe(false); // mounted but closed (nothing drawn)
    document.body.innerHTML = '<div role="dialog" data-rect="100,100,400,300"></div>';
    expect(overlayOpen()).toBe(true);
  });

  it("finds the drawn part of a bar docked to the bottom, under a sticky wrapper", () => {
    layout();
    document.body.innerHTML = '<main><div id="wrap" style="position: sticky" data-rect="0,690,1024,60"><div id="bar" style="background-color: rgb(255, 255, 255)" data-rect="200,694,600,52"><span id="text">Unsaved</span></div></div></main>';
    const text = document.getElementById("text")!;
    expect(dockedPart(text)).toEqual({ left: 200, top: 694, width: 600, height: 52 });
    // Beside the bar the wrapper draws nothing: not a bar there.
    expect(dockedPart(document.getElementById("wrap")!)).toBeNull();
    // jsdom draws nothing: what is at a point, as a browser would say it.
    (document as Document & { elementsFromPoint: (x: number, y: number) => Element[] }).elementsFromPoint = (x: number) => (x >= 200 && x <= 800 ? [text] : []);
    try {
      expect(dockedBars(758, 0, 1024, null)).toEqual([{ left: 200, top: 694, width: 600, height: 52 }]);
      // Its drawing over the bar is never clear, beside it it is.
      expect(spotClear({ left: 400, top: 660, width: 52, height: 48 }, null)).toBe(false);
      expect(spotClear({ left: 900, top: 660, width: 52, height: 48 }, null)).toBe(true);
    } finally {
      delete (document as Partial<Document>).elementsFromPoint;
    }
  });
});

describe("Claude on every page keeps clear", () => {
  async function page(html = "", random = 0.99) {
    vi.useFakeTimers();
    vi.spyOn(Math, "random").mockReturnValue(random); // 0.99: in place, never off on a walk by itself
    vi.stubGlobal("fetch", vi.fn(async () => json({ enabled: true, can_configure: true, claude: "connected", speech: "ready", features: {}, budget: null })));
    layout();
    const main = document.createElement("main");
    main.innerHTML = html;
    document.body.append(main);
    buddyEverywhere.value = true;
    const app = await testApp("/c/1/tasks");
    const { wrapper } = mountWithProviders(BuddyCompanion, { plugins: app.plugins });
    await vi.advanceTimersByTimeAsync(50);
    await flushPromises();
    const walker = () => wrapper.find('[data-testid="ai-buddy-walker"]');
    const layer = () => wrapper.find('[data-testid="ai-buddy-companion"]');
    const at = () => {
      const match = /translate\((-?\d+)px, (-?\d+)px\)/.exec(walker().attributes("style") ?? "");
      return { x: Number(match?.[1]), y: Number(match?.[2]) };
    };
    return { wrapper, walker, layer, at, main };
  }

  function covers(spot: { x: number; y: number }, box: { left: number; top: number; width: number; height: number }): boolean {
    return overlaps(figureBox(spot.x, spot.y, 60), box);
  }

  it("never stands over a button on the floor, and walks to the free part", async () => {
    // The left 600 px of the floor are a row of buttons (a composer, a save bar's buttons).
    const row = { left: 0, top: 690, width: 600, height: 78 };
    // Its first choice (a random 0.3 of the floor) is over the buttons.
    const { walker, at } = await page(`<button data-rect="${row.left},${row.top},${row.width},${row.height}">Send</button>`, 0.3);
    await vi.advanceTimersByTimeAsync(3300);
    expect(walker().find("[data-walking]").exists()).toBe(false);
    expect(covers(at(), row)).toBe(false);
    expect(at().x).toBeGreaterThanOrEqual(600);
    expect(walker().classes()).toContain("pointer-events-auto"); // a checked spot: it may be tapped
  });

  it("steps aside when something to press comes under it, and lets taps through meanwhile", async () => {
    const { walker, at, main } = await page();
    await vi.advanceTimersByTimeAsync(3300);
    const here = at();
    const bar = { left: here.x - 40, top: here.y - 10, width: 200, height: 70 };
    main.insertAdjacentHTML("beforeend", `<button data-rect="${bar.left},${bar.top},${bar.width},${bar.height}">Save</button>`);
    await vi.advanceTimersByTimeAsync(750);
    expect(walker().classes()).toContain("pointer-events-none");
    await vi.advanceTimersByTimeAsync(3300);
    expect(covers(at(), bar)).toBe(false);
    expect(walker().classes()).toContain("pointer-events-auto");
  });

  it("hides while a dialog is open and comes back when it closes", async () => {
    const { layer, walker } = await page();
    await vi.advanceTimersByTimeAsync(3300);
    const dialog = document.createElement("div");
    dialog.setAttribute("role", "dialog");
    dialog.dataset.rect = "200,100,500,400";
    document.body.append(dialog);
    await vi.advanceTimersByTimeAsync(750);
    expect(layer().attributes("data-hidden")).toBeDefined();
    expect(walker().classes()).toContain("pointer-events-none");
    dialog.remove();
    await vi.advanceTimersByTimeAsync(2200);
    expect(layer().attributes("data-hidden")).toBeUndefined();
  });

  it("hides when the whole floor is taken, peek included, and never takes a tap there", async () => {
    const { layer, walker } = await page('<button data-rect="0,600,1024,168">A full-width bar</button>');
    await vi.advanceTimersByTimeAsync(3300);
    expect(layer().attributes("data-hidden")).toBeDefined();
    expect(walker().classes()).toContain("pointer-events-none");
  });

  it("peeks in from the right edge when only that is free", async () => {
    const { at, layer } = await page('<button data-rect="0,600,1000,168">Almost full</button>');
    await vi.advanceTimersByTimeAsync(3300);
    expect(layer().attributes("data-hidden")).toBeUndefined();
    expect(at().x).toBe(1024 - Math.round(60 * 0.45));
  });

  it("stays still with reduced motion, but never over a button", async () => {
    reducedMotion(true);
    const button = { left: 900, top: 650, width: 124, height: 118 }; // where it would stand: the floor's right end
    const { at, walker } = await page(`<button data-rect="${button.left},${button.top},${button.width},${button.height}">Next</button>`);
    await vi.advanceTimersByTimeAsync(2000);
    expect(covers(at(), button)).toBe(false);
    expect(walker().attributes("style")).toContain("transition: none");
  });
});

describe("the Agents page's helper keeps clear", () => {
  it("leaves a card alone when a button sits just above it", async () => {
    vi.useFakeTimers();
    vi.spyOn(Math, "random").mockReturnValue(0.9);
    layout();
    const Page = defineComponent({
      setup: () => () =>
        h("div", { class: "relative", "data-testid": "page", "data-rect": "100,100,1000,900" }, [
          h(AiBuddyStage, { mood: "on", size: 72 }, { default: () => h("p", "On duty") }),
          h("button", { "data-rect": "300,420,700,80" }, "Run now"),
          h("article", { class: "ai-agent-card", "data-agent": "voice_tasks", "data-rect": "300,500,400,180" }, "Voice tasks"),
        ]),
    });
    const app = await testApp("/c/1/ai");
    const { wrapper } = mountWithProviders(Page, { plugins: app.plugins });
    await flushPromises();
    const stage = wrapper.findComponent(AiBuddyStage).vm as unknown as { visit(card: HTMLElement): Promise<void> };
    await stage.visit(wrapper.find(".ai-agent-card").element as HTMLElement);
    await vi.advanceTimersByTimeAsync(40);
    expect(wrapper.find('[data-testid="ai-buddy-traveller"]').exists()).toBe(false); // it stayed home
    expect(wrapper.find('[data-testid="ai-buddy-strip"] [data-testid="ai-buddy"]').exists()).toBe(true);
  });
});
