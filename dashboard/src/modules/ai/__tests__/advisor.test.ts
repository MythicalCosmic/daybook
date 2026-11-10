// Maslahatchi: its numbers read from a review's facts, its chibi in the family, the review card,
// its page (the latest review, the history, empty states) and "Ask the advisor", a panel of its own
// height whose messages scroll inside it with the composer pinned at the bottom.
import "@/core/modules";

import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { mergeModuleMessages } from "@/i18n";
import { json } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

import { emptyKey, followsNewest, periodLabel, reviewKpis, signalsByKey, writerKey } from "../advisor";
import type { Briefing, BriefingFacts, BriefingLatest } from "../briefings";
import AdvisorChat from "../components/AdvisorChat.vue";
import AgentScene from "../components/AgentScene.vue";
import AiBuddy from "../components/AiBuddy.vue";
import BriefingReview from "../components/BriefingReview.vue";
import en from "../i18n/en.json";
import ru from "../i18n/ru.json";
import uz from "../i18n/uz.json";
import { activityReactions, buddyVariant } from "../lib";
import AdvisorPage from "../pages/AdvisorPage.vue";
import { SIGNATURE_MOVE } from "../scene";

const figure = (value: string, previous: string | null, change_pct: string | null) => ({
  value,
  previous,
  average: previous,
  change: null,
  change_pct,
  vs_average: null,
  vs_average_pct: change_pct,
});

function facts(over: Partial<BriefingFacts> = {}): BriefingFacts {
  return {
    version: 1,
    kind: "weekly",
    period: { kind: "weekly", start: "2026-11-09", end: "2026-11-15" },
    today: "2026-11-16",
    currency: "UZS",
    domains: ["finance", "sales"],
    every_branch: true,
    finance: {
      revenue: figure("20000000.00", "18000000.00", "11.1"),
      gross_profit: figure("7800000.00", "7200000.00", "8.3"),
      gross_margin: { value: "39.0", previous: "40.0", average: "40.0", change_pts: "-1.0", vs_average_pts: "-1.0" },
      expenses: figure("14700000.00", "14300000.00", "2.8"),
      profit: figure("5300000.00", "3700000.00", "43.2"),
      margin: { value: "26.5", previous: "20.6", average: "20.6", change_pts: "5.9", vs_average_pts: "5.9" },
      compared_periods: 4,
      branches: [
        {
          id: 1,
          name: "Chilonzor",
          url: "/c/1/finance/reports/pnl?branch=1",
          revenue: figure("12000000.00", "10000000.00", "20.0"),
          gross_profit: figure("5400000.00", "4000000.00", "35.0"),
          gross_margin: { value: "45.0", previous: "40.0", average: "40.0", change_pts: "5.0", vs_average_pts: "5.0" },
          expenses: figure("9100000.00", "6500000.00", "40.0"),
          profit: figure("2900000.00", "3500000.00", "-17.1"),
          margin: null,
        },
        {
          id: 2,
          name: "Yunusobod",
          url: "/c/1/finance/reports/pnl?branch=2",
          revenue: figure("8000000.00", "8000000.00", "0.0"),
          gross_profit: figure("2400000.00", "3200000.00", "-25.0"),
          gross_margin: { value: "30.0", previous: "40.0", average: "40.0", change_pts: "-10.0", vs_average_pts: "-10.0" },
          expenses: figure("5600000.00", "4800000.00", "16.7"),
          profit: figure("-200000.00", "3200000.00", null),
          margin: null,
        },
      ],
      cash: {
        now: "29100000.00",
        low_30: { date: "2026-11-23", balance: "3200000.00" },
        low_90: { date: "2026-11-23", balance: "3200000.00" },
        below_zero_on: null,
        runway_days: null,
        horizon_days: 90,
        url: "/c/1/finance/calendar",
      },
      url: "/c/1/finance/reports/pnl",
    },
    signals: [{ key: "branch:2:margin", kind: "branch_margin", tone: "bad", weight: 16, subject: "Yunusobod", values: {}, url: "/c/1/finance/reports/pnl?branch=2" }],
    ...over,
  };
}

function review(over: Partial<Briefing> = {}): Briefing {
  return {
    id: 41,
    kind: "weekly",
    day: "2026-11-09",
    period: { kind: "weekly", start: "2026-11-09", end: "2026-11-15" },
    headline: "Week of 9–15 November: revenue 20 mln UZS, up 11.1% on the week before.",
    written_by: "ai",
    written_at: "2026-11-16T08:00:04+05:00",
    language: "en",
    sections: [
      { key: "went_well", title: "What went well", bullets: ["Revenue grew to 20 mln UZS."], facts: ["revenue"] },
      { key: "went_wrong", title: "What went wrong", bullets: ["Yunusobod: gross margin down to 30% (it was 40%)."], facts: ["branch:2:margin"] },
    ],
    actions: [
      { text: "Yunusobod: check purchase prices and discounts.", fact: "branch:2:margin", label: "Open the pharmacy's report", url: "/c/1/finance/reports/pnl?branch=2" },
      { text: "Transport: look into it.", fact: "expense:9", label: "Open the expense", url: "/c/1/finance/reports/category-trend?category=9" },
    ],
    facts: facts(),
    ...over,
  };
}

