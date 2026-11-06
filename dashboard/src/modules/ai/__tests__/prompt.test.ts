// An agent's prompt on its page: the owner's own instructions (written, saved, taken away), what
// it asks Claude word for word with those instructions after it, read-only without ai.configure,
// and nothing to instruct for an agent that works by fixed rules.
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { mergeModuleMessages } from "@/i18n";
import { json } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

import AgentPrompt from "../components/AgentPrompt.vue";
import en from "../i18n/en.json";
import ru from "../i18n/ru.json";
import uz from "../i18n/uz.json";
import type { AgentDetail } from "../types";
import { agent, agentDetail } from "./fixtures";

const VOICE = agentDetail({
  ...agent({ key: "voice_tasks", name: "Voice tasks" }),
  prompts: [{ label: "Turning a voice note or a typed instruction into tasks", text: "You turn instructions that a manager in a pharmacy said aloud…" }],
  instructions: "",
});

interface Call {
  method: string;
  url: string;
  body: unknown;
}

function stub(): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init?: RequestInit) => {
      const call = { method: init?.method ?? "GET", url: String(input), body: init?.body ? JSON.parse(String(init.body)) : undefined };
      calls.push(call);
      if (call.method === "PATCH") return json(agent({ key: "voice_tasks", name: "Voice tasks" }));
      return json({});
    }),
  );
  return calls;
}

async function show(detail: AgentDetail, canConfigure = true) {
  const app = await testApp("/c/1/ai");
  const mounted = mountWithProviders(AgentPrompt, { plugins: app.plugins, props: { agent: detail, canConfigure } });
  await flushPromises();
  return mounted;
}

beforeEach(() => {
  mergeModuleMessages("ai", { en, ru, uz });
});

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

describe("AgentPrompt", () => {
  it("shows what the agent asks Claude, word for word", async () => {
    stub();
    const { wrapper } = await show(VOICE);
    expect(wrapper.get("[data-testid=agent-prompt-toggle]").text()).toContain("Turning a voice note or a typed instruction into tasks");
    expect(wrapper.get("[data-testid=agent-prompt-text]").text()).toContain("You turn instructions that a manager in a pharmacy said aloud");
    expect(wrapper.find("[data-testid=agent-prompt-yours]").exists()).toBe(false);
  });

  it("saves the owner's own instructions, trimmed, and only once something changed", async () => {
    const calls = stub();
    const { wrapper } = await show(VOICE);
    const save = wrapper.get("[data-testid=agent-instructions-save]");
    expect(save.attributes("disabled")).toBeDefined();

    await wrapper.get("textarea").setValue("  Fridge problems are always urgent.  ");
    expect(wrapper.get("[data-testid=agent-instructions-save]").attributes("disabled")).toBeUndefined();
    await wrapper.get("[data-testid=agent-instructions-save]").trigger("click");
    await flushPromises();

    const patch = calls.find((call) => call.method === "PATCH")!;
    expect(patch.url).toContain("/ai/agents/voice_tasks/");
    expect(patch.body).toEqual({ instructions: "Fridge problems are always urgent." });
  });

  it("shows the saved instructions after each prompt, and only reads them without ai.configure", async () => {
    stub();
    const { wrapper } = await show({ ...VOICE, instructions: "Fridge problems are always urgent." }, false);
    expect(wrapper.find("[data-testid=agent-instructions]").exists()).toBe(false);
    expect(wrapper.text()).toContain("Fridge problems are always urgent.");
    expect(wrapper.get("[data-testid=agent-prompt-yours]").text()).toContain("Then your instructions:");
  });

  it("has nothing to instruct for an agent that works by fixed rules", async () => {
    stub();
    const { wrapper } = await show(agentDetail());
    expect(wrapper.text()).toContain("Works by fixed rules");
    expect(wrapper.find("[data-testid=agent-instructions]").exists()).toBe(false);
  });
});
