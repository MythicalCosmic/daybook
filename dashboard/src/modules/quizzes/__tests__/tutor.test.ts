// The registry first, as in the app: it is what loads every module's index.ts (see core/modules.ts).
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { toasts } from "@/components/useToast";
import { i18n, mergeModuleMessages, setLanguage } from "@/i18n";
import { useSessionStore } from "@/stores/session";
import { company, json, me } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

import TutorChat from "../components/TutorChat.vue";
import TutorDraftCardView from "../components/TutorDraftCard.vue";
import en from "../i18n/en.json";
import ru from "../i18n/ru.json";
import uz from "../i18n/uz.json";
import TutorPage from "../pages/TutorPage.vue";
import type { ChatMessage, Question, Tutor, TutorDraftCard, TutorDraftItem } from "../types";

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

const t = (key: string, values: Record<string, unknown> = {}) => i18n.global.t(key, values);
const byTestId = (root: ParentNode, id: string) => Array.from(root.querySelectorAll<HTMLElement>(`[data-testid="${id}"]`));

function question(overrides: Partial<Question> = {}): Question {
  return {
    id: 31,
    kind: "single",
    text: "Insulin muzlatgichda qanday haroratda saqlanadi?",
    data: {
      options: [
        { id: "a", text: "+2 °C dan +8 °C gacha", correct: true },
        { id: "b", text: "+15 °C dan +25 °C gacha", correct: false },
      ],
    },
    explanation: "Issiqqa sezgir dorilar +2 °C dan +8 °C gacha saqlanadi.",
    image: null,
    topic: { id: 3, name: "Sovuq zanjir", color: "sky" },
    difficulty: "medium",
    points: 1,
    state: "draft",
    source: "ai",
    lesson: null,
    page: { id: 8, title: "Sovuq zanjir" },
    draft_job_id: 2,
    answered: 0,
    correct: 0,
    correct_percent: null,
    quizzes: 0,
    created_at: "2026-11-10T09:00:00+05:00",
    updated_at: "2026-11-10T09:00:00+05:00",
    ...overrides,
  };
}

function item(id: number, overrides: Partial<TutorDraftItem> = {}): TutorDraftItem {
  const found = question({ id });
  return {
    id,
    deleted: false,
    question: found,
    preview: {
      question: {
        id,
        kind: "single",
        text: found.text,
        image_url: null,
        points: 1,
        options: [
          { id: "b", text: "+15 °C dan +25 °C gacha" },
          { id: "a", text: "+2 °C dan +8 °C gacha" },
        ],
        left: [],
        right: [],
        unit: null,
      },
      right_answer: { option: "a" },
      explanation: found.explanation,
    },
    ...overrides,
  };
}

function card(overrides: Partial<TutorDraftCard> = {}): TutorDraftCard {
  return {
    id: 4,
    kind: "questions",
    state: "done",
    turn_id: 5,
    message_id: 12,
    count: 2,
    title: "Sovuq zanjir",
    error: "",
    created_at: "2026-11-10T09:00:05+05:00",
    questions: [item(31), item(32)],
    quiz: null,
    ...overrides,
  };
}

function quizCard(overrides: Partial<TutorDraftCard> = {}): TutorDraftCard {
  return card({
    id: 6,
    kind: "quiz",
    title: "Sovuq zanjir testi",
    questions: [item(31), item(32, { question: question({ id: 32, state: "active" }), preview: null })],
    quiz: { id: 9, title: "Sovuq zanjir testi", status: "draft", pass_percent: 70, time_limit_seconds: 600, max_attempts: null, audience_all: true, positions: [] },
    ...overrides,
  });
}

function message(id: number, role: ChatMessage["role"], text: string, at = "2026-11-10T09:00:00+05:00"): ChatMessage {
  return { id, role, text, created_at: at, steps: role === "assistant" ? [{ label: "Writing draft questions", status: "done", ms: 900 }] : [] };
}

async function mountCard(value: TutorDraftCard, routes: Record<string, (call: Call) => Response> = {}) {
  const calls = stubApi(routes);
  const app = await testApp("/c/1/learning/tutor");
  const mounted = mountWithProviders(TutorDraftCardView, { props: { card: value }, plugins: app.plugins });
  await flushPromises();
  return { calls, ...mounted };
}

beforeEach(() => {
  mergeModuleMessages("quizzes", { en, ru, uz });
  toasts.splice(0, toasts.length);
});

afterEach(async () => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
  await setLanguage("en");
});

