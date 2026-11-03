// An agent's own page (briefs/v5-agent-page.md): its logic — the status pill, the scene's state,
// night and lines, the KPI strip read from the API's strings, dollars, tokens and times, the old
// drawer's links — and the page against a stubbed API: the section from the URL, every state,
// read-only without ai.configure, and the switch and Run now.
// The registry first, as in the app: it is what loads every module's index.ts (see core/modules.ts).
import { modules } from "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { i18n, mergeModuleMessages } from "@/i18n";
import { json } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

import { agentKpis, agentStatus, durationText, isNight, isScheduled, monthShare, sceneLines, screenText, sceneOf, tokensText, upcomingWhen, usdText, type Translate } from "../agentPage";
import AgentScene from "../components/AgentScene.vue";
import en from "../i18n/en.json";
import AgentPage from "../pages/AgentPage.vue";
import { agentDrawerRedirect } from "../routes";
import type { ActivityItem, AgentDetail, AiStatus } from "../types";
import { activity, agent, agentDetail, agentRun, status, usageDays } from "./fixtures";

// ECharts doesn't draw in jsdom: the chart says what it was given instead.
vi.mock("@/components/BarChart.vue", async () => {
  const { defineComponent, h } = await import("vue");
  return {
    default: defineComponent({
      name: "BarChart",
      props: { categories: { type: Array, default: () => [] }, series: { type: Array, default: () => [] } },
      setup: (props) => () => h("div", { "data-testid": "bar-chart", "data-days": props.categories.length, "data-series": props.series.length }),
    }),
  };
});

const NOW = new Date("2026-11-03T14:40:00+05:00");
const tr: Translate = (key, named, plural) => (plural === undefined ? i18n.global.t(key, named ?? {}) : i18n.global.t(key, named ?? {}, plural));
const ctx = (overrides: Partial<Parameters<typeof agentKpis>[1]> = {}) => ({ t: tr, lang: "en" as const, timeZone: "Asia/Tashkent", now: NOW.getTime(), aiOn: true, ...overrides });

