// The registry first, as in the app: it is what loads every module's index.ts (see core/modules.ts).
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { confirmQueue, settleConfirm } from "@/components/useConfirm";
import type { Perm } from "@/core/perms";
import { mergeModuleMessages } from "@/i18n";
import { useSessionStore } from "@/stores/session";
import { company, json, me } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

import OutcomeEditor from "../components/reviews/OutcomeEditor.vue";
import RatingPills from "../components/reviews/RatingPills.vue";
import RoundWizard from "../components/reviews/RoundWizard.vue";
import en from "../i18n/en.json";
import ReviewPage from "../pages/ReviewPage.vue";
import ReviewsPage from "../pages/ReviewsPage.vue";
import {
  answeredCount,
  blankRound,
  editQuestion,
  lastHalf,
  lastMonth,
  lastQuarter,
  managerForm,
  managerPayload,
  moveItem,
  payAfter,
  publishProblems,
  roundErrors,
  roundPayload,
  suggestedRating,
} from "../reviews/lib";
import type { Question, Review, Round } from "../reviews/types";

const QUESTIONS: Question[] = [
  { id: "q1", kind: "rating", text: "Dispensing and storage rules", key: "dispensing" },
  { id: "q2", kind: "rating", text: "Customer care", key: "customers" },
  { id: "q3", kind: "text", text: "What went best?", key: "best" },
];

function review(overrides: Partial<Review> = {}): Review {
  return {
    id: 41,
    round: { id: 7, name: "Chilonzor: 3-chorak, 2026", status: "manager", period_start: "2026-07-01", period_end: "2026-09-30", self_due_on: "2026-10-13", manager_due_on: "2026-10-22" },
    member: { id: 9, name: "Alisher Valiyev", photo_url: null },
    position: "Farmatsevt",
    home_branch: { id: 1, name: "Chilonzor", code: "CHL" },
    reviewer: { id: 2, name: "Bekzod Mirzayev", photo_url: null },
    questions: QUESTIONS,
    self_part: { visible: true, state: "sent", sent_at: "2026-10-08T16:10:00Z", answers: { q1: { rating: 4, text: "" }, q2: { rating: 5, text: "" }, q3: { rating: null, text: "Kassa to‘g‘ri chiqdi" } }, average: "4.5" },
    manager_answers: {},
    manager_state: "not_started",
    manager_average: null,
    manager_saved_at: null,
    kpis: {
      taken_at: "2026-10-15T10:00:00Z",
      start: "2026-07-01",
      end: "2026-09-30",
      tasks: { total: 40, on_time: 37, late: 2, missed: 1, on_time_percent: "92.5" },
      attendance: { scheduled_days: 60, attended_days: 59, absent_days: 0, late_arrivals: 2, late_minutes: 25, leave_days: 1, worked_hours: "640.0" },
      discipline: { records: 0, by_kind: {} },
      sales: null,
      learning: null,
      goals: null,
    },
    kpis_at: "2026-10-15T10:00:00Z",
    rating: null,
    summary: "",
    outcome: "none",
    raise_percent: null,
    bonus_amount: null,
    bonus_currency: "UZS",
    promotion_position: null,
    effective_on: null,
    goals: [],
    pay: { amount: "5200000.00", currency: "UZS", pay_type: "monthly", rounding_step: "1000.00" },
    job_change: null,
    bonus: null,
    outcome_state: null,
    published_at: null,
    published_by: null,
    acknowledged_at: null,
    earlier: [],
    can: { write: true, pay: true, reassign: true, remove: true, goals: false, draft_summary: false },
    ...overrides,
  };
}

function round(overrides: Partial<Round> = {}): Round {
  return {
    id: 7,
    name: "Chilonzor: 3-chorak, 2026",
    period_start: "2026-07-01",
    period_end: "2026-09-30",
    status: "self",
    self_due_on: "2026-11-20",
    manager_due_on: "2026-11-27",
    reviewers_begin_on: "2026-11-24",
    audience: { positions: [], branches: [] },
    questions: QUESTIONS,
    progress: { people: 8, self_sent: 5, published: 0, acknowledged: 0, late: 0, self_late: 0, manager_late: 0 },
    mine: 0,
    created_by: { id: 2, name: "Bekzod Mirzayev", photo_url: null },
    opened_at: "2026-11-10T05:00:00Z",
    manager_at: null,
    closed_at: null,
    created_at: "2026-11-09T10:00:00Z",
    can: { run: true, edit: true, open: false, advance: true, close: true, remind: true, delete: false },
    ...overrides,
  };
}