describe("the tutor's draft cards", () => {
  it("shows each draft question as the learner will see it, with the right answer marked", async () => {
    const { wrapper } = await mountCard(card());
    const rows = byTestId(document.body, "draft-question");
    expect(rows).toHaveLength(2);
    expect(rows[0]!.dataset.state).toBe("draft");
    expect(rows[0]!.textContent).toContain(t("quizzes.kind.single"));
    expect(rows[0]!.textContent).toContain("Sovuq zanjir");
    expect(rows[0]!.textContent).toContain(t("quizzes.state.draft"));
    const right = Array.from(rows[0]!.querySelectorAll("li")).find((li) => li.className.includes("border-success"));
    expect(right?.textContent).toContain("+2 °C dan +8 °C gacha");
    expect(rows[0]!.textContent).toContain("Issiqqa sezgir dorilar");
    expect(document.body.textContent).toContain("2 draft questions");
    expect(byTestId(document.body, "draft-approve")).toHaveLength(2);
    wrapper.unmount();
  });

  it("approves or discards one question by the person's own call, and edits it in the bank's editor", async () => {
    const { calls, wrapper, inner } = await mountCard(card(), {
      "POST learning/tutor/drafts/4/approve/": () => json(card()),
      "POST learning/tutor/drafts/4/discard/": () => json(card()),
    });
    byTestId(document.body, "draft-approve")[0]!.click();
    await flushPromises();
    byTestId(document.body, "draft-discard")[1]!.click();
    await flushPromises();
    const decided = calls.filter((call) => call.method === "POST");
    expect(decided.map((call) => [call.url.split("/companies/1/")[1], call.body])).toEqual([
      ["learning/tutor/drafts/4/approve/", { question_ids: [31] }],
      ["learning/tutor/drafts/4/discard/", { question_ids: [32] }],
    ]);
    expect(toasts.map((toast) => toast.title)).toEqual([t("quizzes.tutorDrafts.approved"), t("quizzes.tutorDrafts.discarded")]);
    byTestId(document.body, "draft-edit")[0]!.click();
    expect((inner.emitted("edit")?.[0]?.[0] as Question).id).toBe(31);
    wrapper.unmount();
  });

  it("approves every draft left at once", async () => {
    const { calls, wrapper } = await mountCard(card(), { "POST learning/tutor/drafts/4/approve/": () => json(card()) });
    byTestId(document.body, "draft-approve-all")[0]!.click();
    await flushPromises();
    expect(calls.find((call) => call.method === "POST")?.body).toEqual({});
    wrapper.unmount();
  });

  it("says when a question was discarded or is in use already, and offers nothing to do with it", async () => {
    const { wrapper } = await mountCard(card({ questions: [item(31, { deleted: true, question: null, preview: null }), item(32, { question: question({ id: 32, state: "active" }) })] }));
    const [gone, used] = byTestId(document.body, "draft-question");
    expect(gone!.dataset.state).toBe("deleted");
    expect(gone!.textContent).toContain(t("quizzes.tutorDrafts.deleted"));
    expect(used!.textContent).toContain(t("quizzes.state.active"));
    expect(byTestId(document.body, "draft-approve")).toHaveLength(0);
    expect(byTestId(document.body, "draft-approve-all")).toHaveLength(0);
    wrapper.unmount();
  });

  it("shows the questions being written while the tutor works", async () => {
    const { wrapper } = await mountCard(card({ state: "running", message_id: null, count: 5, questions: [] }));
    const [shown] = byTestId(document.body, "tutor-draft");
    expect(shown!.getAttribute("aria-busy")).toBe("true");
    expect(shown!.textContent).toContain(t("quizzes.tutorDrafts.writing"));
    expect(byTestId(document.body, "draft-question")).toHaveLength(0);
    wrapper.unmount();
  });

  it("publishes a draft test with its draft questions in one call, and links to its page", async () => {
    const { calls, wrapper } = await mountCard(quizCard(), { "POST learning/tutor/drafts/6/approve/": () => json(quizCard()) });
    const facts = byTestId(document.body, "draft-quiz-facts")[0]!.textContent ?? "";
    for (const words of ["2 questions", "drafts among them: 1", "Pass mark: 70 %", "Time: 10 min", "For everyone"]) expect(facts).toContain(words);
    expect(byTestId(document.body, "draft-open-quiz")[0]!.getAttribute("href")).toBe("/c/1/learning/quizzes/9");
    byTestId(document.body, "draft-publish")[0]!.click();
    await flushPromises();
    const [publish] = calls.filter((call) => call.method === "POST");
    expect([publish!.url.split("/companies/1/")[1], publish!.body]).toEqual(["learning/tutor/drafts/6/approve/", {}]);
    expect(toasts.map((toast) => toast.title)).toContain(t("quizzes.tutorDrafts.published"));
    wrapper.unmount();
  });

  it("says a discarded test is gone", async () => {
    const { wrapper } = await mountCard(quizCard({ quiz: null }));
    expect(document.body.textContent).toContain(t("quizzes.tutorDrafts.quizDeleted"));
    expect(byTestId(document.body, "draft-publish")).toHaveLength(0);
    wrapper.unmount();
  });
});

