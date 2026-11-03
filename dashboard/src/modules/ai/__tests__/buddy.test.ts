// The registry first, as in the app: it is what loads every module's index.ts (see core/modules.ts).
import "@/core/modules";

import { flushPromises, mount } from "@vue/test-utils";
import { defineComponent, h } from "vue";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { pulse } from "@/core/pulse";
import { mergeModuleMessages } from "@/i18n";
import { toast } from "@/components/useToast";
import { json } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

import AgentChibi from "../components/AgentChibi.vue";
import AiBuddy from "../components/AiBuddy.vue";
import AiBuddyStage from "../components/AiBuddyStage.vue";
import BuddyCompanion from "../components/BuddyCompanion.vue";
import { buddyEverywhere } from "../components/buddyPrefs";
import { buddyCue, buddyGreeting, cue, greet } from "../components/buddyBus";
import { useBuddyCues } from "../components/buddyCues";
import en from "../i18n/en.json";
import { activityReactions, type BuddyAction, BUDDY_DANCES, BUDDY_DURATION, buddyBox, buddyVariant, buddyWalkMs, draftCues, floorY, pickBuddyAction, pickChibiAction, planBuddy, planCompanion, pulseCues, shyStep, standPoint } from "../lib";

/** What the app sets on <html> from the system's "reduce motion" (app/theme.ts). */
function reducedMotion(on: boolean): void {
  document.documentElement.dataset.motion = on ? "reduced" : "full";
}

beforeEach(() => {
  mergeModuleMessages("ai", { en, ru: en, uz: en });
  reducedMotion(false);
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  buddyGreeting.value = null;
  buddyCue.value = null;
  pulse.value = { counters: {}, versions: {} };
  document.body.innerHTML = "";
});

describe("the helper's choices", () => {
  it("acts from its mood's pool, the chibis from a calmer one", () => {
    expect(pickBuddyAction("on", 0)).toBe("blink");
    expect(pickBuddyAction("on", 0.9999)).toBe("sparkle");
    expect(pickBuddyAction("busy", 0)).toBe("type");
    expect(pickChibiAction(true, 0)).toBe("type");
    expect(pickChibiAction(false, 0.9999)).toBe("hop");
  });

  it("visits a card only when it can see one", () => {
    const rolls = (...values: number[]) => () => values.shift() ?? 0;
    expect(planBuddy("on", 3, rolls(0.1, 0.7))).toEqual({ kind: "visit", card: 2 });
    expect(planBuddy("on", 0, rolls(0.1))).toEqual({ kind: "stroll" });
    expect(planBuddy("on", 3, rolls(0.4))).toEqual({ kind: "stroll" });
    expect(planBuddy("busy", 3, rolls(0.9, 0))).toEqual({ kind: "act", action: "type" });
  });

  it("walks at an even pace, never in a blink nor forever", () => {
    expect(buddyWalkMs(0, 0)).toBe(450);
    expect(buddyWalkMs(110, 0)).toBe(1000);
    expect(buddyWalkMs(5000, 400)).toBe(3200);
  });

  it("stands with its feet on a card's top edge, on the card's left part", () => {
    const card = { left: 300, top: 500, width: 400, height: 180 };
    const root = { left: 100, top: 100, width: 1000, height: 900 };
    const { feet } = buddyBox(72);
    expect(standPoint(card, root, 72, 0)).toEqual({ x: 212, y: 400 - feet });
    const far = standPoint(card, root, 72, 0.9999);
    expect(far.x).toBeLessThanOrEqual(212 + Math.round((400 - 72 - 24) * 0.6));
    expect(far.x + 72).toBeLessThan(card.left - root.left + card.width);
    expect(standPoint(card, root, 72, 0, true).y).toBe(400 - feet + 12); // legs hang over the edge
  });

  it("gives every agent its own chibi and the rest Claude", () => {
    expect(["voice_tasks", "morning_plan", "deadline_watcher", "photo_checker", "hr_assistant", "flows"].map(buddyVariant)).toEqual([
      "voice",
      "morning",
      "deadline",
      "photo",
      "hr",
      "claude",
    ]);
  });
});