interface Call {
  method: string;
  url: string;
  body: unknown;
}

function stub(routes: Record<string, unknown>): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init?: RequestInit) => {
      const url = input.replace("/api/v1/owner/companies/1/", "");
      const method = init?.method ?? "GET";
      calls.push({ method, url, body: init?.body ? JSON.parse(String(init.body)) : undefined });
      const key = `${method} ${url.split("?")[0]}`;
      return json(key in routes ? routes[key] : {});
    }),
  );
  return calls;
}

beforeEach(async () => {
  // The clock reads Wednesday 11 November 2026 in Tashkent (only Date: timers stay real).
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-11-11T05:00:00Z"));
  mergeModuleMessages("lifecycle", { en, ru: en, uz: en });
});

const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

describe("review logic", () => {
  it("offers the last full quarter, month and half-year", () => {
    expect(lastQuarter("2026-11-11")).toEqual({ start: "2026-07-01", end: "2026-09-30" });
    expect(lastQuarter("2026-01-05")).toEqual({ start: "2025-10-01", end: "2025-12-31" });
    expect(lastMonth("2026-11-11")).toEqual({ start: "2026-10-01", end: "2026-10-31" });
    expect(lastHalf("2026-11-11")).toEqual({ start: "2026-01-01", end: "2026-06-30" });
    expect(lastHalf("2026-03-01")).toEqual({ start: "2025-07-01", end: "2025-12-31" });
  });

  it("checks a new round and sends only the audience it chose", () => {
    const form = blankRound("2026-11-11", "Q3 2026", QUESTIONS.map(({ kind, text, key }) => ({ kind, text, key })));
    expect(form.self_due_on).toBe("2026-11-18");
    expect(form.manager_due_on).toBe("2026-11-25");
    expect(roundErrors(form, "2026-11-11")).toEqual({});
    expect(roundErrors({ ...form, name: " ", questions: form.questions.slice(0, 2) }, "2026-11-11")).toEqual({ name: "name", questions: "questionCount" });
    expect(roundErrors({ ...form, audience: "some" }, "2026-11-11")).toEqual({ audience: "audience" });
    expect(roundErrors({ ...form, manager_due_on: "2026-11-15" }, "2026-11-11")).toEqual({ manager_due_on: "managerOrder" });
    expect(roundErrors({ ...form, self_due_on: "2026-11-01" }, "2026-11-11").self_due_on).toBe("past");
    const payload = roundPayload({ ...form, positions: [3], branches: [1] }, true);
    expect(payload).toMatchObject({ name: "Q3 2026", positions: [], branches: [], open: true });
    expect(roundPayload({ ...form, audience: "some", positions: [3] }, false)).toMatchObject({ positions: [3], branches: [], open: false });
  });

  it("keeps a template question's key only while its words are the template's", () => {
    const edited = editQuestion({ kind: "rating", text: "Dispensing and storage rules", key: "dispensing" }, "Retsept qoidalari", QUESTIONS);
    expect(edited.key).toBe("");
    expect(editQuestion(edited, "Dispensing and storage rules", QUESTIONS).key).toBe("dispensing");
    expect(moveItem([1, 2, 3], 0, 1)).toEqual([2, 1, 3]);
    expect(moveItem([1, 2, 3], 0, -1)).toEqual([1, 2, 3]);
  });

  it("counts the pay after a raise the way payroll rounds it", () => {
    expect(payAfter("5200000.00", "10", "1000.00")).toBe("5720000.00");
    expect(payAfter("4750000.00", "7.5", "1000.00")).toBe("5106000.00");
    expect(payAfter("4800000.00", "15", "0")).toBe("5520000.00");
    expect(payAfter("5200000.00", null, "1000")).toBeNull();
  });

  it("knows what still stops publishing", () => {
    const form = managerForm(review());
    expect(publishProblems(form, QUESTIONS, "2026-11-11")).toEqual(["ratings", "rating"]);
    form.answers = { q1: { rating: 4 }, q2: { rating: 5 } };
    expect(suggestedRating(form.answers, QUESTIONS)).toBe(5);
    expect(answeredCount(form.answers, QUESTIONS)).toBe(2);
    form.rating = 4;
    form.outcome = "raise";
    expect(publishProblems(form, QUESTIONS, "2026-11-11")).toEqual(["raise", "day"]);
    form.raise_percent = "10";
    form.effective_on = "2026-12-01";
    expect(publishProblems(form, QUESTIONS, "2026-11-11")).toEqual([]);
    expect(managerPayload(form)).toMatchObject({ outcome: "raise", raise_percent: "10", bonus_amount: null, effective_on: "2026-12-01" });
    form.outcome = "improvement_plan";
    form.goals = [{ title: "Jurnal", due_on: "2026-10-01", target: null, unit: "" }];
    expect(publishProblems(form, QUESTIONS, "2026-11-11")).toEqual(["goalDay"]);
    expect(managerPayload(form)).toMatchObject({ raise_percent: null, effective_on: null });
  });
});

