/**
 * Quizzes in the mini app (docs/PLAN-LEARNING.md §4.3, §4.7, §12.1): the intro and why a quiz
 * can't start, the player for every kind of question with each answer saved as given (the exact
 * §4.3 shapes), Back and Next, Finish with a confirm that counts what has no answer, the time
 * limit finishing by itself, the result with the score ring, points, the review and retry, and a
 * regular check's entry opening its quiz.
 */
import { act, cleanup, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../../api/client";
import { membership, navigationState, NOW, person, renderApp } from "../../test/harness";
import AttemptPage from "./AttemptPage";
import { learningKeys } from "./api";
import CheckPage from "./CheckPage";
import { attemptPlay, attemptResult, checkEntry, quizDetail } from "./fixtures";
import QuizPage from "./QuizPage";
import { resetQueue } from "./queue";
import type { AttemptPlay, AttemptResult, QuizDetail } from "./types";

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
const me = person([membership({ company } as never)]);

type Handler = (path: string, method: string, body: unknown) => unknown;
function serve(extra: Handler = () => undefined) {
  server.handler = (path, method, body) => {
    const own = extra(path, method, body);
    if (own !== undefined) return own;
    if (path.includes("/learning/quizzes/8/attempts/") && method === "POST") return attemptPlay({ id: 78 });
    if (path.includes("/learning/quizzes/8/")) return quizDetail();
    if (path.includes("/learning/quizzes/9/attempts/") && method === "POST") return attemptPlay({ id: 79, quiz: { id: 9, title: "Dushanba tekshiruvi", emoji: "", pass_percent: 80 } });
    if (path.includes("/learning/quizzes/9/")) return quizDetail({ id: 9, title: "Dushanba tekshiruvi", questions: 5, max_attempts: 1, attempts_used: 0, best: null });
    if (path.endsWith("/learning/attempts/77/finish/")) return attemptResult();
    if (path.endsWith("/learning/checks/")) return [checkEntry()];
    if (method === "PUT") return undefined;
    return {};
  };
}

/** The saved answers, in order: `[question, answer]`. */
const saves = () => server.calls.filter((call) => call.method === "PUT").map((call) => call.body as { question: number; answer: unknown });
const lastSave = (question: number) => saves().filter((save) => save.question === question).at(-1)?.answer;
const flush = () => act(async () => {});

function play(attempt: AttemptPlay = attemptPlay(), params: Record<string, number> = { id: attempt.id, quiz: 8, course: 4, assignment: 31 }) {
  return renderApp(<AttemptPage params={params} />, {
    me,
    init: { stack: [{ feature: "learning", page: "attempt", params }] },
    seed: (client) => client.setQueryData(learningKeys.attempt(1, attempt.id), attempt),
  });
}

function result(view: AttemptResult = attemptResult(), params: Record<string, number> = { id: view.id, quiz: 8, course: 4, assignment: 31 }) {
  return renderApp(<AttemptPage params={params} />, {
    me,
    init: { stack: [{ feature: "learning", page: "attempt", params }] },
    seed: (client) => client.setQueryData(learningKeys.attempt(1, view.id), view),
  });
}

const next = () => fireEvent.click(screen.getByRole("button", { name: "Next" }));

beforeEach(() => {
  resetQueue();
  localStorage.clear();
  server.calls = [];
  serve();
  celebrate.mockClear();
  vi.spyOn(window, "confirm").mockReturnValue(true);
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("the quiz intro", () => {
  const intro = (detail?: QuizDetail) => {
    if (detail) serve((path) => (path.includes("/learning/quizzes/8/") && !path.includes("attempts") ? detail : undefined));
    return renderApp(<QuizPage params={{ id: 8, assignment: 31, course: 4 }} />, { me, init: { stack: [{ feature: "learning", page: "quiz", params: { id: 8, assignment: 31, course: 4 } }] } });
  };
  const fact = (label: string) => screen.getByText(label).closest(".lrn-fact")?.querySelector(".lrn-fact-value")?.textContent;

  it("says what the test is and starts it for the course", async () => {
    intro();
    expect(await screen.findByRole("heading", { name: "Sovuq zanjir testi" })).toBeTruthy();
    expect(server.calls[0].path).toBe("/companies/1/learning/quizzes/8/?assignment=31");
    expect(fact("Questions")).toBe("7");
    expect(fact("Time")).toBe("10 min");
    expect(fact("Pass mark")).toBe("70%");
    expect(fact("Attempts left")).toBe("2 of 3");
    expect(fact("Your best")).toBe("60%");
    fireEvent.click(screen.getByRole("button", { name: "Start the test" }));
    await flush();
    expect(server.calls.find((call) => call.method === "POST")).toEqual({ path: "/companies/1/learning/quizzes/8/attempts/", method: "POST", body: { assignment: 31 } });
    // In place of the intro: Back from the test goes to the course.
    expect(navigationState().stack).toEqual([{ feature: "learning", page: "attempt", params: { id: 78, quiz: 8, assignment: 31, course: 4 } }]);
  });

  it("resumes the attempt in progress", async () => {
    intro(quizDetail({ in_progress: 77 }));
    fireEvent.click(await screen.findByRole("button", { name: "Continue the test" }));
    expect(navigationState().stack).toEqual([{ feature: "learning", page: "attempt", params: { id: 77, quiz: 8, assignment: 31, course: 4 } }]);
  });

  it("says when the next try is, or that the attempts are used up", async () => {
    intro(quizDetail({ can_start: false, retry_at: "2026-10-21T09:30:00Z", reason: "cooldown" }));
    expect(await screen.findByText("Next try: today, 14:30")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Start the test" })).toBeNull();
    cleanup();
    intro(quizDetail({ can_start: false, attempts_used: 3, reason: "attempts" }));
    expect(await screen.findByText("You’ve used every attempt")).toBeTruthy();
    cleanup();
    intro(quizDetail({ can_start: false, max_attempts: null, reason: "Bu test faqat farmatsevtlar uchun." }));
    expect(await screen.findByText("Bu test faqat farmatsevtlar uchun.")).toBeTruthy();
    cleanup();
    intro(quizDetail({ can_start: false, max_attempts: null, reason: "not_in_audience" }));
    expect(await screen.findByText("This test isn’t open to you right now")).toBeTruthy();
  });
});

describe("the player", () => {
  it("asks one question per screen and saves every kind as it is answered", async () => {
    play();
    expect(screen.getByRole("heading", { name: "Question 1 of 7" })).toBeTruthy();

    // single: radio cards
    fireEvent.click(screen.getByRole("radio", { name: /2–8 °C/ }));
    await flush();
    expect(lastSave(1)).toEqual({ option: "a" });
    expect(screen.getByRole("radio", { name: /2–8 °C/ }).getAttribute("aria-checked")).toBe("true");
    next();

    // multi: checkbox cards, kept in the order shown
    expect(screen.getByRole("heading", { name: "Question 2 of 7" })).toBeTruthy();
    fireEvent.click(screen.getByRole("checkbox", { name: /Vaksinalar/ }));
    fireEvent.click(screen.getByRole("checkbox", { name: /Insulin/ }));
    await flush();
    expect(lastSave(2)).toEqual({ options: ["a", "c"] });
    next();

    // true/false: two big buttons
    fireEvent.click(screen.getByRole("radio", { name: "False" }));
    await flush();
    expect(lastSave(3)).toEqual({ value: false });
    next();

    // order: up and down
    const rows = () => [...document.querySelectorAll(".lrn-order-text")].map((node) => node.textContent);
    expect(rows()).toEqual(["Hujjatga kiritish", "Nakladnoyni tekshirish", "Seriya va muddatni ko‘rish"]);
    fireEvent.click(screen.getAllByRole("button", { name: "Move up" })[1]);
    fireEvent.click(screen.getAllByRole("button", { name: "Move down" })[1]);
    await flush();
    expect(rows()).toEqual(["Nakladnoyni tekshirish", "Seriya va muddatni ko‘rish", "Hujjatga kiritish"]);
    expect(lastSave(4)).toEqual({ order: ["a", "b", "c"] });
    next();

    // match: the first open left is picked; a tap on a right pairs them, in the same colour
    const cell = (text: string) => screen.getByText(text, { selector: ".lrn-match-text" }).closest("button")!;
    fireEvent.click(cell("2–8 °C"));
    await flush();
    expect(lastSave(5)).toEqual({ pairs: { l1: "r1" } });
    fireEvent.click(cell("15–25 °C"));
    await flush();
    expect(lastSave(5)).toEqual({ pairs: { l1: "r1", l2: "r2" } });
    expect(cell("Insulin").className).toContain("lrn-pair--0");
    expect(cell("2–8 °C").className).toContain("lrn-pair--0");
    expect(cell("Sirop").className).toContain("lrn-pair--1");
    // A tap on a matched right with nothing picked undoes that pair.
    fireEvent.click(cell("15–25 °C"));
    await flush();
    expect(lastSave(5)).toEqual({ pairs: { l1: "r1" } });
    fireEvent.click(cell("15–25 °C"));
    await flush();
    next();

    // text: saved on leaving the box (and a moment after the last key)
    const text = screen.getByRole("textbox", { name: "Type the answer" });
    fireEvent.change(text, { target: { value: "2-8" } });
    fireEvent.blur(text);
    await flush();
    expect(lastSave(6)).toEqual({ text: "2-8" });
    next();

    // number: a comma decimal, with the unit beside the box
    expect(screen.getByText("ml")).toBeTruthy();
    const box = screen.getByRole("textbox", { name: "Enter a number" });
    expect(box.getAttribute("inputmode")).toBe("decimal");
    fireEvent.change(box, { target: { value: "4,5" } });
    fireEvent.blur(box);
    await flush();
    expect(lastSave(7)).toEqual({ value: 4.5 });
    expect(screen.getByText("2 points")).toBeTruthy();

    // Every one answered: the strip says so, and Finish asks once more.
    expect(document.querySelectorAll(".lrn-strip-seg--done")).toHaveLength(7);
    fireEvent.click(screen.getByRole("button", { name: "Finish" }));
    await flush();
    expect(window.confirm).toHaveBeenCalledWith("Finish the test? The answers can’t be changed after.");
    await flush();
    expect(server.calls.some((call) => call.path === "/companies/1/learning/attempts/77/finish/" && call.method === "POST")).toBe(true);
    expect(await screen.findByRole("heading", { name: "Passed!" })).toBeTruthy();
    expect(celebrate).toHaveBeenCalledTimes(1);
  });

  it("goes back and forth, and resumes at the first unanswered question", async () => {
    play(attemptPlay({ answers: { "1": { option: "a" }, "2": { options: ["c"] } } }));
    expect(screen.getByRole("heading", { name: "Question 3 of 7" })).toBeTruthy();
    expect(document.querySelectorAll(".lrn-strip-seg--done")).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: "Previous" }));
    expect(screen.getByRole("heading", { name: "Question 2 of 7" })).toBeTruthy();
    expect(screen.getByRole("checkbox", { name: /Vaksinalar/ }).getAttribute("aria-checked")).toBe("true");
    fireEvent.click(screen.getByRole("button", { name: "Question 7" }));
    expect(screen.getByRole("heading", { name: "Question 7 of 7" })).toBeTruthy();
  });

  it("answers an order question left as shown with that order", async () => {
    play(attemptPlay({ answers: { "1": { option: "a" }, "2": { options: ["c"] }, "3": { value: true } } }));
    expect(screen.getByRole("heading", { name: "Question 4 of 7" })).toBeTruthy();
    next();
    await flush();
    expect(lastSave(4)).toEqual({ order: ["c", "a", "b"] });
  });

  it("takes an answer back when its box is emptied", async () => {
    play(attemptPlay({ answers: { "6": { text: "2-8" } } }));
    fireEvent.click(screen.getByRole("button", { name: "Question 6" }));
    const text = screen.getByRole("textbox", { name: "Type the answer" }) as HTMLInputElement;
    expect(text.value).toBe("2-8");
    fireEvent.change(text, { target: { value: "  " } });
    fireEvent.blur(text);
    await flush();
    expect(saves().filter((save) => save.question === 6)).toEqual([{ question: 6, answer: null }]);
    // Leaving it again with nothing new saves nothing more.
    fireEvent.blur(text);
    await flush();
    expect(saves().filter((save) => save.question === 6)).toHaveLength(1);
  });

  it("checks the attempt when a save is refused: still running, it carries on; over, its result shows", async () => {
    let over = false;
    serve((path, method) => {
      if (method === "PUT") return new ApiError(400, { detail: over ? "Time is up: your attempt was graded with the answers you saved." : "This answer doesn't fit the question." });
      if (path.endsWith("/attempts/77/") && method === "GET") return over ? attemptResult({ state: "expired", passed: false, percent: 14, points: null, course_step_done: false }) : attemptPlay();
      return undefined;
    });
    play();
    fireEvent.click(screen.getByRole("radio", { name: /2–8 °C/ }));
    await flush();
    await flush();
    expect(screen.getByRole("heading", { name: "Question 1 of 7" })).toBeTruthy();
    expect(server.calls.some((call) => call.path.endsWith("/finish/"))).toBe(false);
    over = true;
    fireEvent.click(screen.getByRole("radio", { name: /15–25 °C/ }));
    expect(await screen.findByRole("heading", { name: "Not passed this time" })).toBeTruthy();
    expect(server.calls.some((call) => call.path.endsWith("/finish/"))).toBe(false);
  });

  it("counts what has no answer before finishing, and stays when the person says no", async () => {
    vi.mocked(window.confirm).mockReturnValueOnce(false);
    play();
    fireEvent.click(screen.getByRole("radio", { name: /2–8 °C/ }));
    fireEvent.click(screen.getByRole("button", { name: "Question 7" }));
    fireEvent.click(screen.getByRole("button", { name: "Finish" }));
    await flush();
    expect(window.confirm).toHaveBeenCalledWith("6 questions have no answer. Finish anyway?");
    expect(server.calls.some((call) => call.path.endsWith("/finish/"))).toBe(false);
    expect(screen.getByRole("heading", { name: "Question 7 of 7" })).toBeTruthy();
  });

  it("shows the time left and finishes by itself when it runs out", async () => {
    vi.useFakeTimers({ toFake: ["Date", "setInterval", "clearInterval"] });
    vi.setSystemTime(NOW);
    play(attemptPlay({ deadline_at: new Date(NOW.getTime() + 30_000).toISOString() }));
    expect(screen.getByRole("timer").textContent).toBe("0:30");
    await act(async () => {
      vi.advanceTimersByTime(25_000);
    });
    expect(screen.getByRole("timer").textContent).toBe("0:05");
    expect(screen.getByRole("timer").className).toContain("lrn-timer--low");
    await act(async () => {
      vi.advanceTimersByTime(6_000);
    });
    expect(await screen.findByRole("heading", { name: "Passed!" })).toBeTruthy();
    expect(window.confirm).not.toHaveBeenCalled();
  });

  it("shows the result when the attempt was already over on the server", async () => {
    serve((path, method) => {
      if (path.endsWith("/attempts/77/finish/")) return new ApiError(400, { detail: "The attempt is over." });
      if (path.endsWith("/attempts/77/") && method === "GET") return attemptResult({ state: "expired", passed: false, percent: 40, points: null, course_step_done: false });
      return undefined;
    });
    play(attemptPlay({ answers: Object.fromEntries(attemptPlay().questions.map((q) => [String(q.id), { option: "a" }])) }));
    fireEvent.click(screen.getByRole("button", { name: "Question 7" }));
    fireEvent.click(screen.getByRole("button", { name: "Finish" }));
    expect(await screen.findByRole("heading", { name: "Not passed this time" })).toBeTruthy();
    expect(screen.getByText("Time ran out: the saved answers were checked")).toBeTruthy();
    expect(celebrate).not.toHaveBeenCalled();
  });

  it("says when the answers haven't reached the server, and doesn't finish without them", async () => {
    vi.useFakeTimers({ toFake: ["Date", "setTimeout", "clearTimeout"] });
    vi.setSystemTime(NOW);
    serve((_path, method) => (method === "PUT" ? new TypeError("Failed to fetch") : undefined));
    play();
    fireEvent.click(screen.getByRole("radio", { name: /2–8 °C/ }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(screen.getByText("No connection: answers go when it’s back")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Question 7" }));
    fireEvent.click(screen.getByRole("button", { name: "Finish" }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(9_000);
    });
    expect(screen.getByText("Some answers haven’t reached the server yet. Check the connection and press Finish again.")).toBeTruthy();
    expect(server.calls.some((call) => call.path.endsWith("/finish/"))).toBe(false);
  });
});

describe("the result", () => {
  it("shows the score ring, the points, the step done and the review", async () => {
    result();
    expect(screen.getByRole("heading", { name: "Passed!" })).toBeTruthy();
    expect(screen.getByRole("img", { name: "81% right" })).toBeTruthy();
    expect(screen.getByText("6.5 of 8 points")).toBeTruthy();
    expect(screen.getByText("+20 points")).toBeTruthy();
    expect(screen.getByText("The course step is done")).toBeTruthy();
    expect(await screen.findByText("Pass mark 70%")).toBeTruthy();

    const cards = [...document.querySelectorAll(".lrn-review")] as HTMLElement[];
    expect(cards).toHaveLength(5);
    expect(cards[0].textContent).toContain("Right");
    expect(cards[0].textContent).toContain("Insulin 2–8 °C da saqlanadi.");
    expect(cards[0].textContent).not.toContain("Right answer");
    expect(within(cards[1]).getByText("Partly right: 50%")).toBeTruthy();
    expect(within(cards[1]).getAllByRole("listitem").map((item) => item.textContent)).toEqual(["Insulin", "Insulin", "Vaksinalar"]);
    expect(cards[2].querySelector(".lrn-review-line--right")?.textContent).toBe("Right answerInsulin–2–8 °CSirop–15–25 °C");
    expect(cards[3].textContent).toContain("No answer");
    expect(cards[3].querySelector(".lrn-review-line--right")?.textContent).toBe("Right answer2–8 or 2-8");
    expect(cards[4].querySelector(".lrn-review-line--right")?.textContent).toBe("Right answer5 ± 0.5 ml");
  });

  it("offers another try when the quiz allows one, and the way back to the course", async () => {
    result();
    fireEvent.click(await screen.findByRole("button", { name: "Try again" }));
    await flush();
    expect(server.calls.find((call) => call.method === "POST")).toEqual({ path: "/companies/1/learning/quizzes/8/attempts/", method: "POST", body: { assignment: 31 } });
    expect(navigationState().stack).toEqual([{ feature: "learning", page: "attempt", params: { id: 78, quiz: 8, assignment: 31, course: 4 } }]);
    cleanup();

    result();
    fireEvent.click(screen.getByRole("button", { name: "Back to the course" }));
    expect(navigationState().stack).toEqual([{ feature: "learning", page: "course", params: { id: 4 } }]);
  });

  it("says when the next try is, and when the review isn't shown", async () => {
    serve((path) => (path.includes("/learning/quizzes/8/") ? quizDetail({ can_start: false, retry_at: "2026-10-21T09:30:00Z" }) : undefined));
    result(attemptResult({ passed: false, percent: 50, points: null, review: null, course_step_done: false }));
    expect(screen.getByRole("heading", { name: "Not passed this time" })).toBeTruthy();
    expect(await screen.findByText("Next try: today, 14:30")).toBeTruthy();
    expect(screen.getByText("The answers aren’t shown for this attempt.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Try again" })).toBeNull();
  });
});

describe("a regular check", () => {
  it("opens its round's quiz with the entry and the deadline", async () => {
    renderApp(<CheckPage params={{ id: 61 }} />, { me, init: { stack: [{ feature: "learning", page: "check", params: { id: 61 } }] } });
    expect(await screen.findByRole("heading", { name: "Dushanba tekshiruvi" })).toBeTruthy();
    expect(screen.getByText("Regular check")).toBeTruthy();
    expect(screen.getByText("Answer by tomorrow, 10:00")).toBeTruthy();
    expect(server.calls.some((call) => call.path === "/companies/1/learning/quizzes/9/?entry=61")).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Start the test" }));
    await flush();
    expect(server.calls.find((call) => call.method === "POST")?.body).toEqual({ entry: 61 });
    expect(navigationState().stack).toEqual([{ feature: "learning", page: "attempt", params: { id: 79, quiz: 9, entry: 61 } }]);
  });

  it("says an entry that isn't the person's isn't here", async () => {
    renderApp(<CheckPage params={{ id: 404 }} />, { me });
    expect(await screen.findByText("This page isn't here")).toBeTruthy();
  });
});
