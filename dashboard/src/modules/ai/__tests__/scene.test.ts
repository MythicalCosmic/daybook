// An agent's room on its own page: what the chibi does at its desk, what its screen shows, where
// it sits as the box changes size, and the room by state, night and a tap.
import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";

import { testApp } from "@/test/plugins";

import AgentScene from "../components/AgentScene.vue";
import { isNightHour, pickSceneAction, ROOM, SCENE_ACTIONS, sceneActionMs, sceneBuddy, screenLines, seatBox, SEAT } from "../scene";

describe("the chibi at its desk", () => {
  it("only does what reads well in a chair, and never the same face twice in a row", () => {
    const seated = new Set([...SCENE_ACTIONS.working, ...SCENE_ACTIONS.idle]);
    for (const moving of ["hop", "dance", "spin", "bounce", "jumpjack", "twist", "disco"]) expect(seated.has(moving as never)).toBe(false);
    expect(pickSceneAction("idle", "blink", () => 0)).not.toBe("blink");
    expect(pickSceneAction("working", "type", () => 0)).toBe("type"); // typing goes on
    expect(pickSceneAction("asleep", "wave")).toBe("idle");
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