describe("rating pills", () => {
  it("picks a rating with a click or the arrow keys, and stays put when read-only", async () => {
    const app = await testApp("/c/1/lifecycle/reviews/7/41");
    const values: Array<number | null> = [];
    const { wrapper } = mountWithProviders(RatingPills, { plugins: app.plugins, props: { modelValue: null, "onUpdate:modelValue": (value: number | null) => values.push(value) } });
    await wrapper.get('[data-value="4"]').trigger("click");
    expect(values).toEqual([4]);
    await wrapper.get("[data-rating]").trigger("keydown", { key: "ArrowRight" });
    expect(values.at(-1)).toBe(1);
    const read = mountWithProviders(RatingPills, { plugins: app.plugins, props: { modelValue: 3, readonly: true } }).wrapper;
    expect(read.text()).toContain(en["lifecycle.reviews.rating.word3"]);
  });
});

describe("the reviewer's page", () => {
  async function open(perms: Perm[] = ["reviews.manage", "payroll.propose", "payroll.view"]) {
    const app = await testApp("/c/1/lifecycle/reviews");
    app.router.addRoute({ path: "/c/:companyId/lifecycle/reviews/:roundId(\\d+)/:reviewId(\\d+)", component: { render: () => null } });
    await app.router.push("/c/1/lifecycle/reviews/7/41");
    useSessionStore().me = me([company({ is_owner: false, role: { id: 3, name: "Manager" }, permissions: perms })]);
    const { wrapper } = mountWithProviders(ReviewPage, { plugins: app.plugins });
    await flushPromises();
    return wrapper;
  }

  it("shows the person's own answers beside the reviewer's, and publishes once everything is rated", async () => {
    const saved = review({ manager_answers: { q1: { rating: 4 }, q2: { rating: 5 } }, rating: 4, manager_state: "draft" });
    const calls = stub({ "GET lifecycle/reviews/41/": review(), "PATCH lifecycle/reviews/41/": saved, "POST lifecycle/reviews/41/publish/": { ...saved, published_at: "2026-11-11T06:00:00Z" } });
    const wrapper = await open();
    expect(wrapper.get('[data-question="q1"] [data-their-answer]').text()).toContain("4");
    expect(wrapper.get('[data-question="q3"] [data-their-answer]').text()).toContain("Kassa to‘g‘ri chiqdi");
    expect(wrapper.get("[data-kpis]").text()).toContain("92.5%");
    expect(wrapper.get('[data-question="q1"] [data-my-answer]').text()).toContain(en["lifecycle.reviews.yourAnswer"]);
    expect(wrapper.get("[data-publish-needs]").text()).toContain(en["lifecycle.reviews.publishNeeds.ratings"]);

    await wrapper.get('[data-question="q1"] [data-my-answer] [data-value="4"]').trigger("click");
    await wrapper.get('[data-question="q2"] [data-my-answer] [data-value="5"]').trigger("click");
    await flushPromises();
    // The overall rating starts from the reviewer's own mean (4.5 rounds to 5) and the draft saves itself.
    await wait(800);
    await flushPromises();
    const patch = calls.find((call) => call.method === "PATCH");
    expect(patch?.body).toMatchObject({ answers: { q1: { rating: 4 }, q2: { rating: 5 } }, rating: 5, outcome: "none" });
    expect(wrapper.find("[data-publish-needs]").exists()).toBe(false);

    const publish = wrapper.findAll("button").find((button) => button.text() === en["lifecycle.reviews.publish"])!;
    await publish.trigger("click");
    await flushPromises();
    const [request] = confirmQueue.value;
    expect(request!.request.message).toBe(en["lifecycle.reviews.publishBody.none"]);
    settleConfirm(request!.id, { reason: "" }, 0);
    await flushPromises();
    await flushPromises();
    expect(calls.some((call) => call.method === "POST" && call.url === "lifecycle/reviews/41/publish/")).toBe(true);
  });

  it("keeps the person's answers hidden before the reviewers' part, and reads a review it doesn't write", async () => {
    const hidden = review({ round: { ...review().round, status: "self" }, self_part: { visible: false, state: "sent", sent_at: null, answers: null, average: null }, kpis: null, can: { write: false, pay: true, reassign: false, remove: false, goals: false, draft_summary: false } });
    stub({ "GET lifecycle/reviews/41/": hidden });
    const wrapper = await open();
    expect(wrapper.get('[data-question="q1"] [data-their-answer]').text()).toContain(en["lifecycle.reviews.hiddenShort"]);
    expect(wrapper.text()).toContain(en["lifecycle.reviews.kpis.later"]);
    // Someone else's review: the reviewer's side is "the reviewer's", not "yours".
    expect(wrapper.get('[data-question="q1"] [data-my-answer]').text()).toContain(en["lifecycle.reviews.reviewerAnswer"]);
    expect(wrapper.findAll("button").some((button) => button.text() === en["lifecycle.reviews.publish"])).toBe(false);
  });

  it("drafts the summary with AI once something is rated, asking before it replaces the reviewer's words", async () => {
    const rated = review({ manager_answers: { q1: { rating: 5, text: "" } }, summary: "Mening fikrim", manager_state: "draft", can: { ...review().can, draft_summary: true } });
    const draft = "Siz kassani doim to‘g‘ri yuritdingiz. Keyingi chorakda o‘qishga e’tibor bering.";
    const calls = stub({ "GET lifecycle/reviews/41/": rated, "PATCH lifecycle/reviews/41/": rated, "POST lifecycle/reviews/41/draft-summary/": { summary: draft, engine: "claude" } });
    const wrapper = await open();
    const button = wrapper.get("[data-draft-summary]");
    expect(button.text()).toBe(en["lifecycle.reviews.draftSummary"]);

    await button.trigger("click");
    await flushPromises();
    const [request] = confirmQueue.value;
    expect(request!.request.title).toBe(en["lifecycle.reviews.draftReplaceTitle"]);
    settleConfirm(request!.id, { reason: "" }, 0);
    await flushPromises();
    await flushPromises();
    expect(calls.some((call) => call.method === "POST" && call.url === "lifecycle/reviews/41/draft-summary/")).toBe(true);
    expect((wrapper.get("#review-summary").element as HTMLTextAreaElement).value).toBe(draft);
    expect(wrapper.get("[data-drafted]").text()).toBe(en["lifecycle.reviews.draftedHint"]);
    // It saves as the reviewer's own draft: nothing more.
    await wait(800);
    await flushPromises();
    expect(calls.filter((call) => call.method === "PATCH").at(-1)?.body).toMatchObject({ summary: draft });
  });

  it("offers no AI draft while the company's AI is off", async () => {
    stub({ "GET lifecycle/reviews/41/": review() });
    const wrapper = await open();
    expect(wrapper.find("[data-draft-summary]").exists()).toBe(false);
  });
});

