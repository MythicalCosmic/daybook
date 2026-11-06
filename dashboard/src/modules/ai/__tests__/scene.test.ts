// An agent's room on its own page: what the chibi does at its desk, what its screen shows, where
// it sits as the box changes size, the room by state, night and a tap, and its life: the clock,
// the calendar, the cat, what it thinks and says.
import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { mergeModuleMessages } from "@/i18n";
import { testApp } from "@/test/plugins";

import AgentScene from "../components/AgentScene.vue";
import en from "../i18n/en.json";
import ru from "../i18n/ru.json";
import uz from "../i18n/uz.json";
import {
  clockHands,
  isNightHour,
  pickSceneAction,
  pickThought,
  ROOM,
  SCENE_ACTIONS,
  sceneActionMs,
  sceneBuddy,
  sceneSayings,
  screenLines,
  seatBox,
  SEAT,
  SIGNATURE_MOVE,
  stagePoint,
} from "../scene";

describe("the chibi at its desk", () => {
  it("only does what reads well in a chair, and never the same face twice in a row", () => {
    const seated = new Set([...SCENE_ACTIONS.working, ...SCENE_ACTIONS.idle]);
    for (const moving of ["hop", "dance", "spin", "bounce", "jumpjack", "twist", "disco"]) expect(seated.has(moving as never)).toBe(false);
    expect(pickSceneAction("idle", "blink", () => 0)).not.toBe("blink");
    expect(pickSceneAction("working", "type", () => 0)).toBe("type"); // typing goes on
    expect(pickSceneAction("asleep", "wave")).toBe("idle");
  });

  it("now and then does its own move: the voice chibi listens, the deadline one rings its clock", () => {
    expect(pickSceneAction("idle", "blink", () => 0, SIGNATURE_MOVE.voice)).toBe("listen");
    expect(pickSceneAction("working", "type", () => 0, SIGNATURE_MOVE.deadline)).toBe("ring");
    // Not twice in a row, and not when the dice say otherwise.
    expect(pickSceneAction("idle", "listen", () => 0, "listen")).not.toBe("listen");
    expect(pickSceneAction("idle", "blink", () => 0.9, "listen")).not.toBe("listen");
    const seated = new Set(Object.values(SIGNATURE_MOVE));
    for (const moving of ["hop", "dance", "spin", "bounce", "jumpjack", "twist", "disco", "tap"]) expect(seated.has(moving as never)).toBe(false);
  });

  it("thinks of little things while awake, never the same twice in a row, and nothing asleep", () => {
    expect(pickThought("idle", null, () => 0)).toBe("heart");
    expect(pickThought("idle", "heart", () => 0)).not.toBe("heart");
    expect(pickThought("working", null, () => 0)).toBe("idea");
    expect(pickThought("asleep", null)).toBeNull();
  });

  it("says how it is, its own line, what it did today and when it runs next; asleep only that it's off", () => {
    expect(sceneSayings("idle", "voice", "14:30", 3)).toEqual([
      { key: "ai.agent.scene.say.hi" },
      { key: "ai.agent.scene.say.voice" },
      { key: "ai.agent.scene.say.today", params: { count: 3 } },
      { key: "ai.agent.scene.say.next", params: { time: "14:30" } },
    ]);
    expect(sceneSayings("working", "hr", null, 0).map((saying) => saying.key)).toEqual(["ai.agent.scene.say.busy", "ai.agent.scene.say.hr", "ai.agent.scene.say.nothingYet"]);
    expect(sceneSayings("asleep", "morning", "07:00", 5)).toEqual([{ key: "ai.agent.scene.say.asleep" }]);
  });

  it("turns the wall clock's hands to the company's time", () => {
    expect(clockHands(3, 0)).toEqual({ hour: 90, minute: 0 });
    expect(clockHands(15, 30)).toEqual({ hour: 105, minute: 180 });
    expect(clockHands(0, 45)).toEqual({ hour: 22.5, minute: 270 });
  });

  it("places a stage point in the box like the room: the bubbles' anchors", () => {
    const scale = 380 / ROOM.height;
    expect(stagePoint(176, 60, 1100, 380)).toEqual({ left: Math.round((1100 - ROOM.width * scale) / 2 + (ROOM.stageX + 176) * scale), top: Math.round(60 * scale) });
  });

  it("types while it works, watches the screen while it waits and sleeps when off", () => {
    expect(sceneBuddy("working")).toEqual({ mood: "busy", asleep: false, gaze: "right" });
    expect(sceneBuddy("idle")).toEqual({ mood: "on", asleep: false, gaze: "right" });
    expect(sceneBuddy("asleep")).toEqual({ mood: "on", asleep: true, gaze: undefined });
    expect(sceneActionMs("type")).toBe(Number.POSITIVE_INFINITY);
    expect(sceneActionMs("blink")).toBeGreaterThanOrEqual(600);
  });

  it("keeps the newest lines for its screen, one line each, cut to fit", () => {
    const lines = ["one", "two", "  three\n  lines  ", "", "four", "five", "a line far too long for the little screen to hold"];
    expect(screenLines(lines, 5, 20)).toEqual(["two", "three lines", "four", "five", "a line far too long…"]);
    expect(screenLines([])).toEqual([]);
  });

  it("calls 20:00 to 06:00 night", () => {
    expect([19, 20, 23, 0, 5, 6, 12].map(isNightHour)).toEqual([false, true, true, true, true, false, false]);
  });

  it("sits on its chair wherever the room is scaled to, and slumps when asleep", () => {
    // 1100 × 380: the height decides the scale; the stage is centred.
    const desk = seatBox(1100, 380, false);
    const scale = 380 / ROOM.height;
    expect(desk.size).toBe(Math.round(SEAT.size * scale));
    expect(desk.left).toBe(Math.round((1100 - ROOM.width * scale) / 2 + (ROOM.stageX + SEAT.x) * scale));
    expect(desk.top).toBe(Math.round(SEAT.y * scale));
    expect(seatBox(1100, 380, true).top).toBeGreaterThan(desk.top);
    // A box not measured yet never gives a zero-sized chibi.
    expect(seatBox(0, 0, false).size).toBe(1);
  });
});

