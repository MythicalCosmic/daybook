// The registry first, as in the app: it is what loads every module's index.ts (see core/modules.ts).
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { defineComponent, h, ref } from "vue";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { mergeModuleMessages } from "@/i18n";
import { json } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

import AgentCard from "../components/AgentCard.vue";
import AgentField from "../components/AgentField.vue";
import DraftCard from "../components/DraftCard.vue";
import NewTaskTools from "../components/NewTaskTools.vue";
import TurnOnCard from "../components/TurnOnCard.vue";
import { dictation } from "../dictation";
import en from "../i18n/en.json";
import { toEditable, type EditableDraft } from "../lib";
import type { AgentConfigValue, AgentField as Field } from "../types";
import { AGENTS, agent, aiDraft, status } from "./fixtures";

type Call = { method: string; url: string; body: unknown };

function stubFetch(answer: (call: Call) => Response): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init?: RequestInit) => {
      const call = { method: init?.method ?? "GET", url: input, body: init?.body ? JSON.parse(String(init.body)) : undefined };
      calls.push(call);
      return answer(call);
    }),
  );
  return calls;
}

beforeEach(() => {
  mergeModuleMessages("ai", { en, ru: en, uz: en });
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
  dictation.open = false;
});

describe("fields → form controls", () => {
  async function field(definition: Field, value: AgentConfigValue) {
    const app = await testApp("/c/1/ai");
    const changes: AgentConfigValue[] = [];
    const { wrapper } = mountWithProviders(AgentField, { props: { field: definition, value, onChange: (next: AgentConfigValue) => changes.push(next) }, plugins: app.plugins });
    await flushPromises();
    return { wrapper, changes };
  }

  it("draws a switch for yes/no and sends the new value", async () => {
    const { wrapper, changes } = await field({ key: "auto_create", type: "bool", label: "Create at once", help: "Without asking" }, false);
    expect(wrapper.text()).toContain("Create at once");
    expect(wrapper.text()).toContain("Without asking");
    await wrapper.find("[role=switch]").trigger("click");
    expect(changes).toEqual([true]);
  });

  it("draws a stepper with its unit, kept inside the range", async () => {
    const { wrapper, changes } = await field({ key: "escalate_after_hours", type: "int", label: "Tell after", help: "", min: 1, max: 48, unit: "h" }, 48);
    expect(wrapper.find("[role=spinbutton]").exists()).toBe(true);
    expect(wrapper.text()).toContain("h");
    const buttons = wrapper.findAll("button");
    // "Increase" at the maximum changes nothing; "Decrease" sends 47.
    await buttons.find((button) => button.attributes("aria-label")?.toLowerCase().includes("decrease"))!.trigger("click");
    expect(changes).toEqual([47]);
  });

  it("draws a time picker, and side-by-side choices for a few short options", async () => {
    const time = await field({ key: "at", type: "time", label: "At", help: "" }, "08:30");
    expect((time.wrapper.find("input").element as HTMLInputElement).value).toBe("08:30");
    const choice = await field(
      { key: "who", type: "choice", label: "Who", help: "", options: [{ value: "heads", label: "Heads" }, { value: "managers", label: "Managers" }, { value: "both", label: "Both" }] },
      "both",
    );
    const radios = choice.wrapper.findAll("[role=radio]");
    expect(radios.map((radio) => radio.text())).toEqual(["Heads", "Managers", "Both"]);
    await radios[0]!.trigger("click");
    expect(choice.changes).toEqual(["heads"]);
  });
});

describe("a draft card: problems and their fixes", () => {
  async function card(edit: EditableDraft) {
    vi.useFakeTimers({ now: new Date("2026-11-02T09:30:00+05:00"), shouldAdvanceTime: true });
    const app = await testApp("/c/1/ai");
    const model = ref(edit);
    const Host = defineComponent({
      setup: () => () =>
        h(DraftCard, {
          modelValue: model.value,
          "onUpdate:modelValue": (next: EditableDraft) => (model.value = next),
          index: 1,
          people: [
            { id: 11, name: "Dilnoza Karimova" },
            { id: 16, name: "Bekzod Mirzayev", subtitle: "Kassir" },
          ],
          myId: 11,
          timeZone: "Asia/Tashkent",
        }),
    });
    const { wrapper } = mountWithProviders(Host, { plugins: app.plugins });
    await flushPromises();
    return { wrapper, model };
  }

  it("says who wasn't found and fixes it in one tap", async () => {
    const { wrapper, model } = await card(toEditable(aiDraft())[1]!);
    expect(wrapper.text()).toContain("Nobody called “Bekzod” was found. Who should do it?");
    expect(wrapper.text()).toContain("No deadline was heard.");
    const forMe = wrapper.findAll("[data-fix=me]");
    expect(forMe).toHaveLength(1);
    await forMe[0]!.trigger("click");
    expect(model.value).toMatchObject({ assigneeId: null, assigneeTouched: true });
    expect(wrapper.find("[data-problem=no_assignee_match]").exists()).toBe(false);
    const dueFixes = wrapper.findAll("[data-problem=no_due] [data-fix=due]");
    expect(dueFixes.map((button) => button.text())).toEqual(["Today, 18:00", "Tomorrow, 09:00"]);
    await dueFixes[1]!.trigger("click");
    expect(model.value.dueTouched).toBe(true);
    expect(new Date(model.value.dueAt!).toISOString()).toBe("2026-11-03T04:00:00.000Z");
    expect(wrapper.find("[data-problem]").exists()).toBe(false);
    expect(wrapper.find("[data-testid=draft-when]").text()).toContain("Tomorrow, 09:00");
  });

  it("toggles urgent and photo, and removes with an undo", async () => {
    const { wrapper, model } = await card(toEditable(aiDraft())[0]!);
    expect(wrapper.find("[data-testid=draft-when]").text()).toContain("Ertaga, 10:00");
    const urgent = wrapper.findAll("button").find((button) => button.text() === "Urgent")!;
    await urgent.trigger("click");
    expect(model.value.priority).toBe("urgent");
    const photo = wrapper.findAll("button").find((button) => button.text() === "Photo needed")!;
    expect(photo.attributes("aria-pressed")).toBe("true");
    await photo.trigger("click");
    expect(model.value.proof).toBe("none");
    await wrapper.find("button[aria-label='Remove task 2']").trigger("click");
    expect(model.value.removed).toBe(true);
    await wrapper.findAll("button").find((button) => button.text() === "Undo")!.trigger("click");
    expect(model.value.removed).toBe(false);
  });
});

