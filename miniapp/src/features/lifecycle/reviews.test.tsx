/**
 * "Baholashlarim": the questions one screen at a time with my draft kept as I go, the last look
 * and Send after a confirm, the sent state, the published review (rating, what follows, my goals)
 * with "I've read it", My reviews, Home's card, Me's bubble, the bot's link, and the logic.
 */
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { resolveScreen } from "../../state/deeplink";
import { membership, person, renderApp, routeApi } from "../../test/harness";
import { features, findFeature } from "../registry";
import { ReviewCard } from "./reviewSlots";
import ReviewPage from "./ReviewPage";
import { answered, cleanAnswers, noBreak, resumeStep, unrated, waitingCount, type MyReview, type MyReviews, type ReviewQuestion } from "./reviews";
import ReviewsPage from "./ReviewsPage";

const client = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("../../api/client", async (importOriginal) => {
  const real = await importOriginal<typeof import("../../api/client")>();
  return { ...real, api: client.api };
});

const lifecycle = findFeature(features, "lifecycle")!;
const company = { id: 1, name: "Demo Dorixona", timezone: "Asia/Tashkent", features: ["hr", "payroll"], base_currency: "UZS" };
const me = person([membership({ company } as never)]);
const member = { ...me.memberships[0], timeZone: "Asia/Tashkent", companyId: 1 };

const QUESTIONS: ReviewQuestion[] = [
  { id: "q1", kind: "rating", text: "Dispensing and storage rules", key: "dispensing" },
  { id: "q2", kind: "rating", text: "Customer care", key: "customers" },
  { id: "q3", kind: "text", text: "What went best in this period?", key: "best" },
];

function review(extra: Partial<MyReview> = {}): MyReview {
  return {
    id: 7,
    round: { id: 3, name: "Yunusobod: 3-chorak, 2026", status: "self", period_start: "2026-07-01", period_end: "2026-09-30", self_due_on: "2026-11-13" },
    state: "todo",
    can_answer: true,
    self_sent_at: null,
    published_at: null,
    acknowledged_at: null,
    rating: null,
    outcome: null,
    late: false,
    questions: QUESTIONS,
    answers: {},
    self_saved_at: null,
    reviewer: "Farrux Aliyev",
    manager_answers: null,
    summary: null,
    raise_percent: null,
    bonus: null,
    change: null,
    goals: [],
    kpis: null,
    ...extra,
  };
}

function list(extra: Partial<MyReviews> = {}): MyReviews {
  const { questions: _q, answers: _a, self_saved_at: _s, reviewer: _r, manager_answers: _m, summary: _y, raise_percent: _p, bonus: _b, change: _c, goals: _g, kpis: _k, ...row } = review();
  return { open: [row], past: [], goals: [], ...extra };
}

afterEach(() => {
  cleanup();
  client.api.mockReset();
  vi.restoreAllMocks();
});

describe("the answering logic", () => {
  it("knows what is answered, what still needs a rating and where to carry on", () => {
    const answers = { q1: { rating: 4, text: "  " }, q3: { rating: null, text: "Kassa" } };
    expect(unrated(QUESTIONS, answers)).toEqual(["q2"]);
    expect(answered(QUESTIONS, answers)).toBe(2);
    expect(resumeStep(QUESTIONS, answers)).toBe(1);
    expect(cleanAnswers({ ...answers, q2: { rating: null, text: " " } })).toEqual({ q1: { rating: 4, text: "" }, q3: { rating: null, text: "Kassa" } });
    expect(waitingCount(list({ past: [{ ...list().open[0]!, id: 9, state: "published", can_answer: false, acknowledged_at: null }] }))).toBe(2);
  });
});