function latest(over: Partial<BriefingLatest> = {}): BriefingLatest {
  return {
    review: review(),
    next: { weekly: "2026-11-23T08:00:00+05:00", monthly: "2026-12-01T08:00:00+05:00" },
    writer: "ai",
    advisor_on: true,
    chat: true,
    has_data: true,
    can_regenerate: true,
    regenerations_left: 3,
    can_configure: true,
    ...over,
  };
}

const t = (key: string, named?: Record<string, unknown>) => (named ? `${key}:${JSON.stringify(named)}` : key);

beforeEach(() => {
  mergeModuleMessages("ai", { en, ru, uz });
  Element.prototype.scrollIntoView = vi.fn();
  Element.prototype.scrollTo = vi.fn();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("the numbers over a review", () => {
  it("are read from its facts: revenue, gross margin in points, profit and cash's low point", () => {
    const kpis = reviewKpis(facts(), t, "en");

    expect(kpis.map((kpi) => kpi.id)).toEqual(["revenue", "gross_margin", "profit", "cash_low"]);
    expect(kpis[0]).toMatchObject({ value: "20000000.00", format: "money", compact: true, delta: 11.1 });
    expect(kpis[1]).toMatchObject({ value: 39, format: "percent", delta: -1, points: true });
    expect(kpis[3]!.value).toBe("3200000.00");
    expect(kpis[3]!.hint).toContain("23 Nov");
  });

  it("without the books, the tills and the late arrivals", () => {
    const kpis = reviewKpis(
      facts({
        finance: undefined,
        sales: {
          net: figure("600000.00", "500000.00", "20.0"),
          receipts: { value: 20, previous: 25, average: null, change: -5, vs_average_pct: null },
          average_receipt: figure("30000.00", "20000.00", "50.0"),
          url: "/c/1/sales",
        },
        attendance: { late: { value: 4, previous: 1, average: null }, present: 40, rostered: 42, on_time_pct: "90.0", url: "/c/1/attendance/reports" },
      }),
      t,
      "en",
    );

    expect(kpis.map((kpi) => kpi.id)).toEqual(["net", "receipts", "average_receipt", "late"]);
    expect(kpis[3]).toMatchObject({ value: 4, inverse: true });
  });

  it("names the period, who wrote it and what an empty page says", () => {
    expect(periodLabel({ kind: "weekly", start: "2026-11-09", end: "2026-11-15" }, "en")).toBe("9–15 Nov 2026");
    expect(periodLabel({ kind: "monthly", start: "2026-10-01", end: "2026-10-31" }, "uz")).toBe("Oktabr 2026");
    expect(periodLabel({ kind: "monthly", start: "2026-10-01", end: "2026-10-31" }, "ru")).toBe("Октябрь 2026");
    expect(writerKey("ai")).toBe("ai.advisor.writtenByAi");
    expect(emptyKey(latest({ review: null, has_data: false }))).toBe("noData");
    expect(emptyKey(latest({ review: null }))).toBe("first");
    expect(emptyKey(latest({ review: null, next: { weekly: null, monthly: null } }))).toBe("off");
    expect(signalsByKey(facts()).get("branch:2:margin")?.subject).toBe("Yunusobod");
  });

  it("the chat follows a new answer unless its reader scrolled up", () => {
    expect(followsNewest({ scrollTop: 920, scrollHeight: 1400, clientHeight: 420 })).toBe(true);
    expect(followsNewest({ scrollTop: 200, scrollHeight: 1400, clientHeight: 420 })).toBe(false);
    expect(followsNewest(null)).toBe(true);
  });
});

describe("Maslahatchi's chibi", () => {
  it("is the advisor of the family: its own look, move and reactions", () => {
    expect(buddyVariant("advisor")).toBe("advisor");
    expect(SIGNATURE_MOVE.advisor).toBe("star");
    expect(activityReactions([{ agent: "advisor", kind: "weekly_sent" }, { agent: "advisor", kind: "review_rewritten" }])).toEqual([
      { key: "advisor", action: "cheer" },
      { key: "advisor", action: "star" },
    ]);
  });

  it("wears a navy suit with a gold tie and a chart pin, and carries a briefcase that moves with its hand", async () => {
    const made = await testApp("/c/1/ai");
    const wrapper = mount(AiBuddy, { props: { mood: "on", variant: "advisor" }, global: { plugins: made.plugins } });

    expect(wrapper.attributes("data-variant")).toBe("advisor");
    expect(wrapper.find("[data-prop=suit]").exists()).toBe(true);
    expect(wrapper.find("[data-prop=chart]").exists()).toBe(true);
    const briefcase = wrapper.get("[data-prop=briefcase]");
    expect(briefcase.classes()).toContain("buddy-arm-left");
    expect(wrapper.findAll(".buddy-sleeve")).toHaveLength(2);
  });

  it("has a little bar chart on its desk", async () => {
    const made = await testApp("/c/1/ai");
    const wrapper = mount(AgentScene, { props: { variant: "advisor", state: "working", label: "The advisor at its desk" }, global: { plugins: made.plugins } });

    expect(wrapper.get("[data-testid=scene-prop]").attributes("data-prop")).toBe("advisor");
    expect(wrapper.findAll(".sc-bars rect")).toHaveLength(4);
    expect(wrapper.get("[data-testid=ai-buddy]").attributes("data-variant")).toBe("advisor");
  });
});

describe("the review card", () => {
  it("shows the headline, its numbers, the two lists, what to do and each pharmacy", async () => {
    const made = await testApp("/c/1/ai/advisor");
    const { wrapper } = mountWithProviders(BriefingReview, { props: { review: review(), agentName: "Advisor", on: true }, plugins: made.plugins });
    await flushPromises();

    expect(wrapper.get("[data-testid=advisor-headline]").text()).toContain("revenue 20 mln UZS");
    expect(wrapper.get("[data-testid=advisor-writer]").text()).toBe("Written by Claude");
    expect(wrapper.findAll("[data-kpi]")).toHaveLength(4);
    expect(wrapper.get("[data-section=went_wrong]").text()).toContain("Yunusobod");
    const actions = wrapper.findAll("[data-testid=advisor-actions] li");
    expect(actions).toHaveLength(2);
    expect(actions[0]!.text()).toContain("Open the pharmacy's report");
    expect(actions[0]!.find("a").attributes("href")).toBe("/c/1/finance/reports/pnl?branch=2");
    const rows = wrapper.findAll("[data-testid=advisor-branches] tbody tr");
    expect(rows.map((row) => row.attributes("data-branch"))).toEqual(["1", "2"]);
    expect(rows[1]!.text()).toContain("−10");
  });
});

interface Call {
  method: string;
  url: string;
  body?: unknown;
}

function stubApi(answers: { latest?: BriefingLatest; history?: Briefing[]; conversations?: unknown[] } = {}): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init?: RequestInit) => {
      const call = { method: init?.method ?? "GET", url: String(input), body: init?.body ? JSON.parse(String(init.body)) : undefined };
      calls.push(call);
      if (call.url.includes("/briefings/latest/")) return json(answers.latest ?? latest());
      if (call.url.includes("/briefings/advisor/conversations/")) {
        return call.method === "POST" ? json({ id: 9, title: "", created_at: "2026-11-16T09:00:00+05:00" }, 201) : json(answers.conversations ?? []);
      }
      if (call.url.includes("/briefings/regenerate/")) return json({ queued: true }, 202);
      if (/\/briefings\/\d+\//.test(call.url)) return json(review({ id: 40, headline: "An older week." }));
      if (call.url.includes("/briefings/")) return json({ results: answers.history ?? [] });
      if (call.url.includes("/turns/") && call.method === "POST") return json({ turn_id: 77 }, 202);
      if (call.url.includes("/ai/turns/77/")) return json({ id: 77, status: "running", steps: [{ label: "The latest business review", status: "running", ms: null }], text: "", error_code: "", message_id: null });
      if (call.url.includes("/messages/")) return json([]);
      if (call.url.includes("/ai/status/")) return json({ enabled: true, can_configure: true, claude: "available", features: { chat: true } });
      return json({});
    }),
  );
  return calls;
}