describe("the drawing", () => {
  async function draw(props: Record<string, unknown>) {
    const app = await testApp("/c/1/ai");
    const wrapper = mount(AiBuddy, { props: { mood: "on", ...props }, global: { plugins: app.plugins }, attachTo: document.body });
    await flushPromises();
    return wrapper;
  }

  it.each([
    ["voice", "headphones"],
    ["morning", "sun"],
    ["deadline", "clock"],
    ["photo", "glasses"],
  ])("draws the %s chibi with its %s", async (variant, prop) => {
    const wrapper = await draw({ variant });
    expect(wrapper.find(`[data-prop="${prop}"]`).exists()).toBe(true);
    expect(wrapper.find("[data-prop]:not([data-prop=" + prop + "])").exists()).toBe(false);
  });

  it("draws the HR chibi in a tie, holding a clipboard that moves with its hand", async () => {
    const wrapper = await draw({ variant: "hr" });
    expect(wrapper.attributes("data-variant")).toBe("hr");
    expect(wrapper.findAll("[data-prop]").map((prop) => prop.attributes("data-prop"))).toEqual(["clipboard", "tie"]);
    expect(wrapper.find('[data-prop="clipboard"]').classes()).toContain("buddy-arm-left");
  });

  it("draws Claude without a prop, with open eyes and its own name for screen readers", async () => {
    const wrapper = await draw({});
    expect(wrapper.find("[data-prop]").exists()).toBe(false);
    expect(wrapper.find('[data-eyes="open"]').exists()).toBe(true);
    expect(wrapper.attributes("aria-label")).toBe(en["ai.buddy.label"]);
  });

  it("shows the face of what it does and lets out hearts, which float away", async () => {
    vi.useFakeTimers();
    const wrapper = await draw({});
    await wrapper.setProps({ action: "hearts", beat: 1 });
    expect(wrapper.find('[data-eyes="happy"]').exists()).toBe(true);
    expect(wrapper.findAll('[data-kind="heart"]')).toHaveLength(3);
    await vi.advanceTimersByTimeAsync(2100);
    expect(wrapper.findAll(".buddy-particle")).toHaveLength(0);
    await wrapper.setProps({ action: "love", beat: 2 });
    expect(wrapper.find('[data-eyes="love"]').exists()).toBe(true);
  });

  it("sleeps with closed eyes and breathes out a z now and then", async () => {
    vi.useFakeTimers();
    const wrapper = await draw({ variant: "photo", asleep: true });
    expect(wrapper.find('[data-eyes="asleep"]').exists()).toBe(true);
    expect(wrapper.attributes("data-asleep")).toBeDefined();
    await vi.advanceTimersByTimeAsync(1000);
    expect(wrapper.findAll('[data-kind="z"]')).toHaveLength(1);
  });

  it("lets nothing float with reduced motion", async () => {
    reducedMotion(true);
    vi.useFakeTimers();
    const wrapper = await draw({ asleep: true });
    await wrapper.setProps({ action: "hearts", beat: 1 });
    await vi.advanceTimersByTimeAsync(3000);
    expect(wrapper.findAll(".buddy-particle")).toHaveLength(0);
    expect(wrapper.find('[data-eyes="happy"]').exists()).toBe(true); // the face still changes
  });

  it("says when it is tapped", async () => {
    const wrapper = await draw({});
    await wrapper.trigger("click");
    expect(wrapper.emitted("tap")).toHaveLength(1);
  });
});