describe("answering my review", () => {
  it("goes one question a screen, keeps my draft, and sends after a last look and a confirm", async () => {
    const drafts: unknown[] = [];
    const sent: unknown[] = [];
    routeApi(client.api, {
      "/lifecycle/reviews/7/": review(),
      "PATCH /lifecycle/reviews/7/": (body: unknown) => (drafts.push(body), review({ state: "draft" })),
      "POST /lifecycle/reviews/7/send/": (body: unknown) => (sent.push(body), review({ state: "sent", can_answer: false, self_sent_at: new Date().toISOString(), answers: body as MyReview["answers"] })),
    });
    const asked = vi.spyOn(window, "confirm").mockReturnValue(true);
    renderApp(<ReviewPage params={{ id: 7 }} />, { me });
    expect(await screen.findByText("A few questions about your work")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Start" }));

    expect(screen.getByText("Dispensing and storage rules")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Next" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("radio", { name: /4\s*Very good/ }));
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await waitFor(() => expect(drafts).toEqual([{ answers: { q1: { rating: 4, text: "" } } }]));

    fireEvent.click(screen.getByRole("radio", { name: /5\s*Excellent/ }));
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    fireEvent.change(screen.getByPlaceholderText("In your own words"), { target: { value: "Kassa doim to‘g‘ri chiqdi" } });
    fireEvent.click(screen.getByRole("button", { name: "Check my answers" }));
    expect(screen.getByText("Your answers")).toBeTruthy();
    expect(screen.getByText("5 · Excellent")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(sent).toHaveLength(1));
    expect(asked).toHaveBeenCalledWith("Send your answers? They can't change after that.");
    expect(sent[0]).toEqual({ answers: { q1: { rating: 4, text: "" }, q2: { rating: 5, text: "" }, q3: { rating: null, text: "Kassa doim to‘g‘ri chiqdi" } } });
    expect(await screen.findByText("Sent, thank you")).toBeTruthy();
  });

  it("carries on a draft where it stopped", async () => {
    routeApi(client.api, { "/lifecycle/reviews/7/": review({ state: "draft", answers: { q1: { rating: 3, text: "" } } }) });
    renderApp(<ReviewPage params={{ id: 7 }} />, { me });
    expect(await screen.findByText("Customer care")).toBeTruthy();
    expect(screen.getByText("Question 2 of 3")).toBeTruthy();
  });

  it("shows a sent review as waiting for my manager", async () => {
    routeApi(client.api, { "/lifecycle/reviews/7/": review({ state: "sent", can_answer: false, self_sent_at: "2026-11-09T21:40:00+05:00", answers: { q1: { rating: 4, text: "" } } }) });
    renderApp(<ReviewPage params={{ id: 7 }} />, { me });
    expect(await screen.findByText("Sent: your manager answers next")).toBeTruthy();
    expect(screen.getByText("4 · Very good")).toBeTruthy();
  });
});

describe("my published review", () => {
  it("shows the rating, what follows with its approval, my goals, and lets me say I read it", async () => {
    let read = 0;
    const published = review({
      state: "published",
      can_answer: false,
      self_sent_at: "2026-10-08T21:10:00+05:00",
      published_at: "2026-10-16T15:05:00+05:00",
      rating: 5,
      outcome: "raise",
      answers: { q1: { rating: 4, text: "" }, q2: { rating: 5, text: "" } },
      manager_answers: { q1: { rating: 5, text: "Muddati tugayotgan dorilar o‘z vaqtida qaytarildi." }, q2: { rating: 5, text: "" } },
      summary: "Kechki smenaning tayanchi.",
      raise_percent: "10.00",
      change: { status: "waiting", effective_on: "2026-12-01", position: null, pay_before: "5600000.00", pay_after: "6160000.00", currency: "UZS" },
      goals: [{ id: 1, title: "GDP kursini tugatish", target: null, unit: "", progress: null, due_on: "2026-12-31", status: "open", note: "", closed_at: null }],
    });
    routeApi(client.api, {
      "/lifecycle/reviews/7/": published,
      "POST /lifecycle/reviews/7/acknowledge/": () => ((read += 1), { ...published, acknowledged_at: "2026-11-11T10:00:00+05:00" }),
    });
    renderApp(<ReviewPage params={{ id: 7 }} />, { me });
    expect(await screen.findByText("Excellent")).toBeTruthy();
    expect(screen.getByText("Kechki smenaning tayanchi.")).toBeTruthy();
    expect(screen.getByText("A raise")).toBeTruthy();
    expect(screen.getByText("Waiting for approval")).toBeTruthy();
    expect(screen.getByText(/Your pay becomes 6[\s,.]?160[\s,.]?000/)).toBeTruthy();
    expect(screen.getByText("GDP kursini tugatish")).toBeTruthy();
    expect(screen.getByText("Muddati tugayotgan dorilar o‘z vaqtida qaytarildi.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "I’ve read it" }));
    await waitFor(() => expect(read).toBe(1));
  });
});

describe("my reviews, Home and Me", () => {
  it("lists the round to answer, the published ones and my goals", async () => {
    routeApi(client.api, {
      "/lifecycle/reviews/": list({
        past: [{ ...list().open[0]!, id: 9, round: { ...list().open[0]!.round, name: "Chilonzor: 2-chorak, 2026" }, state: "published", can_answer: false, rating: 4, outcome: "bonus", acknowledged_at: null }],
        goals: [{ id: 1, title: "GDP kursini tugatish", target: null, unit: "", progress: null, due_on: "2026-12-31", status: "open", note: "", closed_at: null, round: "Chilonzor: 2-chorak, 2026", review_id: 9 }],
      }),
    });
    renderApp(<ReviewsPage />, { me });
    expect(await screen.findByText(noBreak("Yunusobod: 3-chorak, 2026"))).toBeTruthy();
    expect(screen.getByText("Chilonzor: 2-chorak, 2026")).toBeTruthy();
    expect(screen.getByText("4 of 5 · A bonus")).toBeTruthy();
    expect(screen.getByText("New")).toBeTruthy();
    expect(screen.getByText("GDP kursini tugatish")).toBeTruthy();
  });

  it("puts a card on Home while a round waits for me, a bubble on Me, and answers the bot's link", async () => {
    routeApi(client.api, { "/lifecycle/reviews/": list() });
    renderApp(<ReviewCard member={member as never} summary={undefined} />, { me });
    expect(await screen.findByText("Your performance review")).toBeTruthy();
    expect(lifecycle.meItems?.map((item) => item.id)).toContain("reviews");
    expect(resolveScreen({ name: "lifecycle.review", arg: "7" }, features)).toEqual({ tab: "profile", stack: [{ feature: "lifecycle", page: "review", params: { id: 7 } }] });
    expect(resolveScreen({ name: "lifecycle.reviews", arg: null }, features)).toEqual({ tab: "profile", stack: [{ feature: "lifecycle", page: "reviews", params: {} }] });
  });
});