async function page(path = "/c/1/ai/advisor", answers = {}) {
  const calls = stubApi(answers);
  const made = await testApp("/c/1/ai");
  for (const [name, at] of [
    ["ai.agents", "/c/:companyId/ai"],
    ["ai.agent", "/c/:companyId/ai/agents/:key"],
    ["ai.advisor", "/c/:companyId/ai/advisor"],
  ] as const) {
    made.router.addRoute({ path: at, name, component: { render: () => null } });
  }
  await made.router.replace(path);
  const { wrapper } = mountWithProviders(AdvisorPage, { plugins: made.plugins });
  await flushPromises();
  await flushPromises();
  return { wrapper, calls, app: made };
}

describe("the Maslahatchi page", () => {
  it("shows the latest review, when the next comes, and the chat beside it", async () => {
    const { wrapper } = await page();

    expect(wrapper.get("[data-testid=advisor-review]").attributes("data-review")).toBe("41");
    expect(wrapper.get("[data-testid=advisor-writer-pill]").text()).toContain("Claude writes the reviews");
    expect(wrapper.text()).toContain("Next review:");
    expect(wrapper.find("[data-testid=advisor-chat]").exists()).toBe(true);
    expect(wrapper.find("[data-testid=advisor-rewrite]").exists()).toBe(true);
  });

  it("opens an older review from the history", async () => {
    const older = review({ id: 40, day: "2026-11-02", period: { kind: "weekly", start: "2026-11-02", end: "2026-11-08" }, headline: "An older week." });
    const { wrapper, app } = await page("/c/1/ai/advisor", { history: [review(), older] });

    const rows = wrapper.findAll("[data-history]");
    expect(rows.map((row) => row.attributes("data-history"))).toEqual(["40"]);
    await rows[0]!.trigger("click");
    await flushPromises();
    await flushPromises();

    expect(app.router.currentRoute.value.query.review).toBe("40");
    expect(wrapper.get("[data-testid=advisor-headline]").text()).toBe("An older week.");
  });

  it("before the first review says when it comes, and can write it now", async () => {
    const { wrapper, calls } = await page("/c/1/ai/advisor", { latest: latest({ review: null, writer: "template" }) });

    expect(wrapper.get("[data-testid=advisor-empty]").attributes("data-empty")).toBe("first");
    await wrapper.get("[data-testid=advisor-rewrite]").trigger("click");
    await flushPromises();

    const posted = calls.find((call) => call.url.includes("/briefings/regenerate/"));
    expect(posted?.method).toBe("POST");
    expect(posted?.body).toEqual({ kind: "weekly" });
  });

  it("without data in the reader's scope says so, without Write it now", async () => {
    const { wrapper } = await page("/c/1/ai/advisor", { latest: latest({ review: null, has_data: false, chat: false }) });

    expect(wrapper.get("[data-testid=advisor-empty]").attributes("data-empty")).toBe("noData");
    expect(wrapper.find("[data-testid=advisor-rewrite]").exists()).toBe(false);
  });

  it("offers the chat as a teaser where it isn't open yet", async () => {
    const { wrapper } = await page("/c/1/ai/advisor", { latest: latest({ chat: false, advisor_on: false }) });

    expect(wrapper.find("[data-testid=advisor-chat]").exists()).toBe(false);
    expect(wrapper.get("[data-testid=advisor-chat-teaser]").text()).toContain("Switch the advisor on");
  });
});