describe("New task: Dictate and Smart add", () => {
  it("shows nothing while AI can't take instructions", async () => {
    stubFetch(() => json(status({ enabled: false })));
    const app = await testApp("/c/1/tasks");
    const { wrapper } = mountWithProviders(NewTaskTools, { props: { context: { companyId: 1, title: "", close: () => undefined } }, plugins: app.plugins });
    await flushPromises();
    expect(wrapper.find("[data-testid=ai-new-task-tools]").exists()).toBe(false);
  });

  it("closes New task and opens the dictate dialog, Smart add with the title typed so far", async () => {
    stubFetch(() => json(status({ features: { voice: false, smart_text: true, chat: false, photo_checker: false } })));
    const app = await testApp("/c/1/tasks");
    const close = vi.fn();
    const { wrapper } = mountWithProviders(NewTaskTools, { props: { context: { companyId: 1, title: "Alisher kassani sanasin, Bekzod dori buyursin", close } }, plugins: app.plugins });
    await flushPromises();
    expect(wrapper.find("[data-testid=ai-new-task-dictate]").exists()).toBe(false);
    await wrapper.find("[data-testid=ai-new-task-smart]").trigger("click");
    expect(close).toHaveBeenCalled();
    expect(dictation).toMatchObject({ open: true, mode: "text", text: "Alisher kassani sanasin, Bekzod dori buyursin" });
  });
});

describe("agents", () => {
  it("shows what a card says and keeps an agent that needs Claude switched off", async () => {
    const app = await testApp("/c/1/ai");
    const photo = AGENTS[3]!;
    const { wrapper } = mountWithProviders(AgentCard, { props: { agent: photo, canConfigure: true, aiOn: true }, plugins: app.plugins });
    await flushPromises();
    expect(wrapper.text()).toContain("Photo checker");
    expect(wrapper.text()).toContain("Needs Claude");
    expect(wrapper.text()).toContain("Sends task photos to Claude");
    expect(wrapper.find("[role=switch]").attributes("disabled")).toBeDefined();
    expect(wrapper.find("[data-testid=agent-run-photo_checker]").exists()).toBe(false);
  });

  it("offers Run now on a scheduled agent, and switches and opens it", async () => {
    const app = await testApp("/c/1/ai");
    const events: string[] = [];
    const { wrapper } = mountWithProviders(AgentCard, {
      props: { agent: agent({ running: false }), canConfigure: true, aiOn: true, onToggle: (value: boolean) => events.push(`toggle:${value}`), onRun: () => events.push("run"), onOpen: () => events.push("open") },
      plugins: app.plugins,
    });
    await flushPromises();
    expect(wrapper.text()).toContain("Today3");
    await wrapper.find("[data-testid=agent-run-deadline_watcher]").trigger("click");
    await wrapper.find("[role=switch]").trigger("click");
    await wrapper.find("h3 button").trigger("click");
    expect(events).toEqual(["run", "toggle:false", "open"]);
  });

  it("shows the working state while an agent runs", async () => {
    const app = await testApp("/c/1/ai");
    const { wrapper } = mountWithProviders(AgentCard, { props: { agent: agent({ running: true }), canConfigure: true, aiOn: true }, plugins: app.plugins });
    await flushPromises();
    expect(wrapper.find(".is-running").exists()).toBe(true);
    expect(wrapper.text()).toContain("Working…");
    expect(wrapper.find("[data-testid=agent-run-deadline_watcher]").exists()).toBe(false);
  });

  it("turns AI on only with the terms accepted", async () => {
    const calls = stubFetch((call) => (call.url.endsWith("/owner/me/") ? json({ user: {}, language: "en", companies: [] }) : json(status())));
    const app = await testApp("/c/1/ai");
    const { wrapper } = mountWithProviders(TurnOnCard, { plugins: app.plugins });
    await flushPromises();
    await wrapper.find("[data-testid=ai-enable]").trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain("Tick the box to agree to the terms first.");
    expect(calls.some((call) => call.url.includes("settings/enable"))).toBe(false);
    await wrapper.find("[data-testid=ai-terms] [role=checkbox], [data-testid=ai-terms] button, [data-testid=ai-terms]").trigger("click");
    await wrapper.find("[data-testid=ai-enable]").trigger("click");
    await flushPromises();
    const enable = calls.find((call) => call.url.includes("settings/enable"));
    expect(enable).toMatchObject({ method: "POST", body: { accept_terms: true } });
  });
});