describe("the tutor's chat window", () => {
  /** The conversation 7 with these messages and cards, mounted. */
  async function chat(state: { messages: ChatMessage[]; cards: TutorDraftCard[] }, extra: Record<string, (call: Call) => Response> = {}) {
    const calls = stubApi({
      "GET learning/tutor/conversations/": () => json([{ id: 7, title: "Sovuq zanjir", created_at: "2026-11-10T09:00:00+05:00", last_activity_at: "2026-11-10T09:00:00+05:00" }]),
      "GET ai/conversations/7/messages/": () => json(state.messages),
      "GET learning/tutor/conversations/7/drafts/": () => json(state.cards),
      ...extra,
    });
    const app = await testApp("/c/1/learning/tutor");
    const mounted = mountWithProviders(TutorChat, { plugins: app.plugins });
    await flushPromises();
    await flushPromises();
    return { calls, app, ...mounted };
  }

  function sized(thread: HTMLElement, height: number, view = 400) {
    Object.defineProperty(thread, "scrollHeight", { configurable: true, get: () => height });
    Object.defineProperty(thread, "clientHeight", { configurable: true, get: () => view });
  }

  it("is a window of its own: the messages scroll inside it and the composer stays at its foot", async () => {
    const { wrapper } = await chat({ messages: [message(11, "user", "3 ta savol tuz"), message(12, "assistant", "Kartalarni ko‘ring.")], cards: [card()] });
    const [panel] = byTestId(document.body, "tutor-chat");
    const [thread] = byTestId(document.body, "tutor-thread");
    const [composer] = byTestId(document.body, "tutor-composer");
    expect(panel!.className).toContain("h-full");
    expect(panel!.className).toContain("overflow-hidden");
    expect(thread!.className).toContain("overflow-y-auto");
    expect(thread!.className).toContain("min-h-0");
    expect(thread!.getAttribute("role")).toBe("log");
    expect(thread!.contains(composer!)).toBe(false);
    expect(composer!.className).toContain("shrink-0");
    // The card sits under the answer it belongs to.
    const answer = document.body.querySelector('[data-message="12"]')!;
    expect(answer.querySelectorAll('[data-testid="tutor-draft"]')).toHaveLength(1);
    expect(answer.textContent).toContain("Writing draft questions");
    wrapper.unmount();
  });

  it("follows the newest message, and once the reader scrolled up shows a pill instead", async () => {
    const state = { messages: [message(11, "user", "Kim sust?"), message(12, "assistant", "Alisher.")], cards: [] as TutorDraftCard[] };
    const { app, wrapper } = await chat(state);
    const [thread] = byTestId(document.body, "tutor-thread");
    const scrolled = vi.fn();
    thread!.scrollTo = scrolled as unknown as typeof thread.scrollTo;
    sized(thread!, 1000);
    thread!.scrollTop = 600; // at the foot
    thread!.dispatchEvent(new Event("scroll"));

    state.messages = [...state.messages, message(13, "user", "Yana?"), message(14, "assistant", "Madina.")];
    await app.client.refetchQueries({ queryKey: [1, "quizzes", "messages"] });
    await flushPromises();
    expect(scrolled).toHaveBeenLastCalledWith({ top: 1000, behavior: "auto" });
    expect(byTestId(document.body, "tutor-new-messages")).toHaveLength(0);

    thread!.scrollTop = 100; // the reader went up
    thread!.dispatchEvent(new Event("scroll"));
    scrolled.mockClear();
    state.messages = [...state.messages, message(15, "user", "Va?"), message(16, "assistant", "Jasur.")];
    await app.client.refetchQueries({ queryKey: [1, "quizzes", "messages"] });
    await flushPromises();
    expect(scrolled).not.toHaveBeenCalled();
    const [pill] = byTestId(document.body, "tutor-new-messages");
    expect(pill!.textContent).toContain(t("quizzes.chat.newMessages"));
    pill!.click();
    await flushPromises();
    expect(scrolled).toHaveBeenLastCalledWith({ top: 1000, behavior: "smooth" });
    expect(byTestId(document.body, "tutor-new-messages")).toHaveLength(0);
    wrapper.unmount();
  });

  it("shows the card being written while the tutor works, then under its answer", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const state = { messages: [] as ChatMessage[], cards: [] as TutorDraftCard[] };
    let polled = 0;
    const { wrapper } = await chat(state, {
      "POST ai/conversations/7/turns/": () => {
        state.messages = [message(11, "user", "Sovuq zanjir bo‘yicha 5 ta savol tuz")];
        state.cards = [card({ state: "running", message_id: null, count: 5, questions: [] })];
        return json({ turn_id: 5 }, 202);
      },
      "GET ai/turns/5/": () => {
        polled += 1;
        if (polled === 1) return json({ id: 5, status: "running", steps: [], text: "", error_code: "", message_id: null });
        state.messages = [...state.messages, message(12, "assistant", "5 ta savol qoralamasi tayyor.", "2026-11-10T09:00:09+05:00")];
        state.cards = [card()];
        return json({ id: 5, status: "done", steps: [], text: "5 ta savol qoralamasi tayyor.", error_code: "", message_id: 12 });
      },
    });
    const box = document.body.querySelector("textarea")!;
    box.value = "Sovuq zanjir bo‘yicha 5 ta savol tuz";
    box.dispatchEvent(new Event("input"));
    await flushPromises();
    byTestId(document.body, "tutor-composer")[0]!.dispatchEvent(new Event("submit"));
    await flushPromises();
    await flushPromises();

    const [live] = byTestId(document.body, "tutor-working");
    expect(live!.textContent).toContain(t("quizzes.tutorDrafts.writing"));
    expect(live!.querySelector('[data-testid="tutor-draft"]')!.getAttribute("data-state")).toBe("running");

    await vi.advanceTimersByTimeAsync(1600);
    await flushPromises();
    await flushPromises();
    expect(byTestId(document.body, "tutor-working")).toHaveLength(0);
    const answer = document.body.querySelector('[data-message="12"]')!;
    expect(answer.querySelector('[data-testid="tutor-draft"]')!.getAttribute("data-state")).toBe("done");
    wrapper.unmount();
  });

  it("without the right to manage training it shows no cards and offers no drafting", async () => {
    const calls = stubApi({
      "GET learning/tutor/conversations/": () => json([]),
    });
    const app = await testApp("/c/1/learning/tutor");
    useSessionStore().me = me([company({ is_owner: false, role: { id: 3, name: "Viewer" }, permissions: ["learning.view", "ai.use"] })]);
    const { wrapper } = mountWithProviders(TutorChat, { plugins: app.plugins });
    await flushPromises();
    expect(calls.some((call) => call.url.includes("/drafts/"))).toBe(false);
    const empty = byTestId(document.body, "tutor-chat-empty")[0]!.textContent ?? "";
    expect(empty).toContain(t("quizzes.chat.try3"));
    expect(empty).not.toContain(t("quizzes.chat.try4"));
    wrapper.unmount();
  });
});

