// The agents an owner makes in their own words (briefs/v6-k.md): the form's logic, the New agent
// dialog (gallery, a template's prefill, the checks, the server's field messages, editing), a
// custom agent's card and its page (its last report, its job on the Prompt tab, its settings with
// Delete), read-only without ai.configure.
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { confirmQueue, settleConfirm } from "@/components/useConfirm";
import { i18n, mergeModuleMessages } from "@/i18n";
import { json } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

import { isScheduled, type Translate } from "../agentPage";
import AgentCard from "../components/AgentCard.vue";
import AgentScene from "../components/AgentScene.vue";
import CustomAgentDialog from "../components/CustomAgentDialog.vue";
import { agentsLeft, checkForm, formFromAgent, formFromTemplate, freshForm, payload, whenText } from "../customAgent";
import en from "../i18n/en.json";
import ru from "../i18n/ru.json";
import uz from "../i18n/uz.json";
import { buddyVariant, customColors, CUSTOM_COLORS, isCustomAgent } from "../lib";
import AgentPage from "../pages/AgentPage.vue";
import type { Agent, AgentDetail, CustomAgentInfo, CustomAgentOptions, CustomAgentTemplate } from "../types";
import { agent, agentDetail, status } from "./fixtures";

const t = ((key: string, named: Record<string, unknown> = {}) => i18n.global.t(key, named)) as Translate;

const EVENING: CustomAgentTemplate = {
  key: "evening_report",
  name: "Evening report",
  job: "Every workday evening, sum up the day in a few lines: tasks done and late, who came late, sales against last week.",
  frequency: "weekdays",
  at: "20:00",
  weekday: null,
  month_day: null,
  domains: ["tasks", "reports", "sales"],
  color: "indigo",
  icon: "moon",
  needs: null,
};
const MONDAY: CustomAgentTemplate = { ...EVENING, key: "monday_best", name: "Monday: the best of last week", frequency: "weekly", weekday: 0, at: "09:00", color: "amber", icon: "trophy" };

const OPTIONS: CustomAgentOptions = {
  domains: [
    { key: "tasks", label: "Tasks", available: true, reason: "", feature: null },
    { key: "reports", label: "Team results", available: true, reason: "", feature: null },
    { key: "sales", label: "Sales and cash", available: false, reason: "no_access", feature: "sales" },
  ],
  groups: [{ id: 5, title: "Dorixona xodimlari" }],
  people: [
    { id: 11, name: "Dilnoza Karimova", position: "Owner", photo: null },
    { id: 12, name: "Bekzod Mirzayev", position: "Head of pharmacy", photo: null },
  ],
  max_agents: 10,
  live: 1,
  run_now_left: 10,
  me: { id: 11, name: "Dilnoza Karimova" },
};

function info(overrides: Partial<CustomAgentInfo> = {}): CustomAgentInfo {
  return {
    id: 7,
    job: "Har ish kuni kechqurun kunni xulosa qil: kechikkan vazifalar va kim kechikdi.",
    color: "indigo",
    template: "evening_report",
    frequency: "weekdays",
    at: "20:00",
    weekday: null,
    month_day: null,
    recipients: "me",
    people: [],
    group: null,
    domains: [{ key: "tasks", label: "Tasks" }],
    run_as: { id: 11, name: "Dilnoza Karimova" },
    created_by: { id: 11, name: "Dilnoza Karimova" },
    created_at: "2026-11-01T18:00:00+05:00",
    paused_reason: "",
    paused_text: "",
    last_report: null,
    last_report_at: null,
    ...overrides,
  };
}

function custom(overrides: Partial<Agent> = {}, fields: Partial<CustomAgentInfo> = {}): Agent {
  return agent({
    key: "custom_7",
    name: "Kechki hisobot",
    description: "Har ish kuni kechqurun kunni xulosa qil: kechikkan vazifalar va kim kechikdi.",
    icon: "bot",
    needs_claude: true,
    schedule: "Workdays at 20:00",
    config: {},
    fields: [],
    custom: info(fields),
    ...overrides,
  });
}

function customDetail(fields: Partial<CustomAgentInfo> = {}): AgentDetail {
  return agentDetail({
    ...custom({}, fields),
    prompts: [
      { label: "The report it writes", text: "You are a scheduled report agent of a pharmacy business…" },
      { label: "The same report in another language", text: "You translate a short report…" },
    ],
    instructions: "",
  });
}

type Call = { method: string; url: string; body: unknown };

