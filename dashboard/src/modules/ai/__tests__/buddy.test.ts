// The registry first, as in the app: it is what loads every module's index.ts (see core/modules.ts).
import "@/core/modules";

import { flushPromises, mount } from "@vue/test-utils";
import { defineComponent, h } from "vue";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { pulse } from "@/core/pulse";
import { mergeModuleMessages } from "@/i18n";
import { json } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

import AgentChibi from "../components/AgentChibi.vue";
import AiBuddy from "../components/AiBuddy.vue";
import AiBuddyStage from "../components/AiBuddyStage.vue";
import { buddyCue, buddyGreeting, cue, greet } from "../components/buddyBus";
import { useBuddyCues } from "../components/buddyCues";
import en from "../i18n/en.json";
import { activityReactions, buddyBox, buddyVariant, buddyWalkMs, draftCues, pickBuddyAction, pickChibiAction, planBuddy, pulseCues, standPoint } from "../lib";

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
    expect(["voice_tasks", "morning_plan", "deadline_watcher", "photo_checker", "flows"].map(buddyVariant)).toEqual(["voice", "morning", "deadline", "photo", "claude"]);
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
        { agent: "flows", kind: "ran" },
      ]),
    ).toEqual([
      { key: "deadline_watcher", action: "ring", visit: true },
      { key: "voice_tasks", action: "hearts" },
      { key: "photo_checker", action: "hearts" },
      { key: "photo_checker", action: "look" },
      { key: "morning_plan", action: "wave" },
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
