// The registry first, as in the app: it is what loads every module's index.ts (see core/modules.ts).
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { toasts } from "@/components/useToast";
import { i18n, mergeModuleMessages, setLanguage } from "@/i18n";
import { json } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

import QuestionEditor from "../components/QuestionEditor.vue";
import QuestionPreview from "../components/QuestionPreview.vue";
import en from "../i18n/en.json";
import ru from "../i18n/ru.json";
import uz from "../i18n/uz.json";
import module from "../index";
import { band, blankDraft, dataOf, draftOf, moved, normalize, percent, previewOf, scheduleText, serverProblems, validate, type Draft } from "../lib";
import QuestionsPage from "../pages/QuestionsPage.vue";
import type { DraftJobDetail, Question, QuestionPlay } from "../types";

interface Call {
  method: string;
  url: string;
  body: unknown;
}

function stubApi(routes: Record<string, (call: Call) => Response>): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init?: RequestInit) => {
      const body = init?.body;
      const call = { method: init?.method ?? "GET", url: input, body: typeof body === "string" ? JSON.parse(body) : body };
      calls.push(call);
      const path = input.replace("/api/v1/owner/companies/1/", "").split("?")[0]!;
      const handler = routes[`${call.method} ${path}`];
      return handler ? handler(call) : json({ detail: "Not found." }, 404);
    }),
  );
  return calls;
}

function draft(kind: Draft["kind"], patch: Partial<Draft> = {}): Draft {
  return { ...blankDraft(kind), text: "Insulin qayerda saqlanadi?", ...patch };
}

function question(overrides: Partial<Question> = {}): Question {
  return {
    id: 9,
    kind: "single",
    text: "Insulin qayerda saqlanadi?",
    data: { options: [{ id: "a", text: "Muzlatkichda", correct: true }, { id: "b", text: "Javonda", correct: false }] },
    explanation: "",
    image: null,
    topic: { id: 3, name: "Sovuq zanjir", color: "#2f80ed" },
    difficulty: "medium",
    points: 1,
    state: "active",
    source: "manual",
    lesson: null,
    page: null,
    draft_job_id: null,
    answered: 0,
    correct: 0,
    correct_percent: null,
    quizzes: 0,
    created_at: "2026-11-01T09:00:00+05:00",
    updated_at: "2026-11-01T09:00:00+05:00",
    ...overrides,
  };
}

const t = (key: string, values: Record<string, unknown> = {}) => i18n.global.t(key, values);
const plural = (key: string, n: number) => i18n.global.t(key, { n }, n);

beforeEach(() => {
  mergeModuleMessages("quizzes", { en, ru, uz });
  toasts.splice(0, toasts.length);
});

afterEach(async () => {
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
  await setLanguage("en");
});

describe("module", () => {
  it("registers its pages, both learning slots, the settings panel and the deep links", () => {
    expect(module.id).toBe("quizzes");
    expect(module.feature).toBe("learning");
    expect(module.routes.map((route) => route.name)).toEqual(["quizzes.list", "quizzes.quiz", "quizzes.questions", "quizzes.checks", "quizzes.skills", "quizzes.tutor"]);
    expect(module.nav?.map((item) => item.key)).toEqual(["quizzes", "questions", "checks", "skills", "tutor"]);
    expect(Object.keys(module.extensions ?? {})).toEqual(["learning.person.panels", "learning.overview.cards"]);
    expect(module.settings?.map((panel) => panel.id)).toEqual(["quizzes-daily"]);
    expect(module.deepLinks?.quiz?.("12")).toBe("learning/quizzes/12");
    expect(module.deepLinks?.quiz?.("../x")).toBe("learning/quizzes");
    expect(module.deepLinks?.tutor?.("")).toBe("learning/tutor");
  });
});

