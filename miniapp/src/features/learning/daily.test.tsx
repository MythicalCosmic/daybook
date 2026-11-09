/**
 * The question of the day (docs/PLAN-LEARNING.md §4.8, §12.1) answered right on Home: the result
 * with the explanation, points and the streak, confetti only when right; one tap for true or
 * false; a quiet line once answered; its own page (`daily`). And Home's check card while a round
 * is open, with how many questions and by when.
 */
import { act, cleanup, fireEvent, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { membership, navigationState, NOW, person, renderApp } from "../../test/harness";
import DailyPage from "./Daily";
import { checkEntry, daily, QUESTIONS, quizDetail } from "./fixtures";
import { CheckCard, DailyCard, openChecks } from "./slots";
import type { DailyResult, DailyView } from "./types";

const server = vi.hoisted(() => ({
  calls: [] as { path: string; method: string; body: unknown }[],
  handler: (() => undefined) as (path: string, method: string, body: unknown) => unknown,
}));
vi.mock("../../api/client", async (importOriginal) => {
  const real = await importOriginal<typeof import("../../api/client")>();
  return {
    ...real,
    api: vi.fn(async (path: string, options: { method?: string; json?: unknown } = {}) => {
      const method = options.method ?? (options.json ? "POST" : "GET");
      server.calls.push({ path, method, body: options.json });
      const result = await server.handler(path, method, options.json);
      if (result instanceof Error) throw result;
      return result ?? {};
    }),
  };
});
const celebrate = vi.hoisted(() => vi.fn(() => () => undefined));
vi.mock("../../ui/celebrate", () => ({ celebrate, prefersReducedMotion: () => false }));

const company = { id: 1, name: "Demo Dorixona", timezone: "Asia/Tashkent", features: ["learning"] };
const alisher = membership({ company } as never);
const me = person([alisher]);
const member = { ...alisher, timeZone: "Asia/Tashkent", companyId: 1 };

const RIGHT: DailyResult = { correct: true, share: 1, right_answer: { option: "a" }, explanation: "Insulin 2–8 °C da saqlanadi.", points: 5, streak: 4 };
const WRONG: DailyResult = { correct: false, share: 0, right_answer: { option: "a" }, explanation: "Insulin 2–8 °C da saqlanadi.", points: 1, streak: 1 };

function serve(view: DailyView, reply: DailyResult = RIGHT) {
  server.handler = (path, method) => {
    if (path.endsWith("/learning/daily/")) return view;
    if (path.endsWith("/learning/daily/501/answer/") && method === "POST") return reply;
    if (path.endsWith("/learning/checks/")) return [checkEntry(), checkEntry({ entry_id: 50, done: true, passed: true }), checkEntry({ entry_id: 49, due_at: "2026-10-20T05:00:00Z" })];
    if (path.includes("/learning/quizzes/9/")) return quizDetail({ id: 9, questions: 5 });
    return {};
  };
}

const answers = () => server.calls.filter((call) => call.path.endsWith("/answer/"));

beforeEach(() => {
  server.calls = [];
  celebrate.mockClear();
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("the question of the day on Home", () => {
  it("is answered in place, and a right answer gets confetti, the points and the streak", async () => {
    serve({ daily: daily(), streak: 3 });
    renderApp(<DailyCard member={member} summary={undefined} />, { me });
    expect(await screen.findByText("Question of the day")).toBeTruthy();
    expect(screen.getByText("3 days in a row")).toBeTruthy();
    expect(screen.getByText("Insulin qaysi haroratda saqlanadi?")).toBeTruthy();
    const send = screen.getByRole("button", { name: "Answer" });
    expect(send.hasAttribute("disabled")).toBe(true);
    fireEvent.click(screen.getByRole("radio", { name: /2–8 °C/ }));
    fireEvent.click(send);
    expect(await screen.findByText("Right!")).toBeTruthy();
    expect(answers()).toEqual([{ path: "/companies/1/learning/daily/501/answer/", method: "POST", body: { answer: { option: "a" } } }]);
    expect(screen.getByText("+5 points")).toBeTruthy();
    expect(screen.getByText("Insulin 2–8 °C da saqlanadi.")).toBeTruthy();
    expect(screen.getByText("4 days in a row", { selector: ".lrn-streak" })).toBeTruthy();
    expect(celebrate).toHaveBeenCalledTimes(1);
    // The right answer isn't repeated when it was the person's own.
    expect(screen.queryByText("Right answer")).toBeNull();
  });

  it("shows the right answer after a wrong one, without confetti", async () => {
    serve({ daily: daily(), streak: 3 }, WRONG);
    renderApp(<DailyCard member={member} summary={undefined} />, { me });
    fireEvent.click(await screen.findByRole("radio", { name: /15–25 °C/ }));
    fireEvent.click(screen.getByRole("button", { name: "Answer" }));
    expect(await screen.findByText("Not quite")).toBeTruthy();
    const right = screen.getByText("Right answer").closest(".lrn-review-line");
    expect(right?.textContent).toBe("Right answer2–8 °C");
    expect(screen.getByText("Your answer").closest(".lrn-review-line")?.textContent).toBe("Your answer15–25 °C");
    expect(screen.getByText("+1 point")).toBeTruthy();
    expect(celebrate).not.toHaveBeenCalled();
  });

  it("answers true or false with one tap", async () => {
    serve({ daily: daily({ question: QUESTIONS[2] }), streak: null });
    renderApp(<DailyCard member={member} summary={undefined} />, { me });
    fireEvent.click(await screen.findByRole("radio", { name: "False" }));
    expect(await screen.findByText("Right!")).toBeTruthy();
    expect(answers()[0].body).toEqual({ answer: { value: false } });
    expect(screen.queryByRole("button", { name: "Answer" })).toBeNull();
  });

  it("folds into one line once answered, which opens the question's page", async () => {
    serve({ daily: daily({ answered: true, correct: true, answer: { option: "a" }, right_answer: { option: "a" }, explanation: "Insulin 2–8 °C da saqlanadi." }), streak: 4 });
    renderApp(<DailyCard member={member} summary={undefined} />, { me });
    const line = await screen.findByRole("button", { name: /You got today’s question right/ });
    expect(line.textContent).toContain("4 days in a row");
    fireEvent.click(line);
    expect(navigationState().stack.at(-1)).toEqual({ feature: "learning", page: "daily", params: undefined });
  });

  it("shows nothing on a day without a question", async () => {
    serve({ daily: null, streak: 2 });
    renderApp(<DailyCard member={member} summary={undefined} />, { me });
    await act(async () => {});
    await act(async () => {});
    expect(document.querySelector(".lrn-daily")).toBeNull();
    expect(screen.queryByText("Question of the day")).toBeNull();
  });
});

describe("the question of the day's page", () => {
  it("takes an order question as shown or reordered", async () => {
    serve({ daily: daily({ question: QUESTIONS[3] }), streak: null });
    renderApp(<DailyPage params={{}} />, { me });
    const send = await screen.findByRole("button", { name: "Answer" });
    // The shown order is an answer too: the button is ready at once.
    expect(send.hasAttribute("disabled")).toBe(false);
    fireEvent.click(screen.getAllByRole("button", { name: "Move up" })[2]);
    fireEvent.click(send);
    expect(await screen.findByText("Right!")).toBeTruthy();
    expect(answers()[0].body).toEqual({ answer: { order: ["c", "b", "a"] } });
  });

  it("says kindly when there is none today", async () => {
    serve({ daily: null, streak: null });
    renderApp(<DailyPage params={{}} />, { me });
    expect(await screen.findByText("No question today")).toBeTruthy();
    expect(screen.getByText("A new one comes on your next workday.")).toBeTruthy();
  });
});

describe("Home's check card", () => {
  it("shows the open round with its questions and deadline, and starts it", async () => {
    serve({ daily: null, streak: null });
    renderApp(<CheckCard member={member} summary={undefined} />, { me });
    expect(await screen.findByText("5 questions, by tomorrow, 10:00")).toBeTruthy();
    expect(screen.getByText("Regular check")).toBeTruthy();
    expect(screen.getAllByText("Dushanba tekshiruvi")).toHaveLength(1);
    expect(server.calls.some((call) => call.path === "/companies/1/learning/quizzes/9/?entry=61")).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Start" }));
    expect(navigationState().stack.at(-1)).toEqual({ feature: "learning", page: "check", params: { id: 61 } });
  });

  it("leaves out rounds answered or past their deadline", () => {
    const entries = [checkEntry({ entry_id: 1, done: true }), checkEntry({ entry_id: 2, due_at: "2026-10-20T05:00:00Z" }), checkEntry({ entry_id: 3, due_at: "2026-10-23T05:00:00Z" }), checkEntry({ entry_id: 4 })];
    expect(openChecks(entries, NOW).map((entry) => entry.entry_id)).toEqual([4, 3]);
  });
});