function stubApi(routes: { detail?: AgentDetail; created?: Response; status?: ReturnType<typeof status> } = {}): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init?: RequestInit) => {
      const call = { method: init?.method ?? "GET", url: String(input), body: init?.body ? JSON.parse(String(init.body)) : undefined };
      calls.push(call);
      if (call.url.includes("/custom-agents/templates/")) return json([EVENING, MONDAY]);
      if (call.url.includes("/custom-agents/options/")) return json(OPTIONS);
      if (call.url.includes("/custom-agents/") && call.method === "POST") return (routes.created ?? json(custom(), 201)).clone();
      if (call.url.includes("/custom-agents/") && call.method === "PATCH") return json(custom());
      if (call.url.includes("/custom-agents/") && call.method === "DELETE") return new Response(null, { status: 204 });
      if (call.url.includes("/ai/status/")) return json(routes.status ?? status());
      if (call.url.includes("/ai/activity/")) return json({ results: [], next_before: null });
      if (call.url.includes("/ai/agents/")) return json(routes.detail ?? customDetail());
      return json({});
    }),
  );
  return calls;
}

async function app(path = "/c/1/ai") {
  const made = await testApp("/c/1/ai");
  for (const [name, at] of [
    ["ai.agents", "/c/:companyId/ai"],
    ["ai.agent", "/c/:companyId/ai/agents/:key"],
    ["ai.activity", "/c/:companyId/ai/activity"],
  ] as const) {
    made.router.addRoute({ path: at, name, component: { render: () => null } });
  }
  await made.router.replace(path);
  return made;
}

const $ = <E extends Element = HTMLElement>(selector: string) => document.querySelector<E>(selector);

async function click(selector: string): Promise<void> {
  const element = $(selector);
  if (!element) throw new Error(`Nothing matches ${selector}`);
  element.click();
  await flushPromises();
}

async function type(selector: string, value: string): Promise<void> {
  const element = $<HTMLInputElement | HTMLTextAreaElement>(selector)!;
  element.value = value;
  element.dispatchEvent(new Event("input"));
  await flushPromises();
}