describe("validate (apps/learning/grading.py clean_data)", () => {
  it("passes a good question of every kind", () => {
    const good = [
      draft("single", { options: [{ text: "Muzlatkichda", correct: true }, { text: "Javonda", correct: false }] }),
      draft("multi", { options: [{ text: "A", correct: true }, { text: "B", correct: true }] }),
      draft("true_false", { answer: false }),
      draft("order", { items: [{ text: "Qabul qilish" }, { text: "Tekshirish" }, { text: "Joylash" }] }),
      draft("match", { pairs: [{ left: "Insulin", right: "2–8 °C" }, { left: "Paratsetamol", right: "25 °C gacha" }] }),
      draft("text", { answers: ["2–8", ""] }),
      draft("number", { value: 4.5, tolerance: 0.1, unit: "ml" }),
    ];
    for (const one of good) expect(validate(one), one.kind).toEqual({});
  });

  it("asks for the text and keeps the points within 1–10", () => {
    expect(validate(draft("true_false", { text: "  ", points: 11 }))).toEqual({ text: { key: "quizzes.err.empty" }, points: { key: "quizzes.err.points" } });
    expect(validate(draft("true_false", { text: "x".repeat(1001) })).text).toEqual({ key: "quizzes.err.long", values: { max: 1000 } });
  });

  it("checks the options of one and of several right answers", () => {
    const two = [
      { text: "A", correct: true },
      { text: "B", correct: true },
    ];
    expect(validate(draft("single", { options: two })).options).toEqual({ key: "quizzes.err.oneRight" });
    expect(validate(draft("multi", { options: two.map((o) => ({ ...o, correct: false })) })).options).toEqual({ key: "quizzes.err.someRight" });
    expect(validate(draft("single", { options: [{ text: "A", correct: true }] })).options).toEqual({ key: "quizzes.err.count", values: { min: 2, max: 6 } });
    // The same after normalising, as the server compares them.
    expect(validate(draft("single", { options: [{ text: "2–8 °C", correct: true }, { text: "2-8", correct: false }] })).options).toEqual({ key: "quizzes.err.same" });
    expect(validate(draft("single", { options: [{ text: "A", correct: true }, { text: " ", correct: false }] }))).toEqual({ "options.1.text": { key: "quizzes.err.empty" } });
  });

  it("checks the steps and the pairs", () => {
    expect(validate(draft("order", { items: [{ text: "A" }, { text: "B" }] })).items).toEqual({ key: "quizzes.err.count", values: { min: 3, max: 8 } });
    expect(validate(draft("order", { items: [{ text: "A" }, { text: "a" }, { text: "B" }] })).items).toEqual({ key: "quizzes.err.same" });
    expect(validate(draft("match", { pairs: [{ left: "A", right: "" }, { left: "B", right: "1" }] }))).toEqual({ "pairs.0.right": { key: "quizzes.err.empty" } });
    expect(validate(draft("match", { pairs: [{ left: "A", right: "1" }, { left: "B", right: "1" }] })).pairs).toEqual({ key: "quizzes.err.same" });
  });

  it("checks the accepted answers and the number", () => {
    expect(validate(draft("text", { answers: ["", " "] })).answers).toEqual({ key: "quizzes.err.noAnswer" });
    expect(validate(draft("text", { answers: ["°C"] }))["answers.0"]).toEqual({ key: "quizzes.err.lettersOrDigits" });
    expect(validate(draft("text", { answers: Array.from({ length: 11 }, (_, i) => `v${i}`) })).answers).toEqual({ key: "quizzes.err.manyAnswers", values: { max: 10 } });
    expect(validate(draft("number", { value: null, tolerance: -1 }))).toEqual({ value: { key: "quizzes.err.value" }, tolerance: { key: "quizzes.err.tolerance" } });
  });

  it("files the server's errors under the editor's names", () => {
    expect(serverProblems({ "data.options.1.text": ["Too long."], text: ["Write the question."], points: [] })).toEqual({ "options.1.text": "Too long.", text: "Write the question." });
  });
});