describe("Ask the advisor", () => {
  it("is a panel of its own height: the messages scroll inside it, the composer stays at its bottom", async () => {
    stubApi();
    const made = await testApp("/c/1/ai/advisor");
    const { wrapper } = mountWithProviders(AdvisorChat, { props: { agentName: "Advisor" }, plugins: made.plugins });
    await flushPromises();

    const panel = wrapper.get("[data-testid=advisor-chat]");
    expect(panel.classes()).toEqual(expect.arrayContaining(["flex", "flex-col", "overflow-hidden", "min-h-0"]));
    const thread = wrapper.get("[data-testid=advisor-thread]");
    expect(thread.classes()).toEqual(expect.arrayContaining(["flex-1", "overflow-y-auto", "min-h-0"]));
    const children = panel.element.children;
    expect(children[children.length - 1]!.getAttribute("data-testid")).toBe("advisor-composer-bar");
    expect(wrapper.get("[data-testid=advisor-composer-bar]").classes()).toContain("shrink-0");
    expect(wrapper.findAll("[data-question]")).toHaveLength(4);
  });

  it("asks in a new advisor conversation and shows the answer forming", async () => {
    const calls = stubApi();
    const made = await testApp("/c/1/ai/advisor");
    const { wrapper } = mountWithProviders(AdvisorChat, { props: { agentName: "Advisor" }, plugins: made.plugins });
    await flushPromises();

    await wrapper.get("[data-question='ai.advisor.chat.try.branch']").trigger("click");
    await flushPromises();
    await flushPromises();

    const made_ = calls.find((call) => call.method === "POST" && call.url.includes("/briefings/advisor/conversations/"));
    expect(made_).toBeTruthy();
    const turn = calls.find((call) => call.method === "POST" && call.url.includes("/ai/conversations/9/turns/"));
    expect(turn?.body).toEqual({ text: "Can I afford a second pharmacy?", page: "ai/advisor" });
    expect(wrapper.find("[data-testid=advisor-live-answer]").exists()).toBe(true);
    expect(wrapper.find("[data-testid=advisor-stop]").exists()).toBe(true);
  });
});