beforeEach(() => {
  mergeModuleMessages("ai", { en, ru: en, uz: en });
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

describe("an agent's page: the logic", () => {
  it("puts a status pill on each state", () => {
    expect(agentStatus(agent({ running: true }), true)).toEqual({ key: "working", tone: "primary", live: true });
    expect(agentStatus(agent(), true)).toMatchObject({ key: "on", tone: "success" });
    expect(agentStatus(agent({ enabled: false }), true)).toMatchObject({ key: "off", tone: "neutral" });
    expect(agentStatus(agent(), false)).toMatchObject({ key: "ai_off", tone: "neutral" });
    expect(agentStatus(agent({ enabled: false, available: false, unavailable_reason: "needs_claude" }), true)).toMatchObject({ key: "needs_claude", tone: "warning" });
  });

  it("shows the scene working, waiting or asleep, from the agent's own fields so a switch shows at once", () => {
    expect(sceneOf(agentDetail({ running: true, scene: "working" }), true)).toBe("working");
    expect(sceneOf(agentDetail({ scene: "idle" }), true)).toBe("idle");
    // Switched off here before the server answers: asleep already.
    expect(sceneOf(agentDetail({ enabled: false, scene: "idle" }), true)).toBe("asleep");
    expect(sceneOf(agentDetail({ available: false, unavailable_reason: "needs_claude" }), true)).toBe("asleep");
    expect(sceneOf(agentDetail(), false)).toBe("asleep");
    // "Run now" pressed: at work before the next answer.
    expect(sceneOf(agentDetail({ running: true, scene: "idle" }), true)).toBe("working");
  });

  it("darkens the room from 20:00 to 06:00 by the company's clock", () => {
    const at = (iso: string) => isNight("Asia/Tashkent", new Date(iso).getTime());
    expect([at("2026-11-03T19:59:00+05:00"), at("2026-11-03T20:00:00+05:00"), at("2026-11-04T05:59:00+05:00"), at("2026-11-04T06:00:00+05:00")]).toEqual([false, true, true, false]);
    // 20:30 in Tashkent is still afternoon in London: the company's clock decides.
    expect(isNight("Europe/London", new Date("2026-11-03T20:30:00+05:00").getTime())).toBe(false);
  });

  it("puts what it did and its runs on its screen, newest last, a quiet check only once", () => {
    const items = [
      activity(3, { text: "Bekzod told: Kassani sanash is late", created_at: "2026-11-03T14:30:01+05:00" }),
      activity(2, { text: "Alisher told: Muzlatgich is late", created_at: "2026-11-03T14:30:00.500+05:00" }),
      activity(1, { text: "Morning plan sent", created_at: "2026-11-03T09:00:00+05:00" }),
    ];
    const runs = [
      agentRun(14, { status: "running", finished_at: null, duration_ms: null, started_at: "2026-11-03T14:39:00+05:00", done: 0 }),
      agentRun(13, { started_at: "2026-11-03T14:35:00+05:00", finished_at: "2026-11-03T14:35:01+05:00", done: 0 }),
      agentRun(12),
      agentRun(11, { started_at: "2026-11-03T14:00:00+05:00", finished_at: "2026-11-03T14:00:01+05:00", done: 0 }),
      agentRun(10, { started_at: "2026-11-03T13:30:00+05:00", finished_at: "2026-11-03T13:30:05+05:00", status: "error", done: 0 }),
    ];
    expect(sceneLines(items, runs, tr)).toEqual([
      "Stopped with an error",
      "Alisher told: Muzlatgich is late",
      "Bekzod told: Kassani sanash is late",
      "Finished: 2 actions",
      "Checked, nothing new",
      "Working…",
    ]);
    expect(sceneLines(items, runs, tr, 3)).toEqual(["Finished: 2 actions", "Checked, nothing new", "Working…"]);
    expect(sceneLines([], [], tr)).toEqual([]);
    // The agent's own name isn't repeated on its screen.
    const plan = [{ text: "Ertalabki reja (Dilnoza Karimova): bugun muddati — 3", created_at: "2026-11-03T03:30:00Z" }];
    expect(sceneLines(plan, [], tr, 6, "Ertalabki reja")).toEqual(["Dilnoza Karimova: bugun muddati — 3"]);
    expect(screenText("Ertalabki reja — yuborildi", "Ertalabki reja")).toBe("yuborildi");
    expect(screenText("Told Bekzod that «Kassa» is late", "Deadline watcher")).toBe("Told Bekzod that «Kassa» is late");
    expect(screenText("Ertalabki reja", "Ertalabki reja")).toBe("Ertalabki reja");
  });

  it("words a run so it fits the scene's screen (26 characters) in every language", async () => {
    const dictionaries = [en, (await import("../i18n/ru.json")).default, (await import("../i18n/uz.json")).default] as Record<string, string>[];
    for (const words of dictionaries) {
      const texts = ["ai.agent.line.running", "ai.agent.line.error", "ai.agent.line.quiet"].map((key) => words[key]!);
      // Every plural form of "Finished: 99 actions".
      texts.push(...words["ai.agent.line.done"]!.split("|").map((form) => form.trim().replace("{n}", "99")));
      expect(texts.filter((text) => text.length > 26)).toEqual([]);
    }
  });

  it("reads dollars from the API's strings, and never says $0.00 for something spent", () => {
    expect(usdText("0.421300")).toBe("$0.42");
    expect(usdText("0.010000")).toBe("$0.01");
    // Haiku's calls cost fractions of a cent: four places below a cent.
    expect(usdText("0.003400")).toBe("$0.0034");
    expect(usdText("0.000638")).toBe("$0.0006");
    expect(usdText("0.000040")).toBe("<$0.0001");
    expect(usdText("12.5")).toBe("$12.50");
    expect(usdText("20.00")).toBe("$20.00");
    expect(usdText("0.000000")).toBe("$0.00");
    expect(usdText(null)).toBeNull();
    expect(usdText("")).toBeNull();
  });

  it("shortens tokens from ten thousand up, in each language", () => {
    expect(tokensText(48210, "uz", true)).toBe("48,2 ming");
    expect(tokensText(48210, "ru", true)).toBe("48,2 тыс.");
    expect(tokensText(48210, "en", true)).toBe("48.2K");
    expect(tokensText(9870, "en", true)).toBe("9,870");
    expect(tokensText(48210, "uz")).toBe("48 210");
    expect(tokensText(null, "uz")).toBe("—");
  });

  it("says how long a run or a call took", () => {
    expect(durationText(40, "uz")).toBe("<0,1 s");
    expect(durationText(2400, "uz")).toBe("2,4 s");
    expect(durationText(42_000, "ru")).toBe("42 с");
    expect(durationText(185_000, "uz")).toBe("3 daq 5 s");
    expect(durationText(120_000, "en")).toBe("2m");
    expect(durationText(null, "en")).toBe("—");
  });

  it("builds the numbers under the scene from the API's strings", () => {
    const [last, next, tokens, cost] = agentKpis(agentDetail(), ctx());
    expect(last).toMatchObject({ value: "14:30", hint: "10 min ago · 2.4s", status: { tone: "success", label: "Done", live: false } });
    expect(next).toMatchObject({ value: "15:00", hint: "in 20 min" });
    expect(tokens).toMatchObject({ value: "48.2K", secondary: "/ 6,930", hint: "In / out · 37 calls" });
    // 0.4213 of the company's 3.50 this month.
    expect(cost).toMatchObject({ value: "$0.42", hint: "12% of the company’s AI spending" });
    expect(cost!.hidden).toBeUndefined();
  });

  it("hides the money from people who don't set up AI: 'Hidden', never 0", () => {
    const usage = { month: { calls: 37, input_tokens: 48210, output_tokens: 6930, cache_read_tokens: 0, cost_usd: null }, days: usageDays(), company: null };
    const cost = agentKpis(agentDetail({ usage }), ctx())[3]!;
    expect(cost).toMatchObject({ value: "Hidden", hidden: true, hint: "Only people who set up AI see it" });
    expect(cost.value).not.toContain("0");
    expect(monthShare(usage)).toBeNull();
  });

  it("says when an agent hasn't run yet, works as things arrive, or is off", () => {
    const fresh = agentKpis(agentDetail({ runs: [], last_run_at: null }), ctx())[0]!;
    expect(fresh).toMatchObject({ value: "—", hint: "Hasn’t run yet" });
    expect(fresh.status).toBeUndefined();
    const voice = agentDetail({ key: "voice_tasks", schedule: "When a voice message arrives", next_run_at: null, runs: [], upcoming: [{ at: null, kind: "item", label: "Works when a voice note arrives" }] });
    expect(agentKpis(voice, ctx())[1]).toMatchObject({ value: "Instantly", hint: "When a voice message arrives" });
    expect(agentKpis(agentDetail({ enabled: false, next_run_at: null }), ctx())[1]).toMatchObject({ value: "—", hint: "Planned once it’s on" });
    expect(agentKpis(agentDetail(), ctx({ aiOn: false }))[1]).toMatchObject({ value: "—", hint: "Planned once it’s on" });
    // Tomorrow's run: the hint says when it repeats rather than the same time again; yesterday's
    // run: only how long it took.
    const tomorrow = agentKpis(agentDetail({ schedule: "Weekdays at 08:30", next_run_at: "2026-11-04T08:30:00+05:00", runs: [agentRun(9, { started_at: "2026-11-02T08:30:00+05:00" })] }), ctx());
    expect(tomorrow[0]).toMatchObject({ value: "Yesterday, 08:30", hint: "2.4s" });
    expect(tomorrow[1]).toMatchObject({ value: "Tomorrow, 08:30", hint: "Weekdays at 08:30" });
    // The last run still going: no duration yet, the pill breathes.
    const running = agentKpis(agentDetail({ runs: [agentRun(15, { status: "running", started_at: "2026-11-03T14:39:00+05:00", finished_at: null, duration_ms: null })] }), ctx())[0]!;
    expect(running).toMatchObject({ value: "14:39", hint: "1 min ago", status: { label: "Running", live: true } });
  });

  it("says once when something coming up happens", () => {
    const when = (iso: string, lang: "uz" | "en" = "en") => upcomingWhen(iso, "Asia/Tashkent", lang, NOW.getTime(), lang === "en" ? "Today" : "Bugun");
    expect(when("2026-11-03T15:00:00+05:00")).toEqual({ when: "Today, 15:00", soon: "in 20 min" });
    expect(when("2026-11-03T21:00:00+05:00")).toEqual({ when: "Today, 21:00", soon: "in 6 h" });
    expect(when("2026-11-04T08:30:00+05:00", "uz")).toEqual({ when: "Ertaga, 08:30", soon: null });
    expect(when("2026-11-05T08:30:00+05:00", "uz")).toEqual({ when: "Payshanba, 5-noyabr, 08:30", soon: null });
    expect(upcomingWhen("2026-11-05T08:30:00+05:00", "Asia/Tashkent", "ru", NOW.getTime(), "Сегодня").when).toBe("Четверг, 5 ноября, 08:30");
  });

  it("takes this agent's share of the company's month, and the company's of its budget", () => {
    expect(monthShare(agentDetail().usage)).toEqual({ agent: 0.4213, company: 3.5, budget: 20, share: (0.4213 / 3.5) * 100, budgetShare: 17.5 });
    expect(monthShare({ month: agentDetail().usage.month, company: { month_cost_usd: "0.000000", monthly_budget_usd: "0.00" } })).toMatchObject({ share: null, budgetShare: null });
  });

  it("knows the agents with a schedule (they have Run now)", () => {
    expect(["deadline_watcher", "morning_plan", "hr_assistant"].every((key) => isScheduled({ key, next_run_at: null }))).toBe(true);
    expect(isScheduled({ key: "voice_tasks", next_run_at: null })).toBe(false);
    expect(isScheduled({ key: "new_agent", next_run_at: "2026-11-03T15:00:00+05:00" })).toBe(true);
  });

  it("sends the old drawer's links and Telegram's startapp to the agent's page", () => {
    expect(agentDrawerRedirect({ params: { companyId: "3" }, query: { agent: "voice_tasks", from: "bot" } })).toEqual({
      name: "ai.agent",
      params: { companyId: "3", key: "voice_tasks" },
      query: { from: "bot" },
      replace: true,
    });
    expect(agentDrawerRedirect({ params: { companyId: "3" }, query: {} })).toBe(true);
    expect(agentDrawerRedirect({ params: { companyId: "3" }, query: { agent: "../x" } })).toBe(true);
    const ai = modules.find((module) => module.id === "ai")!;
    expect(ai.deepLinks!.ai!("deadline_watcher")).toBe("ai/agents/deadline_watcher");
    expect(ai.deepLinks!.ai!("")).toBe("ai");
  });
});

// ─── The page against a stubbed API ─────────────────────────────────────────

type Call = { method: string; url: string; body: unknown };

/** The API as the page uses it; like the server, it remembers a switch and a run started. */
function stubApi(detail: AgentDetail | Response, options: { status?: AiStatus; feed?: ActivityItem[] } = {}): Call[] {
  const calls: Call[] = [];
  let current = detail;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init?: RequestInit) => {
      const call = { method: init?.method ?? "GET", url: String(input), body: init?.body ? JSON.parse(String(init.body)) : undefined };
      calls.push(call);
      if (call.url.includes("/ai/status/")) return json(options.status ?? status());
      if (call.url.includes("/ai/activity/")) return json({ results: options.feed ?? [], next_before: null });
      if (current instanceof Response) return current.clone();
      if (call.url.includes("/run/")) {
        current = { ...current, running: true, scene: "working" };
        return json({ queued: true }, 202);
      }
      if (call.method === "PATCH") {
        current = { ...current, ...(call.body as Partial<AgentDetail>) };
        const { runs: _runs, calls: _calls, usage: _usage, upcoming: _upcoming, scene: _scene, ...row } = current;
        return json(row);
      }
      if (call.url.includes("/ai/agents/")) return json(current);
      return json({});
    }),
  );
  return calls;
}