describe("normalize (grading.normalize_text, the same cases as test_grading.py)", () => {
  const accepted = new Set(["2–8", "+2 – +8"].map((answer) => normalize(answer, false)));

  it.each(["2-8", "2–8", " 2 — 8 ", "2 - 8 °C", "2°C - 8°C", "2-8 C", "2‒8℃", "+2 – +8", "2-8."])("accepts %j", (typed) => {
    expect(accepted.has(normalize(typed, false))).toBe(true);
  });

  it.each(["2-9", "28", "2 8", "sakkiz"])("refuses %j", (typed) => {
    expect(accepted.has(normalize(typed, false))).toBe(false);
  });

  it("unifies the apostrophes, keeps case when asked and leaves a word after a number alone", () => {
    const right = normalize("Ko‘k terak", false);
    for (const typed of ["ko'k  terak", "KOʻK TERAK", "ko`k terak", "Ko’k terak"]) expect(normalize(typed, false)).toBe(right);
    expect(normalize("XPN", true)).not.toBe(normalize("xpn", true));
    expect(normalize("5 сутки", false)).toBe("5 сутки");
    expect(normalize("2-8 С", false)).toBe("2-8");
  });
});

describe("the editor's model", () => {
  it("sends only the kind's part, trimmed, with the ids kept", () => {
    expect(dataOf(draft("single", { options: [{ id: "a", text: " A ", correct: true }, { text: "B", correct: false }] }))).toEqual({
      options: [
        { id: "a", text: "A", correct: true },
        { text: "B", correct: false },
      ],
    });
    expect(dataOf(draft("text", { answers: [" 2–8 ", "", "  "], caseSensitive: true }))).toEqual({ answers: ["2–8"], case: true });
    expect(dataOf(draft("number", { value: 36.6, tolerance: 0.2, unit: " °C " }))).toEqual({ value: 36.6, tolerance: 0.2, unit: "°C" });
  });

  it("reads a saved question back as it was", () => {
    const saved = question({ kind: "match", data: { pairs: [{ id: "x", left: "A", right: "1" }, { id: "y", left: "B", right: "2" }] } });
    const back = draftOf(saved);
    expect(back.kind).toBe("match");
    expect(back.topic_id).toBe(3);
    expect(dataOf(back)).toEqual(saved.data);
  });

  it("moves a step within the list only", () => {
    expect(moved([1, 2, 3], 0, -1)).toEqual([1, 2, 3]);
    expect(moved([1, 2, 3], 0, 1)).toEqual([2, 1, 3]);
    expect(moved([1, 2, 3], 2, 1)).toEqual([1, 2, 3]);
  });
});

describe("the learner's preview", () => {
  const stay = () => 0.999; // a shuffle that would leave everything where it is

  it("never shows the steps or the right side in their right order, and numbers them by place", () => {
    const steps = previewOf(draft("order", { items: [{ text: "1" }, { text: "2" }, { text: "3" }] }), stay);
    expect(steps.options.map((o) => o.text)).not.toEqual(["1", "2", "3"]);
    expect(steps.options.map((o) => o.id)).toEqual(["o1", "o2", "o3"]);
    const pairs = previewOf(draft("match", { pairs: [{ left: "A", right: "1" }, { left: "B", right: "2" }] }), stay);
    expect(pairs.left.map((o) => o.text)).toEqual(["A", "B"]);
    expect(pairs.right.map((o) => o.text)).toEqual(["2", "1"]);
    expect(pairs.right.map((o) => o.id)).toEqual(["r1", "r2"]);
  });

  it("carries nothing but what a learner gets", () => {
    const play = previewOf(draft("single", { options: [{ id: "a", text: "A", correct: true }, { id: "b", text: "B", correct: false }] }));
    expect(Object.keys(play).sort()).toEqual(["id", "image_url", "kind", "left", "options", "points", "right", "text", "unit"]);
    expect(JSON.stringify(play)).not.toContain("correct");
    expect(previewOf(draft("number", { value: 5, unit: " ml " })).unit).toBe("ml");
  });

  it("marks the right answer only when given one", async () => {
    const app = await testApp("/c/1/learning/questions");
    const play: QuestionPlay = { id: 1, kind: "single", text: "Insulin qayerda saqlanadi?", image_url: null, points: 1, options: [{ id: "a", text: "Muzlatkichda" }, { id: "b", text: "Javonda" }], left: [], right: [], unit: null };
    const bare = mountWithProviders(QuestionPreview, { props: { question: play }, plugins: app.plugins });
    expect(bare.wrapper.find('[aria-label="Right answer"]').exists()).toBe(false);
    bare.wrapper.unmount();
    const marked = mountWithProviders(QuestionPreview, { props: { question: play, right: { option: "a" }, answer: { option: "b" } }, plugins: app.plugins });
    expect(marked.wrapper.findAll('[aria-label="Right answer"]')).toHaveLength(1);
    expect(marked.wrapper.findAll('[aria-label="Their answer"]')).toHaveLength(1);
    marked.wrapper.unmount();
  });
});

