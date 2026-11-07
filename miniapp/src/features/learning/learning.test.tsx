/**
 * Training in the mini app (docs/PLAN-LEARNING.md §12.1): who sees it, its deep links, Home's
 * training card, Me's badge, the learning home's tabs and checks, and the course page (locked,
 * open and done steps, Continue, a page step in the knowledge reader, Start the course).
 */
import { act, cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { featureTranslator } from "../../i18n/feature";
import { parseScreen, resolveScreen } from "../../state/deeplink";
import { membership, navigationState, NOW, person, renderApp } from "../../test/harness";
import { PageReader } from "../knowledge/PageReader";
import { features, featureVisible, findFeature, homeSlots, meItemsByGroup } from "../registry";
import { courseDetail, checkEntry, home, step } from "./fixtures";
import CoursePage from "./CoursePage";
import LearningHome from "./LearningHome";
import { continueStep, dueText, isAnswered, openMandatory, parseNumber, sortTodo, whenText } from "./lib";
import { messages } from "./messages";
import { dropIndex, moveItem } from "./questions";
import { TrainingCard } from "./slots";
import type { CourseDetail } from "./types";

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

const learning = findFeature(features, "learning")!;
const company = { id: 1, name: "Demo Dorixona", timezone: "Asia/Tashkent", features: ["learning"] };
const alisher = membership({ company } as never);
const me = person([alisher]);
const member = { ...alisher, timeZone: "Asia/Tashkent", companyId: 1 };
const en = featureTranslator(messages, "en");

type Handler = (path: string, method: string, body: unknown) => unknown;
function serve(extra: Handler = () => undefined) {
  server.handler = (path, method, body) => {
    const own = extra(path, method, body);
    if (own !== undefined) return own;
    if (path.endsWith("/learning/")) return home();
    if (path.endsWith("/learning/checks/")) return [];
    if (path.endsWith("/learning/courses/4/")) return courseDetail();
    return {};
  };
}

beforeEach(() => {
  server.calls = [];
  serve();
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("the rules", () => {
  it("orders open courses late first, then by deadline", () => {
    expect(sortTodo(home().todo).map((card) => card.id)).toEqual([32, 31, 33]);
    expect(openMandatory(home().todo).map((card) => card.id)).toEqual([32, 31]);
  });

  it("says deadlines in the company's day", () => {
    const tz = "Asia/Tashkent";
    expect(dueText({ due_at: "2026-10-21T18:59:59Z", late: false }, NOW, tz, "en-GB", en)).toBe("Due today");
    expect(dueText({ due_at: "2026-10-22T18:59:59Z", late: false }, NOW, tz, "en-GB", en)).toBe("Due tomorrow");
    expect(dueText({ due_at: "2026-10-28T18:59:59Z", late: false }, NOW, tz, "en-GB", en)).toBe("Due 28 Oct");
    expect(dueText({ due_at: "2026-10-19T18:59:59Z", late: true }, NOW, tz, "en-GB", en)).toBe("Late since 19 Oct");
    expect(dueText({ due_at: null, late: false }, NOW, tz, "en-GB", en)).toBeNull();
    expect(whenText("2026-10-22T05:00:00Z", NOW, tz, "en-GB", en)).toBe("tomorrow, 10:00");
    expect(whenText("2026-10-23T05:00:00Z", NOW, tz, "en-GB", en)).toBe("Friday, 10:00");
    expect(whenText("2026-10-21T09:30:00Z", NOW, tz, "en-GB", en)).toBe("today, 14:30");
  });

  it("continues with the first open step, a required one first", () => {
    expect(continueStep(courseDetail())?.id).toBe(103);
    expect(continueStep({ steps: [step({ id: 1, required: false }), step({ id: 2 })] })?.id).toBe(2);
    expect(continueStep({ steps: [step({ id: 1, done: true }), step({ id: 2, locked: true })] })).toBeNull();
  });

  it("drops a dragged row past the middle of the rows it passes", () => {
    const boxes = [0, 68, 136].map((top) => ({ top, height: 60 }));
    expect(dropIndex(0, 20, boxes)).toBe(0);
    expect(dropIndex(0, 50, boxes)).toBe(1);
    expect(dropIndex(0, 120, boxes)).toBe(2);
    expect(dropIndex(0, 999, boxes)).toBe(2);
    expect(dropIndex(2, -50, boxes)).toBe(1);
    expect(dropIndex(2, -120, boxes)).toBe(0);
    expect(moveItem(["a", "b", "c"], 0, 2)).toEqual(["b", "c", "a"]);
  });

  it("reads numbers as people type them, and knows a whole answer", () => {
    expect(parseNumber("4,5")).toBe(4.5);
    expect(parseNumber(" 12 ")).toBe(12);
    expect(parseNumber("-0.5")).toBe(-0.5);
    expect(parseNumber("4,")).toBeNull();
    expect(parseNumber("abc")).toBeNull();
    const match = { id: 1, kind: "match" as const, text: "", image_url: null, points: 1, options: [], left: [{ id: "l1", text: "" }, { id: "l2", text: "" }], right: [], unit: null };
    expect(isAnswered(match, { pairs: { l1: "r1" } })).toBe(false);
    expect(isAnswered(match, { pairs: { l1: "r1", l2: "r2" } })).toBe(true);
  });
});

describe("the feature", () => {
  const context = (who = alisher) => ({ member: { ...who, timeZone: "Asia/Tashkent", companyId: 1 }, summary: undefined });

  it("shows only while the company has training on, to people who work here", () => {
    expect(featureVisible(learning, context())).toBe(true);
    expect(featureVisible(learning, context(membership({ company: { ...company, features: [] } } as never)))).toBe(false);
    expect(featureVisible(learning, context(membership({ company, status: "suspended" } as never)))).toBe(false);
    expect(featureVisible(learning, context(membership({ company, status: "pending" } as never)))).toBe(false);
  });

  it("puts its cards on Home and My training on Me", () => {
    expect(homeSlots(features, "home.cards", context()).filter(({ feature }) => feature.id === "learning").map(({ item }) => item.id)).toEqual(["check", "daily", "training"]);
    expect(meItemsByGroup(features, context()).work.map(({ item }) => item.label)).toContain("me.training");
  });

  it("answers every deep link of the plan", () => {
    const go = (name: string, arg: string | null) => resolveScreen({ name, arg }, features);
    expect(go("learning", null)).toEqual({ tab: "profile", stack: [{ feature: "learning", page: "home", params: {} }] });
    expect(go("course", "4")).toEqual({ tab: "home", stack: [{ feature: "learning", page: "course", params: { id: 4 } }] });
    expect(go("lesson", "12")).toEqual({ tab: "home", stack: [{ feature: "learning", page: "lesson", params: { id: 12 } }] });
    expect(go("quiz", "8")).toEqual({ tab: "home", stack: [{ feature: "learning", page: "quiz", params: { id: 8 } }] });
    expect(go("check", "61")).toEqual({ tab: "home", stack: [{ feature: "learning", page: "check", params: { id: 61 } }] });
    expect(go("daily", null)).toEqual({ tab: "home", stack: [{ feature: "learning", page: "daily", params: {} }] });
    // t.me/<bot>/app?startapp=learn-4
    expect(resolveScreen(parseScreen("learn-4", "startapp"), features)).toEqual({ tab: "home", stack: [{ feature: "learning", page: "course", params: { id: 4 } }] });
    expect(go("learning.attempt", "77")).toEqual({ tab: "home", stack: [{ feature: "learning", page: "attempt", params: { id: 77 } }] });
  });

  it("counts the open mandatory courses on Me", async () => {
    const status = learning.meItems![0].useStatus!;
    let badge: number | null | undefined;
    function Probe() {
      badge = status({ member, summary: undefined }).badge;
      return null;
    }
    renderApp(<Probe />, { me });
    await waitFor(() => expect(badge).toBe(2));
  });

  it("has the plan's words in Uzbek and Russian", () => {
    const uz = featureTranslator(messages, "uz");
    const ru = featureTranslator(messages, "ru");
    expect([uz("title"), ru("title")]).toEqual(["O‘qitish", "Обучение"]);
    expect([uz("daily.title"), ru("daily.title")]).toEqual(["Kun savoli", "Вопрос дня"]);
    expect([uz("check.kicker"), ru("check.kicker")]).toEqual(["Muntazam tekshiruv", "Регулярная проверка"]);
    expect([uz("quiz.facts.pass"), ru("quiz.facts.pass")]).toEqual(["O‘tish bali", "Проходной балл"]);
    expect(ru("steps", { count: 5 })).toBe("5 шагов");
    expect(ru("points", { count: 2 })).toBe("+2 балла");
    expect(uz("streak", { count: 4 })).toBe("Ketma-ket 4 kun");
  });
});

describe("Home's training card", () => {
  it("lists the open mandatory courses, late first, and opens them", async () => {
    const { container } = renderApp(<TrainingCard member={member} summary={undefined} />, { me });
    const rows = await screen.findAllByRole("button", { name: /Sovuq zanjir|Retsept/ });
    expect(rows.map((row) => row.querySelector(".lrn-mini-title")?.textContent)).toEqual(["Retsept bo‘yicha dori berish", "Sovuq zanjir"]);
    expect(rows[0].textContent).toContain("Late since 19 Oct");
    expect(rows[1].textContent).toContain("2 of 4 steps done · Due 28 Oct");
    // The optional course stays off the card.
    expect(container.textContent).not.toContain("Kassa qoidalari");
    fireEvent.click(rows[1]);
    expect(navigationState().stack.at(-1)).toEqual({ feature: "learning", page: "course", params: { id: 4 } });
    fireEvent.click(screen.getByRole("button", { name: "All" }));
    expect(navigationState().stack.at(-1)).toEqual({ feature: "learning", page: "home", params: undefined });
  });

  it("shows at most three, and nothing when none is open", async () => {
    const many = Array.from({ length: 5 }, (_, index) => ({ ...home().todo[0], id: 40 + index, course: { ...home().todo[0].course, id: 40 + index, title: `Kurs ${index}` } }));
    serve((path) => (path.endsWith("/learning/") ? home({ todo: many }) : undefined));
    renderApp(<TrainingCard member={member} summary={undefined} />, { me });
    await waitFor(() => expect(document.querySelectorAll(".lrn-mini")).toHaveLength(3));
    cleanup();
    serve((path) => (path.endsWith("/learning/") ? home({ todo: [] }) : undefined));
    renderApp(<TrainingCard member={member} summary={undefined} />, { me });
    await waitFor(() => expect(server.calls.some((call) => call.path.endsWith("/learning/"))).toBe(true));
    await act(async () => {});
    expect(document.querySelector(".lrn-home-card")).toBeNull();
  });
});

describe("the learning home", () => {
  it("has To do, Done and Catalogue, certificates and the checks", async () => {
    serve((path) => (path.endsWith("/learning/checks/") ? [checkEntry(), checkEntry({ entry_id: 50, title: "O‘tgan hafta", due_at: "2026-10-14T05:00:00Z", done: true, passed: true })] : undefined));
    renderApp(<LearningHome />, { me });
    expect(await screen.findByText("Sovuq zanjir")).toBeTruthy();
    // Late first in the to-do list too.
    const todo = [...document.querySelectorAll(".lrn-course-title")].map((node) => node.textContent);
    expect(todo).toEqual(["Retsept bo‘yicha dori berish", "Sovuq zanjir", "Kassa qoidalari"]);
    expect(screen.getByRole("button", { name: /1 certificate/ })).toBeTruthy();

    const checks = await screen.findByText("Dushanba tekshiruvi");
    const open = checks.closest("button")!;
    expect(open.textContent).toContain("Answer by tomorrow, 10:00");
    fireEvent.click(open);
    expect(navigationState().stack.at(-1)).toEqual({ feature: "learning", page: "check", params: { id: 61 } });
    expect(screen.getByText("O‘tgan hafta").closest(".list-item")?.textContent).toContain("Passed");

    fireEvent.click(screen.getByRole("tab", { name: /Done/ }));
    expect(await screen.findByText("Yangi xodim kursi")).toBeTruthy();
    expect(screen.getByText("Finished 10 Oct")).toBeTruthy();
    expect(screen.getByRole("button", { name: /Certificate/ })).toBeTruthy();

    fireEvent.click(screen.getByRole("tab", { name: /Catalogue/ }));
    const row = await screen.findByText("Analoglar bilan ishlash");
    expect(row.closest("button")?.textContent).toContain("3 steps · 20 min");
    fireEvent.click(row.closest("button")!);
    expect(navigationState().stack.at(-1)).toEqual({ feature: "learning", page: "course", params: { id: 7 } });
  });

  it("says kindly when there is nothing", async () => {
    serve((path) => (path.endsWith("/learning/") ? home({ todo: [], done: [], catalog: [], certificates: 0 }) : undefined));
    renderApp(<LearningHome />, { me });
    expect(await screen.findByText("All caught up")).toBeTruthy();
    fireEvent.click(screen.getByRole("tab", { name: /Catalogue/ }));
    expect(screen.getByText("No other courses yet")).toBeTruthy();
  });

  it("offers Try again when the list didn't load", async () => {
    serve((path) => (path.endsWith("/learning/") ? new TypeError("Failed to fetch") : undefined));
    renderApp(<LearningHome />, { me });
    expect(await screen.findByRole("button", { name: /Try again/ })).toBeTruthy();
  });
});

describe("the course page", () => {
  const open = (detail?: CourseDetail) => {
    if (detail) serve((path) => (path.endsWith("/learning/courses/4/") ? detail : undefined));
    return renderApp(<CoursePage params={{ id: 4 }} />, { me, init: { stack: [{ feature: "learning", page: "course", params: { id: 4 } }] } });
  };

  it("shows the progress and the steps, locked, open and done, and continues with the next one", async () => {
    open();
    expect(await screen.findByRole("heading", { name: "Sovuq zanjir" })).toBeTruthy();
    expect(screen.getByText("Mandatory course")).toBeTruthy();
    expect(screen.getByText("Due 28 Oct")).toBeTruthy();
    expect(screen.getByText("2 of 4 steps done")).toBeTruthy();
    const steps = [...document.querySelectorAll(".lrn-step")];
    expect(steps.map((node) => node.className.replace(/\s+/g, " "))).toEqual([
      "lrn-step lrn-step--done",
      "lrn-step lrn-step--done",
      "lrn-step lrn-step--current",
      "lrn-step lrn-step--locked",
    ]);
    expect(steps[3].textContent).toContain("Test · 10 min · Best 60%");

    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(navigationState().stack.at(-1)).toEqual({ feature: "learning", page: "lesson", params: { id: 12, course: 4 } });
  });

  it("opens a page step in the reader, which then asks for I've read it", async () => {
    open();
    fireEvent.click(await screen.findByText("Harorat jurnali"));
    expect(navigationState().stack.at(-1)).toEqual({ feature: "knowledge", page: "page", params: { id: 5, course: 4 } });
  });

  it("keeps a locked step shut", async () => {
    open();
    fireEvent.click(await screen.findByText("Sovuq zanjir testi"));
    expect(navigationState().stack.at(-1)).toEqual({ feature: "learning", page: "course", params: { id: 4 } });
    expect(await screen.findByText("Finish the steps before this one first")).toBeTruthy();
  });

  it("starts an optional course of the person's audience", async () => {
    const detail = courseDetail({ assignment: null, can_start: true, mandatory: false });
    let started = false;
    serve((path, method) => {
      if (path.endsWith("/learning/courses/4/start/") && method === "POST") {
        started = true;
        return { ...courseDetail().assignment!, state: "assigned", percent: 0, steps_done: 0 };
      }
      if (path.endsWith("/learning/courses/4/")) return started ? courseDetail() : detail;
      return undefined;
    });
    open();
    expect(await screen.findByText("Start the course to open its steps.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Start the course" }));
    expect(await screen.findByText("The course is on your list. Good luck!")).toBeTruthy();
    expect(server.calls.some((call) => call.path === "/companies/1/learning/courses/4/start/" && call.method === "POST")).toBe(true);
  });

  it("shows the certificate of a finished course", async () => {
    open(
      courseDetail({
        assignment: { ...courseDetail().assignment!, state: "completed", percent: 100, steps_done: 4, completed_at: "2026-10-20T07:00:00Z", certificate_url: "/api/v1/files/c/" },
        steps: courseDetail().steps.map((item) => ({ ...item, done: true, locked: false })),
      }),
    );
    expect(await screen.findByText("You finished this course")).toBeTruthy();
    expect(screen.getByText("Finished 20 Oct")).toBeTruthy();
    expect(screen.getByRole("button", { name: /Certificate/ })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Continue" })).toBeNull();
  });
});

describe("the knowledge reader as a course step", () => {
  const page = {
    id: 5,
    title: "Harorat jurnali",
    emoji: "",
    space: { id: 2, name: "Qo‘llanma", icon: "" },
    parent_id: null,
    require_ack: false,
    version: 2,
    updated_at: "2026-10-20T09:00:00+05:00",
    updated_by: null,
    excerpt: "",
    body: "<p>Har kuni ikki marta yozing.</p>",
    ack_version: 2,
    breadcrumbs: [],
    children: [],
    my_ack: null,
  };

  it("asks for I've read it although the page itself doesn't", async () => {
    serve((path) => (path.endsWith("/knowledge/pages/5/") ? page : undefined));
    renderApp(<PageReader params={{ id: 5, course: 4 }} />, { me, init: { stack: [{ feature: "knowledge", page: "page", params: { id: 5, course: 4 } }] } });
    expect(await screen.findByText("Please read it to the end and confirm.")).toBeTruthy();
    expect(screen.getByRole("button", { name: /I’ve read it/ })).toBeTruthy();
    cleanup();
    renderApp(<PageReader params={{ id: 5 }} />, { me, init: { stack: [{ feature: "knowledge", page: "page", params: { id: 5 } }] } });
    expect(await screen.findByText("Har kuni ikki marta yozing.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /I’ve read it/ })).toBeNull();
  });

  it("reports the view when it opens, then while in front, and when left", async () => {
    vi.useFakeTimers({ toFake: ["Date", "setInterval", "clearInterval"] });
    vi.setSystemTime(NOW);
    serve((path) => (path.endsWith("/knowledge/pages/5/") ? page : undefined));
    const { unmount } = renderApp(<PageReader params={{ id: 5 }} />, { me, init: { stack: [{ feature: "knowledge", page: "page", params: { id: 5 } }] } });
    await screen.findByText("Har kuni ikki marta yozing.");
    const views = () => server.calls.filter((call) => call.path === "/companies/1/knowledge/pages/5/view/");
    expect(views()).toHaveLength(1);
    const opened = views()[0].body as { session: string; seconds: number; scrolled: number };
    expect(opened).toMatchObject({ seconds: 0, scrolled: 100 });
    expect(opened.session.length).toBeGreaterThan(8);

    await act(async () => {
      vi.advanceTimersByTime(15_000);
    });
    expect(views()).toHaveLength(2);
    expect(views()[1].body).toEqual({ session: opened.session, seconds: 15, scrolled: 100 });

    vi.setSystemTime(new Date(NOW.getTime() + 21_000));
    unmount();
    expect(views()).toHaveLength(3);
    expect(views()[2].body).toEqual({ session: opened.session, seconds: 6, scrolled: 100 });
  });
});