describe("an agent's chibi", () => {
  async function chibi(props: Record<string, unknown>) {
    const app = await testApp("/c/1/ai");
    const { wrapper } = mountWithProviders(AgentChibi, { props: { agentKey: "voice_tasks", name: "Voice tasks", on: true, ...props }, plugins: app.plugins });
    await flushPromises();
    return wrapper;
  }

  it("is the agent's own, named for screen readers, and asleep while its agent is off", async () => {
    const wrapper = await chibi({ on: false });
    const buddy = wrapper.find('[data-testid="ai-buddy"]');
    expect(buddy.attributes("data-variant")).toBe("voice");
    expect(buddy.attributes("aria-label")).toBe("Voice tasks");
    expect(wrapper.find('[data-eyes="asleep"]').exists()).toBe(true);
  });

  it("greets Claude's helper when it pokes its card, and only then", async () => {
    vi.useFakeTimers();
    vi.spyOn(Math, "random").mockReturnValue(0.1);
    const wrapper = await chibi({});
    greet("deadline_watcher");
    await vi.advanceTimersByTimeAsync(300);
    expect(wrapper.find('[data-eyes="happy"]').exists()).toBe(false);
    greet("voice_tasks");
    await vi.advanceTimersByTimeAsync(300);
    expect(wrapper.find('[data-eyes="happy"]').exists()).toBe(true);
  });

  it("smiles when tapped, even waking up for a moment", async () => {
    const wrapper = await chibi({ on: false });
    await wrapper.find('[data-testid="ai-buddy"]').trigger("click");
    expect(wrapper.find('[data-eyes="happy"]').exists()).toBe(true);
  });
});

describe("the helper's walks", () => {
  function rect(left: number, top: number, width: number, height: number): DOMRect {
    return { left, top, width, height, right: left + width, bottom: top + height, x: left, y: top, toJSON: () => ({}) } as DOMRect;
  }

  async function page() {
    vi.spyOn(Element.prototype, "getBoundingClientRect").mockImplementation(function (this: Element) {
      const element = this as HTMLElement;
      if (element.classList.contains("ai-agent-card")) return rect(300, 500, 400, 180);
      if (element.dataset.testid === "page") return rect(100, 100, 1000, 900);
      return rect(140, 150, 72, 68);
    });
    const Page = defineComponent({
      setup: () => () =>
        h("div", { class: "relative", "data-testid": "page" }, [
          h(AiBuddyStage, { mood: "on", size: 72 }, { default: () => h("p", "On duty") }),
          h("article", { class: "ai-agent-card", "data-agent": "voice_tasks" }, "Voice tasks"),
        ]),
    });
    const app = await testApp("/c/1/ai");
    const { wrapper } = mountWithProviders(Page, { plugins: app.plugins });
    await flushPromises();
    const stage = wrapper.findComponent(AiBuddyStage);
    return { wrapper, stage: stage.vm as unknown as { visit(card: HTMLElement): Promise<void>; callOff(): void }, card: wrapper.find(".ai-agent-card").element as HTMLElement };
  }

  it("walks to a card, pokes it so its chibi greets back, and walks home", async () => {
    vi.useFakeTimers();
    vi.spyOn(Math, "random").mockReturnValue(0.9);
    const { wrapper, stage, card } = await page();
    expect(wrapper.find('[data-testid="ai-buddy-strip"]').text()).toContain("On duty");

    const trip = stage.visit(card);
    await vi.advanceTimersByTimeAsync(40);
    const traveller = wrapper.find('[data-testid="ai-buddy-traveller"]');
    expect(traveller.exists()).toBe(true);
    expect(traveller.attributes("style")).toContain("translate(376px, 340px)"); // feet on the card's edge
    expect(traveller.find("[data-walking]").exists()).toBe(true);
    expect(wrapper.find('[data-testid="ai-buddy-strip"] [data-testid="ai-buddy"]').exists()).toBe(false);

    await vi.advanceTimersByTimeAsync(3200);
    expect(card.dataset.buddyPoke).toBeDefined();
    expect(buddyGreeting.value?.key).toBe("voice_tasks");
    expect(wrapper.find('[data-testid="ai-buddy-traveller"] [data-action="touch"]').exists()).toBe(true);
    await vi.advanceTimersByTimeAsync(700);
    expect(card.dataset.buddyPoke).toBeUndefined();

    await vi.advanceTimersByTimeAsync(400 + 1700 + 3200);
    await trip;
    expect(wrapper.find('[data-testid="ai-buddy-traveller"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="ai-buddy-strip"] [data-testid="ai-buddy"]').exists()).toBe(true);
  });

  it("goes straight home when the window changes size", async () => {
    vi.useFakeTimers();
    vi.spyOn(Math, "random").mockReturnValue(0.9);
    const { wrapper, stage, card } = await page();
    void stage.visit(card);
    await vi.advanceTimersByTimeAsync(40);
    window.dispatchEvent(new Event("resize"));
    await flushPromises();
    expect(wrapper.find('[data-testid="ai-buddy-traveller"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="ai-buddy-strip"] [data-testid="ai-buddy"]').exists()).toBe(true);
  });

  it("stays home and still with reduced motion, and leaves no timers behind", async () => {
    reducedMotion(true);
    vi.useFakeTimers();
    const { wrapper } = await page();
    expect(vi.getTimerCount()).toBe(0);
    wrapper.unmount();
    expect(vi.getTimerCount()).toBe(0);
  });
});