describe("AgentScene", () => {
  beforeEach(() => {
    mergeModuleMessages("ai", { en, ru, uz });
  });

  afterEach(() => {
    vi.useRealTimers();
    document.documentElement.removeAttribute("data-motion");
  });

  async function draw(props: Record<string, unknown>) {
    const app = await testApp("/c/1/ai");
    const wrapper = mount(AgentScene, { props: { variant: "hr_assistant", state: "idle", label: "HR assistant at its desk", ...props }, global: { plugins: app.plugins } });
    await flushPromises();
    return wrapper;
  }

  it("draws the agent's own chibi and names the picture for screen readers", async () => {
    const wrapper = await draw({});
    const scene = wrapper.get("[data-testid=agent-scene]");
    expect(scene.attributes("role")).toBe("img");
    expect(scene.attributes("aria-label")).toBe("HR assistant at its desk");
    expect(scene.attributes("data-variant")).toBe("hr");
    expect(wrapper.get("[data-testid=ai-buddy]").attributes("data-variant")).toBe("hr");
    wrapper.unmount();
  });

  it("shows the newest lines on the screen, and code-like bars before there are any", async () => {
    const wrapper = await draw({ lines: ["Ertalabki xulosa yuborildi", "Ish haqi: oktabr tayyor"] });
    expect(wrapper.findAll("[data-testid=scene-line]").map((line) => line.text())).toEqual(["Ertalabki xulosa yuborildi", "Ish haqi: oktabr tayyor"]);
    await wrapper.setProps({ lines: [] });
    expect(wrapper.findAll("[data-testid=scene-line]")).toHaveLength(0);
    expect(wrapper.findAll(".sc-bar").length).toBeGreaterThan(0);
    wrapper.unmount();
  });

  it("types the newest line out letter by letter while it works", async () => {
    vi.useFakeTimers();
    const wrapper = await draw({ state: "working", lines: ["Hujjatlar tekshirildi"] });
    expect(wrapper.get("[data-testid=scene-line]").text()).toBe("");
    await vi.advanceTimersByTimeAsync(45 * 6);
    expect(wrapper.get("[data-testid=scene-line]").text()).toBe("Hujjat");
    await vi.advanceTimersByTimeAsync(45 * 40);
    expect(wrapper.get("[data-testid=scene-line]").text()).toBe("Hujjatlar tekshirildi");
    wrapper.unmount();
  });

  it("asleep: the screen goes dark, the chibi sleeps, and night is marked for the window", async () => {
    const wrapper = await draw({ state: "asleep", night: true, lines: ["one"] });
    const scene = wrapper.get("[data-testid=agent-scene]");
    expect(scene.attributes("data-state")).toBe("asleep");
    expect(scene.attributes("data-night")).toBeDefined();
    expect(wrapper.findAll("[data-testid=scene-line]")).toHaveLength(0);
    expect(wrapper.find(".sc-saver").exists()).toBe(true);
    expect(wrapper.get("[data-testid=ai-buddy]").attributes("data-asleep")).toBeDefined();
    wrapper.unmount();
  });

  it("a tap on the chibi lets out hearts while it's awake", async () => {
    const wrapper = await draw({ state: "idle" });
    await wrapper.get(".scene-seat").trigger("click");
    expect(wrapper.get("[data-testid=ai-buddy]").attributes("data-action")).toBe("hearts");
    wrapper.unmount();
  });

  it("a tap makes it talk: its lines one after another, with today's count and the next run", async () => {
    const wrapper = await draw({ state: "idle", variant: "voice_tasks", nextRun: "14:30", doneToday: 2 });
    const seat = wrapper.get(".scene-seat");
    await seat.trigger("click");
    expect(wrapper.get("[data-testid=scene-speech]").text()).toBe("Hi! All calm here.");
    await seat.trigger("click");
    expect(wrapper.get("[data-testid=scene-speech]").text()).toBe("Send me a voice note!");
    await seat.trigger("click");
    expect(wrapper.get("[data-testid=scene-speech]").text()).toBe("Done today: 2");
    await seat.trigger("click");
    expect(wrapper.get("[data-testid=scene-speech]").text()).toBe("Next run: 14:30");
    wrapper.unmount();
  });

  it("shows the company's time on the wall clock and its day on the calendar", async () => {
    const wrapper = await draw({ clock: { hours: 15, minutes: 30, day: 6 } });
    expect(wrapper.get("[data-testid=scene-hour]").attributes("transform")).toBe("rotate(105 171 31)");
    expect(wrapper.get("[data-testid=scene-day]").text()).toBe("6");
    wrapper.unmount();
  });

  it("the cat purrs when petted, curls up at night, and the desk has the agent's own thing", async () => {
    const wrapper = await draw({ state: "idle", variant: "photo_checker" });
    await wrapper.get("[data-testid=scene-cat]").trigger("click");
    expect(wrapper.get("[data-testid=scene-cat-says]").text()).toBe("Mrr!");
    expect(wrapper.find(".sc-cat-sleep").exists()).toBe(false);
    expect(wrapper.get("[data-testid=scene-prop]").attributes("data-prop")).toBe("photo");
    await wrapper.setProps({ night: true });
    expect(wrapper.find(".sc-cat-sleep").exists()).toBe(true);
    wrapper.unmount();
  });

  it("something new on its screen gets a sparkle and a cheer; asleep it dreams in Zzz", async () => {
    const wrapper = await draw({ state: "idle", lines: ["Kassa: tekshirildi"] });
    expect(wrapper.find("[data-testid=scene-burst]").exists()).toBe(false);
    await wrapper.setProps({ lines: ["Kassa: tekshirildi", "3 ta vazifa yaratildi"] });
    expect(wrapper.find("[data-testid=scene-burst]").exists()).toBe(true);
    expect(wrapper.get("[data-testid=ai-buddy]").attributes("data-action")).toBe("cheer");
    expect(wrapper.find(".scene-zzz").exists()).toBe(false);
    await wrapper.setProps({ state: "asleep" });
    expect(wrapper.find(".scene-zzz").exists()).toBe(true);
    wrapper.unmount();
  });

  it("with reduced motion it sits still: no faces cycling, the line shown whole", async () => {
    document.documentElement.dataset.motion = "reduced";
    vi.useFakeTimers();
    const wrapper = await draw({ state: "working", lines: ["Ish haqi: oktabr tayyor"] });
    expect(wrapper.get("[data-testid=scene-line]").text()).toBe("Ish haqi: oktabr tayyor");
    expect(wrapper.get("[data-testid=ai-buddy]").attributes("data-action")).toBe("type");
    await vi.advanceTimersByTimeAsync(10_000);
    expect(wrapper.get("[data-testid=ai-buddy]").attributes("data-action")).toBe("type");
    wrapper.unmount();
  });
});