describe("bands, schedules and wording", () => {
  it("puts a score in its band", () => {
    expect([null, 0, 59, 60, 84, 85, 100].map((score) => band(score))).toEqual(["unrated", "weak", "weak", "ok", "ok", "strong", "strong"]);
    expect(percent(2, 3)).toBe(66);
    expect(percent(0, 0)).toBeNull();
  });

  it("says when a check runs in each language", async () => {
    const weekly = { every: "week" as const, weekday: 2, month_day: null, at: "09:30:00" };
    const monthly = { every: "month" as const, weekday: null, month_day: 5, at: "18:00:00" };
    expect([scheduleText(weekly, t), scheduleText(monthly, t)]).toEqual(["Every Wednesday, 09:30", "Monthly, day 5, 18:00"]);
    await setLanguage("ru");
    expect([scheduleText(weekly, t), scheduleText(monthly, t)]).toEqual(["Каждую среду, 09:30", "Ежемесячно, 5-го числа, 18:00"]);
    await setLanguage("uz");
    expect([scheduleText(weekly, t), scheduleText(monthly, t)]).toEqual(["Har chorshanba, 09:30", "Har oy, sana: 5, 18:00"]);
  });

  it("counts in the three plural forms", async () => {
    expect([0, 1, 2].map((n) => plural("quizzes.bank.changed", n))).toEqual(["0 questions changed", "1 question changed", "2 questions changed"]);
    await setLanguage("ru");
    expect([1, 3, 5, 21].map((n) => plural("quizzes.bank.changed", n))).toEqual(["Изменён 1 вопрос", "Изменено 3 вопроса", "Изменено 5 вопросов", "Изменён 21 вопрос"]);
    expect([1, 2, 11].map((n) => plural("quizzes.checks.within", n))).toEqual(["1 час на ответ", "2 часа на ответ", "11 часов на ответ"]);
    await setLanguage("uz");
    expect([1, 5].map((n) => plural("quizzes.bank.changed", n))).toEqual(["1 ta savol o‘zgartirildi", "5 ta savol o‘zgartirildi"]);
  });
});

describe("the bank", () => {
  function job(state: DraftJobDetail["state"], made = 0): DraftJobDetail {
    return {
      id: 5,
      state,
      engine: "claude",
      page: { id: 8, title: "Sovuq zanjir" },
      lesson: null,
      topic: null,
      count: 3,
      kinds: [],
      difficulty: "",
      made,
      dropped: state === "done" ? 1 : 0,
      error: "",
      created_at: "2026-11-09T09:00:00+05:00",
      finished_at: null,
      questions: [],
    };
  }

  it("follows a drafting job from the link until its drafts are written", async () => {
    let asked = 0;
    const calls = stubApi({
      "GET learning/questions/": () => json({ count: 1, next: null, previous: null, results: [question({ state: "draft", source: "ai", draft_job_id: 5 })] }),
      "GET knowledge/topics/": () => json([]),
      "GET learning/drafts/5/": () => {
        asked += 1;
        return json(asked === 1 ? job("running") : job("done", 2));
      },
    });
    const app = await testApp("/c/1/learning/questions?job=5");
    const { wrapper } = mountWithProviders(QuestionsPage, { plugins: app.plugins });
    await flushPromises();
    expect(document.body.querySelector('[data-testid="draft-job"]')?.textContent).toContain("Writing questions from «Sovuq zanjir»");
    expect(calls.find((call) => call.url.includes("learning/questions/"))!.url).toContain("draft_job=5");
    await app.client.refetchQueries({ queryKey: [1, "quizzes", "draft"] });
    await flushPromises();
    const done = document.body.querySelector('[data-testid="draft-job"]')?.textContent ?? "";
    expect(done).toContain("2 drafts written from «Sovuq zanjir».");
    expect(done).toContain("1 left out (not in the text).");
    wrapper.unmount();
  });
});