describe("what happens, as reactions", () => {
  it("turns agent activity into the right chibi's reaction", () => {
    expect(
      activityReactions([
        { agent: "deadline_watcher", kind: "escalated" },
        { agent: "voice_tasks", kind: "draft_auto_applied" },
        { agent: "voice_tasks", kind: "draft_failed" },
        { agent: "photo_checker", kind: "looks_right" },
        { agent: "photo_checker", kind: "unclear" },
        { agent: "morning_plan", kind: "plan_sent" },
        { agent: "hr_assistant", kind: "digest_sent" },
        { agent: "hr_assistant", kind: "payroll_ready" },
        { agent: "hr_assistant", kind: "payroll_blocked" },
        { agent: "hr_assistant", kind: "bonuses_suggested" },
        { agent: "flows", kind: "ran" },
      ]),
    ).toEqual([
      { key: "deadline_watcher", action: "ring", visit: true },
      { key: "voice_tasks", action: "hearts" },
      { key: "photo_checker", action: "hearts" },
      { key: "photo_checker", action: "look" },
      { key: "morning_plan", action: "wave" },
      { key: "hr_assistant", action: "wave" },
      { key: "hr_assistant", action: "cheer" },
      { key: "hr_assistant", action: "look" },
      { key: "hr_assistant", action: "hearts" },
    ]);
  });

  it("hears a task go late and the tasks change in the pulse, never on the first one", () => {
    const first = { counters: { "tasks.late_now": 2 }, versions: { "tasks.tasks": "a" } };
    expect(pulseCues(null, first)).toEqual({ late: false, tasksChanged: false });
    expect(pulseCues({ counters: {}, versions: {} }, first)).toEqual({ late: false, tasksChanged: false }); // before the server answered
    expect(pulseCues(first, { counters: { "tasks.late_now": 3 }, versions: { "tasks.tasks": "a" } })).toEqual({ late: true, tasksChanged: false });
    expect(pulseCues(first, { counters: { "tasks.late_now": 1 }, versions: { "tasks.tasks": "b" } })).toEqual({ late: false, tasksChanged: true });
  });

  it("listens while a voice note is written down and is pleased when it became tasks", () => {
    const start = draftCues(null, [{ id: 7, status: "transcribing" }, { id: 6, status: "applied" }]);
    expect(start).toMatchObject({ listen: true, done: false });
    const ready = draftCues(start.seen, [{ id: 7, status: "ready" }, { id: 6, status: "applied" }]);
    expect(ready).toMatchObject({ listen: false, done: true });
    expect(draftCues(ready.seen, [{ id: 7, status: "ready" }, { id: 6, status: "applied" }])).toMatchObject({ listen: false, done: false });
    expect(draftCues(ready.seen, [{ id: 8, status: "applied" }, { id: 7, status: "ready" }]).done).toBe(true); // a quick one, never seen working
    expect(draftCues(start.seen, [{ id: 7, status: "failed" }]).done).toBe(false);
  });
});