describe("the tutor's page", () => {
  it("keeps the chat a panel of its own height, and on wide screens two panes that fill the window", async () => {
    const tutor: Tutor = {
      agent: { listed: true, enabled: true, ai_on: true, claude: "ok", chat: true, next_report_at: null, config: { weekly_report: true, report_day: "0", at: "09:00", nudge_learners: true, suggest: true, weak_threshold: 60 } },
      report: null,
      suggestions: { total: 0 },
      weakest: [],
      events: [],
    };
    stubApi({
      "GET learning/tutor/": () => json(tutor),
      "GET learning/suggestions/": () => json([]),
      "GET learning/tutor/conversations/": () => json([]),
    });
    const app = await testApp("/c/1/learning/tutor");
    const { wrapper } = mountWithProviders(TutorPage, { plugins: app.plugins });
    await flushPromises();
    await flushPromises();
    const [page] = byTestId(document.body, "tutor-page");
    const [panel] = byTestId(document.body, "tutor-chat-panel");
    const [findings] = byTestId(document.body, "tutor-findings");
    expect(page!.className).toContain("xl:h-[calc(100dvh-var(--topbar-h)-86px)]");
    expect(panel!.className).toContain("h-[calc(100dvh-var(--topbar-h)");
    expect(panel!.className).toContain("overflow-hidden");
    expect(panel!.className).toContain("xl:h-auto");
    expect(findings!.className).toContain("xl:overflow-y-auto");
    expect(panel!.querySelector('[data-testid="tutor-chat"]')).not.toBeNull();
    wrapper.unmount();
  });
});