describe("QuestionEditor", () => {
  function type(element: Element | undefined, value: string): void {
    const input = element as HTMLInputElement | HTMLTextAreaElement;
    input.value = value;
    input.dispatchEvent(new Event("input"));
  }
  const buttonCalled = (label: string) => Array.from(document.body.querySelectorAll("button")).find((button) => button.textContent?.trim() === label)!;

  it("shows what to fix and sends nothing until the question is whole", async () => {
    const calls = stubApi({ "GET knowledge/topics/": () => json([]) });
    const app = await testApp("/c/1/learning/questions");
    const { wrapper } = mountWithProviders(QuestionEditor, { props: { open: true, kind: "single" }, plugins: app.plugins });
    await flushPromises();
    buttonCalled("Save").click();
    await flushPromises();
    // The text and the three empty options.
    expect(document.body.querySelector('[data-testid="question-problems"]')?.textContent).toBe("4 things to fix");
    expect(document.body.textContent).toContain("Write something here.");
    expect(calls.filter((call) => call.method === "POST")).toHaveLength(0);
    wrapper.unmount();
  });

  it("saves a question in the server's shape", async () => {
    const calls = stubApi({
      "GET knowledge/topics/": () => json([{ id: 3, name: "Sovuq zanjir", color: "#2f80ed", archived: false }]),
      "POST learning/questions/": (call) => json(question({ id: 12, ...(call.body as Partial<Question>) }), 201),
    });
    const app = await testApp("/c/1/learning/questions");
    const { wrapper, inner } = mountWithProviders(QuestionEditor, { props: { open: true, kind: "single" }, plugins: app.plugins });
    await flushPromises();
    type(document.body.querySelector("textarea") ?? undefined, " Insulin qayerda saqlanadi? ");
    const options = Array.from(document.body.querySelectorAll('input[placeholder="An option"]'));
    expect(options).toHaveLength(3);
    type(options[0], "Muzlatkichda, 2–8 °C");
    type(options[1], "Javonda");
    type(options[2], "Seyfda");
    await flushPromises();
    // The preview shows the options (shuffled), and no mark of the right one.
    const preview = document.body.querySelector('[data-testid="question-preview"]')!;
    expect(preview.textContent).toContain("Seyfda");
    expect(preview.querySelector('[aria-label="Right answer"]')).toBeNull();

    buttonCalled("Save").click();
    await flushPromises();
    const post = calls.find((call) => call.method === "POST")!;
    expect(post.url).toContain("/owner/companies/1/learning/questions/");
    expect(post.body).toEqual({
      kind: "single",
      text: "Insulin qayerda saqlanadi?",
      data: {
        options: [
          { text: "Muzlatkichda, 2–8 °C", correct: true },
          { text: "Javonda", correct: false },
          { text: "Seyfda", correct: false },
        ],
      },
      explanation: "",
      topic_id: null,
      difficulty: "medium",
      points: 1,
      image_id: null,
      state: "active",
    });
    expect(inner.emitted("saved")).toHaveLength(1);
    expect(inner.emitted("update:open")?.at(-1)).toEqual([false]);
    wrapper.unmount();
  });
});