describe("the helpers react", () => {
  it("listens with sound waves, rings with red marks, cheers with hearts", async () => {
    vi.useFakeTimers();
    const app = await testApp("/c/1/ai");
    const wrapper = mount(AiBuddy, { props: { mood: "on", variant: "deadline" }, global: { plugins: app.plugins }, attachTo: document.body });
    await wrapper.setProps({ action: "listen", beat: 1 });
    expect(wrapper.find('[data-eyes="happy"]').exists()).toBe(true);
    expect(wrapper.findAll('[data-kind="wave"]')).toHaveLength(3);
    await wrapper.setProps({ action: "ring", beat: 2 });
    expect(wrapper.attributes("data-action")).toBe("ring");
    expect(wrapper.findAll('[data-kind="alert"]')).toHaveLength(2);
    await wrapper.setProps({ action: "cheer", beat: 3 });
    expect(wrapper.findAll('[data-kind="heart"]')).toHaveLength(4);
  });

  it("an agent's chibi reacts to its own agent's news and to everyone's, not to another's", async () => {
    const app = await testApp("/c/1/ai");
    const { wrapper } = mountWithProviders(AgentChibi, { props: { agentKey: "deadline_watcher", name: "Deadline watcher", on: false }, plugins: app.plugins });
    await flushPromises();
    const buddy = () => wrapper.find('[data-testid="ai-buddy"]');
    cue("voice_tasks", "listen");
    await flushPromises();
    expect(buddy().attributes("data-action")).toBe("idle");
    cue("deadline_watcher", "ring");
    await flushPromises();
    expect(buddy().attributes("data-action")).toBe("ring");
    expect(buddy().attributes("data-asleep")).toBeUndefined(); // the alarm wakes it up
    cue("", "cheer");
    await flushPromises();
    expect(buddy().attributes("data-action")).toBe("cheer");
  });
});

describe("the page's live data", () => {
  it("hears a voice note, a late task and a finished task, but nothing from before", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval", "Date"] });
    let drafts = [{ id: 5, status: "applied" }];
    let doneToday = 3;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string) => {
        if (input.includes("task-drafts/")) return json({ count: drafts.length, next: null, previous: null, results: drafts });
        if (input.includes("tasks/summary/")) return json({ done_today: doneToday });
        if (input.includes("ai/activity/")) return json({ results: [], next_before: null });
        return json({});
      }),
    );
    const Probe = defineComponent({
      setup() {
        useBuddyCues(true);
        return () => h("div");
      },
    });
    const app = await testApp("/c/1/ai");
    mountWithProviders(Probe, { plugins: app.plugins });
    pulse.value = { counters: { "tasks.late_now": 1 }, versions: { "tasks.tasks": "a" } };
    await vi.advanceTimersByTimeAsync(100);
    expect(buddyCue.value).toBeNull(); // what was already there is the baseline

    drafts = [{ id: 6, status: "transcribing" }, ...drafts];
    await vi.advanceTimersByTimeAsync(5100);
    expect(buddyCue.value).toMatchObject({ key: "voice_tasks", action: "listen" });

    pulse.value = { counters: { "tasks.late_now": 2 }, versions: { "tasks.tasks": "a" } };
    await vi.advanceTimersByTimeAsync(100);
    expect(buddyCue.value).toMatchObject({ key: "deadline_watcher", action: "ring" });

    doneToday = 4;
    pulse.value = { counters: { "tasks.late_now": 2 }, versions: { "tasks.tasks": "b" } };
    await vi.advanceTimersByTimeAsync(100);
    expect(buddyCue.value).toMatchObject({ key: "", action: "cheer" });
  });
});

describe("Claude on every page: the choices", () => {
  it("climbs a card it can see, strolls, moonwalks, or acts in place", () => {
    const rolls = (...values: number[]) => () => values.shift() ?? 0;
    expect(planCompanion(4, rolls(0.1, 0.6))).toEqual({ kind: "visit", card: 2 });
    expect(planCompanion(0, rolls(0.1))).toEqual({ kind: "stroll" });
    expect(planCompanion(4, rolls(0.3))).toEqual({ kind: "stroll" });
    expect(planCompanion(4, rolls(0.45))).toEqual({ kind: "moonwalk" });
    expect(planCompanion(4, rolls(0.9, 0))).toEqual({ kind: "act", action: "blink" });
    for (const dance of BUDDY_DANCES) expect(BUDDY_DURATION[dance]).toBeGreaterThan(0);
  });

  it("stands on the phone's tab bar, else just above the bottom of the window", () => {
    const { feet } = buddyBox(52);
    expect(floorY(844, 760, 52)).toBe(760 - feet);
    expect(floorY(900, null, 60)).toBe(890 - buddyBox(60).feet);
  });

  it("steps away from the pointer, and the other way when there is no room", () => {
    expect(shyStep(400, 380, 0, 1000)).toBe(540);
    expect(shyStep(400, 420, 0, 1000)).toBe(260);
    expect(shyStep(950, 900, 0, 1000)).toBe(810); // no room on the right: it goes left
    expect(shyStep(50, 60, 0, 1000)).toBe(190);
  });
});