describe("the outcome", () => {
  it("shows the pay now and after a raise, and locks pay outcomes for people who may not propose pay", async () => {
    const app = await testApp("/c/1/lifecycle/reviews/7/41");
    const form = { ...managerForm(review()), outcome: "raise" as const, raise_percent: "10", effective_on: "2026-12-01" };
    const { wrapper } = mountWithProviders(OutcomeEditor, { plugins: app.plugins, props: { modelValue: form, review: review(), today: "2026-11-11" } });
    await flushPromises();
    expect(wrapper.get("[data-pay-after]").text()).toMatch(/5[\s,.]?720[\s,.]?000/);
    const locked = mountWithProviders(OutcomeEditor, { plugins: app.plugins, props: { modelValue: managerForm(review()), review: review({ can: { ...review().can, pay: false } }), today: "2026-11-11" } }).wrapper;
    await flushPromises();
    expect(locked.text()).toContain(en["lifecycle.reviews.outcomePayLocked"]);
  });
});

describe("the reviews page and the new round", () => {
  it("explains the three steps on a first visit and lists rounds by stage after", async () => {
    stub({ "GET lifecycle/review-rounds/": [] });
    const app = await testApp("/c/1/lifecycle/reviews");
    useSessionStore().me = me([company({ permissions: ["reviews.manage"] })]);
    const empty = mountWithProviders(ReviewsPage, { plugins: app.plugins }).wrapper;
    await flushPromises();
    expect(empty.get("[data-reviews-empty]").text()).toContain(en["lifecycle.reviews.empty.oneTitle"]);

    stub({ "GET lifecycle/review-rounds/": [round({ mine: 2, status: "manager" }), round({ id: 8, status: "closed", closed_at: "2026-10-24T13:00:00Z" })] });
    const listed = mountWithProviders(ReviewsPage, { plugins: (await testApp("/c/1/lifecycle/reviews")).plugins }).wrapper;
    await flushPromises();
    expect(listed.find('[data-section="open"] [data-round="7"]').exists()).toBe(true);
    expect(listed.find('[data-section="closed"] [data-round="8"]').exists()).toBe(true);
    expect(listed.get("[data-waiting]").text()).toContain("2 reviews wait for you");
  });

  it("walks the wizard step by step and opens the round with the template's questions", async () => {
    const template = QUESTIONS.map((question, index) => ({ ...question, id: `q${index + 1}` }));
    const calls = stub({
      "GET lifecycle/review-rounds/template/": template,
      "GET lifecycle/review-rounds/preview/": { count: 2, reviewers: [{ reviewer: { id: 2, name: "Bekzod Mirzayev" }, people: 2 }], people: [] },
      "POST lifecycle/review-rounds/": round({ progress: { ...round().progress, people: 2 } }),
    });
    const app = await testApp("/c/1/lifecycle/reviews");
    const { wrapper } = mountWithProviders(RoundWizard, { plugins: app.plugins, props: { open: true } });
    await flushPromises();
    const dialog = () => document.body.querySelector("[data-round-wizard]")!;
    expect(dialog().querySelector('[data-step="basics"]')).not.toBeNull();
    const next = () => [...document.body.querySelectorAll("button")].find((button) => button.textContent?.trim() === en["lifecycle.reviews.wizard.next"]) as HTMLButtonElement;
    next().click();
    await flushPromises();
    expect(dialog().querySelector('[data-step="people"]')?.textContent).toContain("Bekzod Mirzayev");
    next().click();
    await flushPromises();
    expect(dialog().querySelectorAll("[data-questions] li")).toHaveLength(3);
    next().click();
    await flushPromises();
    const openNow = [...document.body.querySelectorAll("button")].find((button) => button.textContent?.trim() === en["lifecycle.reviews.wizard.openNow"]) as HTMLButtonElement;
    openNow.click();
    await flushPromises();
    const post = calls.find((call) => call.method === "POST" && call.url === "lifecycle/review-rounds/");
    expect(post?.body).toMatchObject({ name: "Q3 2026", period_start: "2026-07-01", period_end: "2026-09-30", open: true, positions: [], branches: [] });
    expect((post?.body as { questions: unknown[] }).questions).toHaveLength(3);
    wrapper.unmount();
  });
});