async function openPage(path = "/c/1/ai/agents/deadline_watcher") {
  vi.useFakeTimers({ now: NOW, shouldAdvanceTime: true });
  const app = await testApp("/c/1/ai");
  for (const [name, at] of [
    ["ai.agents", "/c/:companyId/ai"],
    ["ai.agent", "/c/:companyId/ai/agents/:key"],
    ["ai.activity", "/c/:companyId/ai/activity"],
  ] as const) {
    app.router.addRoute({ path: at, name, component: { render: () => null } });
  }
  await app.router.replace(path);
  const { wrapper } = mountWithProviders(AgentPage, { plugins: app.plugins });
  await flushPromises();
  await flushPromises();
  return { app, wrapper };
}

describe("an agent's page", () => {
  it("shows its name, status, scene and numbers, and opens the section the URL names", async () => {
    stubApi(agentDetail(), { feed: [activity(5, { text: "Bekzod told: Kassani sanash is late", created_at: "2026-11-03T14:30:01+05:00" })] });
    const { app, wrapper } = await openPage("/c/1/ai/agents/deadline_watcher?tab=tokens");
    expect(wrapper.find("h1").text()).toBe("Deadline watcher");
    expect(wrapper.find("[data-testid=agent-status]").text()).toBe("On");
    const scene = wrapper.findComponent(AgentScene);
    expect(scene.props()).toMatchObject({ variant: "deadline_watcher", state: "idle", night: false, label: "Deadline watcher: on, waiting for its next job" });
    expect(scene.props("lines")).toEqual(["Stopped with an error", "Checked, nothing new", "Bekzod told: Kassani sanash is late", "Finished: 2 actions"]);
    const kpis = wrapper.find("[data-testid=agent-kpis]").text();
    for (const text of ["14:30", "Done", "15:00", "48.2K", "/ 6,930", "$0.42"]) expect(kpis).toContain(text);
    // ?tab=tokens: the 30 days as two stacked series, the month, the share.
    expect(wrapper.find("[data-testid=agent-usage]").exists()).toBe(true);
    expect(wrapper.find("[data-testid=bar-chart]").attributes()).toMatchObject({ "data-days": "30", "data-series": "2" });
    expect(wrapper.find("[data-testid=agent-share]").text()).toContain("12%");
    // Another section: the URL follows.
    await wrapper.findAll("[role=tab]").find((tab) => tab.text().startsWith("Internal log"))!.trigger("click");
    await flushPromises();
    expect(app.router.currentRoute.value.query.tab).toBe("log");
    expect(wrapper.find("[data-testid=agent-log]").text()).toContain("Claude didn’t answer in time");
    expect(wrapper.find("[data-testid=agent-log]").text()).toContain("claude-haiku-5-5");
  });

  it("opens what it did when the URL names no section, or one it doesn't have", async () => {
    stubApi(agentDetail(), { feed: [activity(5, { text: "Bekzod told: Kassani sanash is late" })] });
    const { wrapper } = await openPage("/c/1/ai/agents/deadline_watcher?tab=nonsense");
    expect(wrapper.find("[data-section-panel]").attributes("data-section-panel")).toBe("done");
    expect(wrapper.find("[data-testid=ai-activity]").text()).toContain("Bekzod told: Kassani sanash is late");
  });

  it("is read-only without ai.configure: no switch to press, no Run now, no money", async () => {
    const hidden = agentDetail({
      runs: [agentRun(12, { cost_usd: null }), agentRun(10, { status: "error", error: null, cost_usd: null })],
      calls: [],
      usage: { month: { calls: 37, input_tokens: 48210, output_tokens: 6930, cache_read_tokens: 0, cost_usd: null }, days: usageDays(), company: null },
    });
    stubApi(hidden, { status: status({ can_configure: false, budget: null }) });
    const { wrapper } = await openPage("/c/1/ai/agents/deadline_watcher?tab=log");
    expect(wrapper.find("[data-testid=agent-switch] [role=switch]").attributes("disabled")).toBeDefined();
    expect(wrapper.find("[data-testid=agent-run]").exists()).toBe(false);
    const cost = wrapper.find("[data-kpi=cost]").text();
    expect(cost).toContain("Hidden");
    expect(cost).not.toMatch(/\$|0\.00/);
    const log = wrapper.find("[data-testid=agent-log]");
    expect(log.findAll("th").map((th) => th.text())).not.toContain("Cost");
    expect(log.text()).not.toContain("$");
    await wrapper.findAll("[role=tab]").find((tab) => tab.text().startsWith("Settings"))!.trigger("click");
    await flushPromises();
    expect(wrapper.find("[data-testid=agent-read-only]").exists()).toBe(true);
    expect(wrapper.find("[data-testid=agent-settings] [role=spinbutton]").attributes("disabled")).toBeDefined();
  });

  it("shows every empty state: never ran, no Claude calls, no key, nothing done, nothing coming", async () => {
    const empty = agentDetail({ runs: [], calls: [], last_run_at: null, upcoming: [], usage: { month: { calls: 0, input_tokens: 0, output_tokens: 0, cache_read_tokens: 0, cost_usd: "0.000000" }, days: usageDays({}), company: null } });
    stubApi(empty, { status: status({ claude: "not_configured" }) });
    const { wrapper } = await openPage();
    expect(wrapper.find("[data-testid=agent-no-activity]").text()).toContain("This agent hasn’t done anything yet");
    expect(wrapper.find("[data-kpi=last]").text()).toContain("Hasn’t run yet");
    const go = async (label: string) => {
      await wrapper.findAll("[role=tab]").find((tab) => tab.text().startsWith(label))!.trigger("click");
      await flushPromises();
    };
    await go("Internal log");
    expect(wrapper.find("[data-testid=agent-no-runs]").text()).toContain("Hasn’t run yet");
    expect(wrapper.find("[data-testid=agent-no-calls]").text()).toContain("until a key is added");
    await go("Tokens");
    expect(wrapper.find("[data-testid=agent-usage]").text()).toContain("No tokens used in the last 30 days");
    expect(wrapper.find("[data-testid=bar-chart]").exists()).toBe(false);
    expect(wrapper.find("[data-testid=agent-share]").exists()).toBe(false);
    await go("Coming up");
    expect(wrapper.find("[data-testid=agent-upcoming-empty]").text()).toContain("Nothing planned");
  });

  it("explains an agent that works as things arrive: no runs to list, its calls below", async () => {
    stubApi(agentDetail({ key: "voice_tasks", name: "Voice tasks", schedule: "When a voice message arrives", next_run_at: null, runs: [], upcoming: [{ at: null, kind: "item", label: "Works when a voice note arrives" }] }));
    const { wrapper } = await openPage("/c/1/ai/agents/voice_tasks?tab=log");
    expect(wrapper.find("[data-testid=agent-no-runs]").text()).toContain("When it works: When a voice message arrives.");
    expect(wrapper.find("[data-testid=agent-run]").exists()).toBe(false);
    expect(wrapper.find("[data-kpi=next]").text()).toContain("Instantly");
  });

  it("switches the agent off: it falls asleep and Run now goes away", async () => {
    const calls = stubApi(agentDetail());
    const { wrapper } = await openPage();
    await wrapper.find("[data-testid=agent-switch] [role=switch]").trigger("click");
    await flushPromises();
    expect(calls.find((call) => call.method === "PATCH")).toMatchObject({ url: expect.stringContaining("/ai/agents/deadline_watcher/"), body: { enabled: false } });
    expect(wrapper.findComponent(AgentScene).props("state")).toBe("asleep");
    expect(wrapper.find("[data-testid=agent-status]").text()).toBe("Off");
    expect(wrapper.find("[data-testid=agent-run]").exists()).toBe(false);
  });

  it("starts a run with Run now: at work at once", async () => {
    const calls = stubApi(agentDetail());
    const { wrapper } = await openPage();
    await wrapper.find("[data-testid=agent-run]").trigger("click");
    await flushPromises();
    expect(calls.some((call) => call.method === "POST" && call.url.endsWith("/ai/agents/deadline_watcher/run/"))).toBe(true);
    expect(wrapper.findComponent(AgentScene).props("state")).toBe("working");
    expect(wrapper.find("[data-testid=agent-status]").text()).toBe("Working");
  });

  it("says so when the agent isn't there", async () => {
    stubApi(json({ detail: "Not found.", code: "not_found" }, 404));
    const { wrapper } = await openPage("/c/1/ai/agents/nobody");
    expect(wrapper.find("[data-testid=agent-not-found]").exists()).toBe(true);
    expect(wrapper.findComponent(AgentScene).exists()).toBe(false);
  });
});