describe("more faces and little dances", () => {
  async function draw(action: BuddyAction) {
    const app = await testApp("/c/1/ai");
    const wrapper = mount(AiBuddy, { props: { mood: "on" }, global: { plugins: app.plugins }, attachTo: document.body });
    await wrapper.setProps({ action, beat: 1 });
    return wrapper;
  }

  it.each<[BuddyAction, string]>([
    ["wink", "wink"],
    ["star", "star"],
    ["wide", "wide"],
    ["sweat", "wide"],
    ["shy", "shy"],
    ["dizzy", "dizzy"],
    ["think", "think"],
    ["disco", "happy"],
    ["spin", "happy"],
    ["bye", "happy"],
  ])("%s shows its %s face", async (action, face) => {
    const wrapper = await draw(action);
    expect(wrapper.find(`[data-eyes="${face}"]`).exists()).toBe(true);
  });

  it("lets out music notes dancing, a sweat drop, thinking dots and stars", async () => {
    vi.useFakeTimers();
    expect((await draw("disco")).findAll('[data-kind="note"]')).toHaveLength(3);
    expect((await draw("sweat")).findAll('[data-kind="drop"]')).toHaveLength(1);
    expect((await draw("think")).findAll('[data-kind="dots"]')).toHaveLength(1);
    expect((await draw("dizzy")).findAll('[data-kind="star"]')).toHaveLength(3);
  });
});