beforeEach(() => {
  mergeModuleMessages("ai", { en, ru, uz });
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

describe("the form's logic", () => {
  it("knows the agents an owner made, and dresses their chibi in its colour", () => {
    expect(isCustomAgent("custom_7")).toBe(true);
    expect(isCustomAgent("custom_x")).toBe(false);
    expect(buddyVariant("custom_7")).toBe("custom");
    expect(buddyVariant("custom_")).toBe("claude");
    expect(customColors("plum")).toBe(CUSTOM_COLORS.plum);
    expect(customColors("gold")).toBe(CUSTOM_COLORS.sky);
    expect(isScheduled({ key: "custom_7", next_run_at: null })).toBe(true);
  });

  it("fills the form from a template, keeping only what the person may read", () => {
    const form = formFromTemplate(EVENING, OPTIONS.domains);

    expect(form).toMatchObject({ name: "Evening report", template: "evening_report", frequency: "weekdays", at: "20:00", color: "indigo", recipients: "me" });
    expect(form.domains).toEqual(["tasks", "reports"]);
    expect(formFromTemplate(MONDAY, OPTIONS.domains)).toMatchObject({ frequency: "weekly", weekday: 0, at: "09:00" });
    expect(freshForm(OPTIONS.domains)).toMatchObject({ name: "", job: "", frequency: "weekdays", at: "20:00", domains: ["tasks"] });
  });

  it("edits an agent as it is, and sends only what its frequency and readers need", () => {
    const form = formFromAgent({ name: "Kechki hisobot", custom: info({ recipients: "people", people: [{ id: 12, name: "Bekzod Mirzayev" }] }) });

    expect(form).toMatchObject({ name: "Kechki hisobot", recipients: "people", people: [12], domains: ["tasks"] });
    expect(payload({ ...form, weekday: 3, month_day: 9, group: 5 })).toMatchObject({ weekday: null, month_day: null, group: null, people: [12] });
    expect(payload({ ...form, frequency: "monthly", month_day: 1, recipients: "group", group: 5 })).toMatchObject({ month_day: 1, weekday: null, people: [], group: 5 });
  });

  it("checks what it needs before it sends", () => {
    const empty = freshForm([]);

    expect(checkForm(empty)).toEqual({ name: "ai.custom.error.name", job: "ai.custom.error.job", domains: "ai.custom.error.domains" });
    const ready = { ...formFromTemplate(EVENING, OPTIONS.domains) };
    expect(checkForm(ready)).toEqual({});
    expect(checkForm({ ...ready, frequency: "weekly", weekday: null })).toEqual({ weekday: "ai.custom.error.weekday" });
    expect(checkForm({ ...ready, recipients: "people" })).toEqual({ people: "ai.custom.error.people" });
    expect(checkForm({ ...ready, recipients: "group" })).toEqual({ group: "ai.custom.error.group" });
    expect(checkForm({ ...ready, at: "25:00" })).toEqual({ at: "ai.custom.error.at" });
  });

  it("says when it runs in a few words, and how many more there may be", () => {
    expect(whenText(EVENING, t)).toBe("Workdays · 20:00");
    expect(whenText(MONDAY, t)).toBe("Weekly: Monday · 09:00");
    expect(whenText({ frequency: "monthly", month_day: 1, at: "09:00", weekday: null }, t)).toBe("Monthly: day 1 · 09:00");
    expect(agentsLeft([custom(), agent(), custom({ key: "custom_8" })])).toBe(8);
  });

  it("has every text in every language", () => {
    const keys = Object.keys(en).filter((key) => key.startsWith("ai.custom.") || key === "ai.agent.scene.say.custom");
    expect(keys.length).toBeGreaterThan(80);
    for (const dictionary of [uz, ru] as Record<string, string>[]) {
      for (const key of keys) expect(dictionary[key], key).toBeTruthy();
    }
    for (const key of keys) expect((uz as Record<string, string>)[key], key).not.toMatch(/['`]/);
  });
});

describe("the New agent dialog", () => {
  async function open(props: Record<string, unknown> = {}) {
    const made = await app();
    const opened: boolean[] = [];
    const mounted = mountWithProviders(CustomAgentDialog, { plugins: made.plugins, props: { open: true, "onUpdate:open": (value: boolean) => opened.push(value), ...props } });
    await flushPromises();
    await flushPromises();
    return { app: made, opened, ...mounted };
  }

  it("starts from a template, fills the form with it, creates the agent and opens its page", async () => {
    const calls = stubApi();
    const { app: made, opened } = await open();

    expect($("[data-testid=custom-gallery]")).not.toBeNull();
    expect($("[data-template=monday_best]")!.textContent).toContain("Weekly: Monday · 09:00");
    await click("[data-template=evening_report]");

    expect($<HTMLInputElement>("[data-testid=custom-name]")!.value).toBe("Evening report");
    expect($<HTMLTextAreaElement>("[data-testid=custom-job]")!.value).toBe(EVENING.job);
    expect($<HTMLInputElement>("[data-domain=sales] button, [data-domain=sales]")).not.toBeNull();
    await type("[data-testid=custom-name]", "Kechki hisobot");
    await click("[data-testid=custom-submit]");

    const post = calls.find((call) => call.method === "POST")!;
    expect(post.url).toContain("/ai/custom-agents/");
    expect(post.body).toEqual({
      name: "Kechki hisobot",
      job: EVENING.job,
      color: "indigo",
      template: "evening_report",
      frequency: "weekdays",
      at: "20:00",
      weekday: null,
      month_day: null,
      recipients: "me",
      people: [],
      group: null,
      domains: ["tasks", "reports"],
    });
    expect(opened).toContain(false);
    await flushPromises();
    expect(made.router.currentRoute.value.fullPath).toBe("/c/1/ai/agents/custom_7");
  });

  it("written from scratch, it says what is missing and sends nothing", async () => {
    const calls = stubApi();
    await open();

    await click("[data-testid=custom-own]");
    await type("[data-testid=custom-job]", "");
    await click("[data-testid=custom-submit]");

    const dialog = $("[data-testid=custom-form]")!.textContent!;
    expect(dialog).toContain("Give it a name.");
    expect(dialog).toContain("Write what it should do, in a sentence or more.");
    expect(calls.some((call) => call.method === "POST")).toBe(false);
  });

  it("shows the server's message on its field", async () => {
    const calls = stubApi({ created: json({ domains: ["You can't read Sales and cash yourself, so it can't either."] }, 400) });
    await open();
    await click("[data-template=evening_report]");

    await click("[data-testid=custom-submit]");

    expect(calls.filter((call) => call.method === "POST")).toHaveLength(1);
    expect($("[data-testid=custom-form]")!.textContent).toContain("You can't read Sales and cash yourself");
  });

  it("chooses its readers and its colour, and its chibi tries the colour on", async () => {
    const calls = stubApi();
    await open();
    await click("[data-template=evening_report]");

    await click("[data-testid=custom-colors] [data-color=rose]");
    expect($("[data-testid=custom-preview]")!.getAttribute("data-color")).toBe("rose");
    expect($("[data-testid=custom-recipients]")).not.toBeNull();
    await click("[data-testid=custom-submit]");

    expect(calls.find((call) => call.method === "POST")!.body).toMatchObject({ color: "rose" });
  });

  it("edits an agent in place: straight to the form, saved with PATCH", async () => {
    const calls = stubApi();
    const { app: made } = await open({ agent: custom() });

    expect($("[data-testid=custom-gallery]")).toBeNull();
    expect($<HTMLInputElement>("[data-testid=custom-name]")!.value).toBe("Kechki hisobot");
    await type("[data-testid=custom-name]", "Kech");
    await click("[data-testid=custom-submit]");

    const patch = calls.find((call) => call.method === "PATCH")!;
    expect(patch.url).toContain("/ai/custom-agents/7/");
    expect(patch.body).toMatchObject({ name: "Kech", domains: ["tasks"], recipients: "me" });
    expect(made.router.currentRoute.value.fullPath).toBe("/c/1/ai");
  });

  it("says that changing someone else's agent makes you its owner", async () => {
    stubApi();
    await open({ agent: custom({}, { run_as: { id: 30, name: "Madina Saidova" } }) });

    expect($("[data-testid=custom-takes-over]")).not.toBeNull();
  });
});

describe("a custom agent's card", () => {
  it("wears its colour, says it is the owner's own and when it paused itself", async () => {
    const made = await app();
    const { wrapper } = mountWithProviders(AgentCard, { plugins: made.plugins, props: { agent: custom({}, { color: "lime", paused_reason: "left", paused_text: "Its owner no longer works here" }), canConfigure: true, aiOn: true } });
    await flushPromises();

    const chibi = wrapper.find("[data-agent-chibi=custom_7]");
    expect(chibi.attributes("data-variant")).toBe("custom");
    expect(chibi.attributes("data-color")).toBe("lime");
    expect(wrapper.find("[data-testid=agent-own]").text()).toBe("Your own");
    expect(wrapper.find("[data-testid=agent-paused]").attributes("title")).toBe("Its owner no longer works here");
    expect(wrapper.find("[data-testid=agent-run-custom_7]").exists()).toBe(true);
  });
});

describe("a custom agent's page", () => {
  async function page(path: string, routes: Parameters<typeof stubApi>[0] = {}) {
    const calls = stubApi(routes);
    const made = await app(path);
    const { wrapper } = mountWithProviders(AgentPage, { plugins: made.plugins });
    await flushPromises();
    await flushPromises();
    return { app: made, wrapper, calls };
  }

  it("shows its last report first, in its colour", async () => {
    const { wrapper } = await page("/c/1/ai/agents/custom_7", { detail: customDetail({ last_report: "Bugun 1 ta vazifa kechikdi.", last_report_at: "2026-11-02T20:00:12+05:00" }) });

    expect(wrapper.find("h1").text()).toBe("Kechki hisobot");
    expect(wrapper.find("[data-testid=custom-last-report]").text()).toContain("Bugun 1 ta vazifa kechikdi.");
    expect(wrapper.findComponent(AgentScene).props("color")).toBe("indigo");
  });

  it("shows its job and its prompts on the Prompt tab, with Edit", async () => {
    const { wrapper } = await page("/c/1/ai/agents/custom_7?tab=prompt");

    expect(wrapper.find("[data-testid=custom-job-text]").text()).toBe(info().job);
    expect(wrapper.findAll("[data-testid=agent-prompt-toggle]")).toHaveLength(2);
    expect(wrapper.find("[data-testid=agent-instructions]").exists()).toBe(false);
    await wrapper.find("[data-testid=custom-prompt-edit]").trigger("click");
    await flushPromises();
    await flushPromises();
    expect($<HTMLInputElement>("[data-testid=custom-name]")!.value).toBe("Kechki hisobot");
  });

  it("deletes it after a confirm and goes back to the agents", async () => {
    const { wrapper, calls, app: made } = await page("/c/1/ai/agents/custom_7?tab=settings");

    expect(wrapper.find("[data-row=runAs]").text()).toContain("Dilnoza Karimova");
    await wrapper.find("[data-testid=custom-delete]").trigger("click");
    await flushPromises();
    const [request] = confirmQueue.value;
    settleConfirm(request!.id, { reason: "" }, 0);
    await flushPromises();
    await flushPromises();

    expect(calls.find((call) => call.method === "DELETE")!.url).toContain("/ai/custom-agents/7/");
    expect(made.router.currentRoute.value.fullPath).toBe("/c/1/ai");
  });

  it("is read-only without ai.configure", async () => {
    const { wrapper } = await page("/c/1/ai/agents/custom_7?tab=settings", { status: status({ can_configure: false }) });

    expect(wrapper.find("[data-testid=custom-delete]").exists()).toBe(false);
    expect(wrapper.find("[data-testid=agent-read-only]").exists()).toBe(true);
  });

  it("says why nothing is sent when it paused itself or the budget is spent", async () => {
    const { wrapper } = await page("/c/1/ai/agents/custom_7", {
      detail: customDetail({ paused_reason: "no_access", paused_text: "Its owner can't use AI or the dashboard any more" }),
      status: status({ claude: "budget_reached" }),
    });

    expect(wrapper.find("[data-testid=agent-paused-alert]").text()).toContain("Its owner can't use AI");
    expect(wrapper.find("[data-testid=agent-budget-alert]").exists()).toBe(true);
  });
});