describe("Claude on every page", () => {
  function box(left: number, top: number, width: number, height: number): DOMRect {
    return { left, top, width, height, right: left + width, bottom: top + height, x: left, y: top, toJSON: () => ({}) } as DOMRect;
  }

  async function page(path = "/c/1/tasks") {
    vi.useFakeTimers();
    vi.spyOn(Math, "random").mockReturnValue(0.99); // in place, never off on a walk by itself
    vi.stubGlobal("fetch", vi.fn(async () => json({ enabled: true, can_configure: true, claude: "connected", speech: "ready", features: {}, budget: null })));
    const main = document.createElement("main");
    main.innerHTML = '<section class="rounded-card">A card</section>';
    document.body.append(main);
    vi.spyOn(Element.prototype, "getBoundingClientRect").mockImplementation(function (this: Element) {
      if (this.tagName === "MAIN") return box(248, 0, 1000, 900);
      if (this.classList.contains("rounded-card")) return box(300, 300, 600, 200);
      return box(0, 0, 0, 0);
    });
    buddyEverywhere.value = true;
    const app = await testApp(path);
    app.router.addRoute({ path: "/c/:cid/ai", name: "ai.agents", component: { render: () => null } });
    app.router.addRoute({ path: "/c/:cid/ai/agents/:key", name: "ai.agent", component: { render: () => null } });
    const { wrapper } = mountWithProviders(BuddyCompanion, { plugins: app.plugins });
    await vi.advanceTimersByTimeAsync(50);
    await flushPromises();
    return { wrapper, app, buddy: () => wrapper.find('[data-testid="ai-buddy"]') };
  }

  it("walks onto the page from the left while AI is on, and stays away when switched off", async () => {
    const { wrapper, buddy } = await page();
    const walker = () => wrapper.find('[data-testid="ai-buddy-walker"]');
    expect(walker().exists()).toBe(true);
    expect(buddy().attributes("data-walking")).toBeDefined();
    await vi.advanceTimersByTimeAsync(3300);
    expect(buddy().attributes("data-walking")).toBeUndefined();
    buddyEverywhere.value = false;
    await flushPromises();
    expect(wrapper.find('[data-testid="ai-buddy-companion"]').exists()).toBe(false);
  });

  it("leaves the Agents page to the strip's own helper, and comes along to the next page", async () => {
    const { wrapper, app } = await page();
    await app.router.push("/c/1/ai");
    await flushPromises();
    expect(wrapper.find('[data-testid="ai-buddy-companion"]').exists()).toBe(false);
    // An agent's page has its chibi at its desk: it stays away there too.
    await app.router.push("/c/1/ai/agents/deadline_watcher");
    await flushPromises();
    expect(wrapper.find('[data-testid="ai-buddy-companion"]').exists()).toBe(false);
    await app.router.push("/c/1/people");
    await flushPromises();
    await vi.advanceTimersByTimeAsync(40);
    const style = wrapper.find('[data-testid="ai-buddy-walker"]').attributes("style") ?? "";
    expect(style).toContain("transition: transform"); // walking in from the left edge
  });

  it("gets dizzy from five quick taps", async () => {
    const { buddy } = await page();
    await vi.advanceTimersByTimeAsync(3300);
    for (let index = 0; index < 5; index += 1) await buddy().trigger("click");
    expect(buddy().attributes("data-action")).toBe("dizzy");
  });

  it("waves goodbye and hides on a long press, and the toast brings it back", async () => {
    const info = vi.spyOn(toast, "info");
    const { wrapper } = await page();
    await vi.advanceTimersByTimeAsync(3300);
    await wrapper.find('[data-testid="ai-buddy-walker"]').trigger("pointerdown");
    await vi.advanceTimersByTimeAsync(700);
    expect(wrapper.find('[data-testid="ai-buddy"]').attributes("data-action")).toBe("bye");
    await vi.advanceTimersByTimeAsync(5000);
    expect(buddyEverywhere.value).toBe(false);
    const options = info.mock.calls.at(-1)?.[1] as { action: { onClick: () => void } };
    options.action.onClick();
    expect(buddyEverywhere.value).toBe(true);
  });

  it("dozes off when nobody is around and wakes up surprised", async () => {
    const { buddy } = await page();
    await vi.advanceTimersByTimeAsync(100_000);
    expect(buddy().attributes("data-asleep")).toBeDefined();
    window.dispatchEvent(new Event("keydown"));
    await flushPromises();
    expect(buddy().attributes("data-action")).toBe("wide");
  });

  it("cheers and dances for a finished task, sweats over a late one", async () => {
    const { buddy } = await page();
    await vi.advanceTimersByTimeAsync(3300);
    cue("", "cheer");
    await flushPromises();
    expect(buddy().attributes("data-action")).toBe("cheer");
    await vi.advanceTimersByTimeAsync(BUDDY_DURATION.cheer + 150);
    expect(BUDDY_DANCES).toContain(buddy().attributes("data-action"));
    await vi.advanceTimersByTimeAsync(2000);
    cue("deadline_watcher", "ring");
    await flushPromises();
    expect(buddy().attributes("data-action")).toBe("sweat");
  });

  it("lets taps through while it walks or stands on a card, and takes them on the floor", async () => {
    const { wrapper } = await page();
    const walker = () => wrapper.find('[data-testid="ai-buddy-walker"]');
    await vi.advanceTimersByTimeAsync(3300);
    expect(walker().classes()).toContain("pointer-events-auto");
    const companion = wrapper.findComponent(BuddyCompanion).vm as unknown as { visit(card: HTMLElement): Promise<void> };
    void companion.visit(document.querySelector("main .rounded-card") as HTMLElement);
    await vi.advanceTimersByTimeAsync(50);
    expect(walker().classes()).toContain("pointer-events-none");
    await vi.advanceTimersByTimeAsync(3300);
    expect(walker().classes()).toContain("pointer-events-none"); // up on the card
    expect((document.querySelector("main .rounded-card") as HTMLElement).dataset.buddyPoke).toBeDefined();
  });

  it("stays still with reduced motion, whatever the time", async () => {
    reducedMotion(true);
    const { wrapper, buddy } = await page();
    await vi.advanceTimersByTimeAsync(20_000);
    expect(buddy().attributes("data-action")).toBe("idle");
    expect(wrapper.find('[data-testid="ai-buddy-walker"]').attributes("style")).toContain("transition: none");
  });
});
