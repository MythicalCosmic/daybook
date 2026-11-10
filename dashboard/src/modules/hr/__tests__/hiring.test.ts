// The registry first, as in the app: it is what loads every module's index.ts (see core/modules.ts).
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { confirmQueue } from "@/components/useConfirm";
import { mergeModuleMessages } from "@/i18n";
import { json } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

import { hiringApi, hiringKeys } from "../hiring/api";
import DecisionDialog from "../hiring/components/DecisionDialog.vue";
import ShareDialog from "../hiring/components/ShareDialog.vue";
import VacancyFormDialog from "../hiring/components/VacancyFormDialog.vue";
import {
  canDrop,
  cleanQuestions,
  emptyQuestion,
  formatPhone,
  highlights,
  initials,
  nextStage,
  pharmacistQuestions,
  questionProblem,
  salaryText,
  stageSegments,
  toldByDefault,
  toDrafts,
  vacancyProblem,
  vacancyState,
} from "../hiring/lib";
import HiringPage from "../hiring/pages/HiringPage.vue";
import VacancyPage from "../hiring/pages/VacancyPage.vue";
import type { Applicant, ApplicantDetail, Vacancy } from "../hiring/types";
import en from "../i18n/en.json";
import module from "../index";

interface Call {
  method: string;
  url: string;
  body: unknown;
}

/** fetch answers by URL prefix (relative to the company), recording every call. */
function stub(routes: Record<string, unknown> = {}): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init?: RequestInit) => {
      const url = input.replace("/api/v1/owner/companies/1/", "");
      calls.push({ method: init?.method ?? "GET", url, body: init?.body ? JSON.parse(String(init.body)) : undefined });
      const match = Object.keys(routes)
        .sort((a, b) => b.length - a.length)
        .find((prefix) => url.startsWith(prefix));
      return json(match ? routes[match] : {});
    }),
  );
  return calls;
}

const counts = { new: 2, screening: 1, interview: 1, offer: 0, hired: 0, rejected: 1, total: 5 };

function vacancy(overrides: Partial<Vacancy> = {}): Vacancy {
  return {
    id: 4,
    title: "Farmatsevt",
    status: "open",
    accepting: true,
    position: { id: 3, name: "Farmatsevt" },
    role: { id: 6, name: "Xodim" },
    branch: { id: 1, name: "Chilonzor", code: "CHL" },
    description: "2/2 smena",
    salary_from: "4500000.00",
    salary_to: "6000000.00",
    currency: "UZS",
    questions: [
      { id: "qa1", text: "Farmatsevtik ma’lumotingiz bormi?", kind: "yes_no", required: true, options: [] },
      { id: "qa2", text: "Qaysi smena qulay?", kind: "choice", required: true, options: ["Kunduzgi", "Tungi"] },
    ],
    asks_document: true,
    opens_on: null,
    closes_on: "2026-11-28",
    link: "https://t.me/daybook_bot?start=job_Ab3dE5fG7h",
    qr_link: "https://t.me/daybook_bot?start=job_Ab3dE5fG7h-q",
    link_opens: 47,
    counts,
    created_by: { id: 2, name: "Bekzod Mirzayev", photo_url: null },
    created_at: "2026-10-28T05:00:00Z",
    published_at: "2026-10-29T05:00:00Z",
    closed_at: null,
    hire_blocker: null,
    ...overrides,
  };
}

function applicant(overrides: Partial<Applicant> = {}): Applicant {
  return {
    id: 31,
    vacancy: { id: 4, name: "Farmatsevt" },
    name: "Dilfuza Raximova",
    phone: "+998901234401",
    telegram_username: "dilfuza_r",
    language: "uz",
    stage: "new",
    stage_changed_at: "2026-11-09T13:30:00Z",
    source: "qr",
    answers: [
      { id: "qa1", text: "Farmatsevtik ma’lumotingiz bormi?", kind: "yes_no", answer: "yes" },
      { id: "qa2", text: "Qaysi smena qulay?", kind: "choice", answer: "Kunduzgi" },
    ],
    has_document: true,
    rejected_reason: "",
    member: null,
    hired_at: null,
    created_at: "2026-11-09T13:30:00Z",
    ...overrides,
  };
}

function detail(overrides: Partial<ApplicantDetail> = {}): ApplicantDetail {
  return {
    ...applicant(),
    document: "/api/v1/files/signed-token/",
    events: [
      { id: 1, kind: "applied", from_stage: "", to_stage: "new", text: "", message: "", notified: false, by: null, created_at: "2026-11-09T13:30:00Z" },
      { id: 2, kind: "note", from_stage: "", to_stage: "", text: "Qo‘ng‘iroq qildim", message: "", notified: false, by: { id: 2, name: "Bekzod Mirzayev", photo_url: null }, created_at: "2026-11-09T14:00:00Z" },
    ],
    ...overrides,
  };
}

beforeEach(() => {
  mergeModuleMessages("hr", { en, ru: en, uz: en });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  confirmQueue.value = [];
  document.body.innerHTML = "";
});

describe("hiring rules", () => {
  it("walks the pipeline and decides what tells the applicant", () => {
    expect(["new", "screening", "interview", "offer", "hired", "rejected"].map((stage) => nextStage(stage as never))).toEqual(["screening", "interview", "offer", "hired", null, null]);
    expect(toldByDefault("interview") && toldByDefault("offer")).toBe(true);
    expect(toldByDefault("screening") || toldByDefault("new")).toBe(false);
    expect(canDrop({ stage: "new" }, "new", "rejected")).toBe(true);
    expect(canDrop({ stage: "hired" }, "hired", "offer")).toBe(false);
  });

  it("reads a vacancy's state from its status and dates", () => {
    const today = "2026-11-10";
    expect(vacancyState({ status: "open", accepting: true, opens_on: null, closes_on: "2026-11-28" }, today)).toBe("open");
    expect(vacancyState({ status: "open", accepting: false, opens_on: "2026-11-15", closes_on: null }, today)).toBe("scheduled");
    expect(vacancyState({ status: "open", accepting: false, opens_on: null, closes_on: "2026-11-09" }, today)).toBe("ended");
    expect(vacancyState({ status: "paused", accepting: false, opens_on: null, closes_on: null }, today)).toBe("paused");
  });

  it("draws the stage bar and the card's details", () => {
    expect(stageSegments(counts).map((segment) => [segment.stage, segment.count, segment.share])).toEqual([
      ["new", 2, 0.4],
      ["screening", 1, 0.2],
      ["interview", 1, 0.2],
      ["rejected", 1, 0.2],
    ]);
    expect(stageSegments({ ...counts, new: 0, screening: 0, interview: 0, rejected: 0, total: 0 })).toEqual([]);
    expect(initials("Aziza Karimova")).toBe("AK");
    expect(initials("елена ким")).toBe("ЕК");
    expect(formatPhone("+998901234401")).toBe("+998 90 123 44 01");
    expect(formatPhone("+7 912 000")).toBe("+7 912 000");
    expect(highlights([{ id: "a", text: "A", kind: "text", answer: "" }, ...applicant().answers]).map((row) => row.id)).toEqual(["qa1", "qa2"]);
    const money = (value: string, _currency: string, options?: { currencyDisplay?: "label" | "none" }) => (options?.currencyDisplay === "none" ? value : `${value} UZS`);
    const t = (key: string, values: Record<string, string>) => `${key}:${values.amount}`;
    expect(salaryText({ salary_from: "3", salary_to: "4", currency: "UZS" }, money, t)).toBe("3 – 4 UZS");
    expect(salaryText({ salary_from: "3", salary_to: null, currency: "UZS" }, money, t)).toBe("hr.hiring.salaryFrom:3 UZS");
    expect(salaryText({ salary_from: null, salary_to: null, currency: "UZS" }, money, t)).toBeNull();
  });

  it("checks the form and cleans the questions for the server", () => {
    expect(vacancyProblem({ title: " ", salary_from: null, salary_to: null, opens_on: null, closes_on: null })).toBe("title");
    expect(vacancyProblem({ title: "Kassir", salary_from: "5000000", salary_to: "3000000", opens_on: null, closes_on: null })).toBe("salary");
    expect(vacancyProblem({ title: "Kassir", salary_from: null, salary_to: null, opens_on: "2026-11-20", closes_on: "2026-11-12" })).toBe("dates");
    expect(questionProblem({ text: "", kind: "text", required: true, options: [] })).toBe("text");
    expect(questionProblem({ text: "Smena?", kind: "choice", required: true, options: ["Kunduzgi", " "] })).toBe("options");
    expect(questionProblem({ text: "Smena?", kind: "choice", required: true, options: ["Tun", "tun"] })).toBe("optionTwice");
    expect(questionProblem({ text: "Smena?", kind: "choice", required: true, options: ["Kunduzgi", "Tungi"] })).toBeNull();
    const drafts = toDrafts([...vacancy().questions, { text: " Yangi ", kind: "text", required: false, options: ["x"] }]);
    expect(new Set(drafts.map((draft) => draft.key)).size).toBe(3);
    expect(cleanQuestions(drafts)).toEqual([
      { id: "qa1", text: "Farmatsevtik ma’lumotingiz bormi?", kind: "yes_no", required: true, options: [] },
      { id: "qa2", text: "Qaysi smena qulay?", kind: "choice", required: true, options: ["Kunduzgi", "Tungi"] },
      { text: "Yangi", kind: "text", required: false, options: [] },
    ]);
    expect(emptyQuestion("choice").options).toEqual(["", ""]);
    const suggested = pharmacistQuestions((key) => key);
    expect(suggested.map((question) => question.kind)).toEqual(["yes_no", "yes_no", "number", "choice", "text"]);
    expect(suggested.every((question) => questionProblem(question) === null)).toBe(true);
  });
});

describe("api and registration", () => {
  it("calls the hiring endpoints", async () => {
    const calls = stub();
    await hiringApi.vacancies(1);
    await hiringApi.createVacancy(1, { title: "Kassir", position_id: null, branch_id: 1, description: "", salary_from: null, salary_to: null, questions: [], asks_document: false, opens_on: null, closes_on: null, publish: true });
    await hiringApi.updateVacancy(1, 4, { title: "Katta kassir" });
    await hiringApi.setStatus(1, 4, "pause");
    await hiringApi.removeVacancy(1, 5);
    await hiringApi.applicants(1, { vacancy: [4], page_size: 500 });
    await hiringApi.applicant(1, 31);
    await hiringApi.move(1, 31, { stage: "interview", message: "Payshanba 10:00" });
    await hiringApi.reject(1, 32, { reason: "Tajriba kam", notify: false });
    await hiringApi.hire(1, 31, { message: "Dushanba 09:00" });
    await hiringApi.note(1, 31, "Keldi");
    expect(calls.map((c) => `${c.method} ${c.url}`)).toEqual([
      "GET hr/vacancies/?page_size=100",
      "POST hr/vacancies/",
      "PATCH hr/vacancies/4/",
      "POST hr/vacancies/4/pause/",
      "DELETE hr/vacancies/5/",
      "GET hr/applicants/?vacancy=4&page_size=500",
      "GET hr/applicants/31/",
      "POST hr/applicants/31/move/",
      "POST hr/applicants/32/reject/",
      "POST hr/applicants/31/hire/",
      "POST hr/applicants/31/notes/",
    ]);
    expect(calls[7]!.body).toEqual({ stage: "interview", message: "Payshanba 10:00" });
    expect(calls[10]!.body).toEqual({ text: "Keldi" });
    expect(hiringKeys.applicants(1, { vacancy: [4] })).toEqual([1, "hr", "hiring-applicants", { vacancy: [4] }]);
  });

  it("puts hiring in the sidebar with its badge, its two pages and a palette action", () => {
    const hiring = module.nav?.find((item) => item.key === "hiring");
    expect(hiring?.badge?.({ counters: { "hr.applicants": 3, "hr.expiring": 9 }, versions: {} })).toBe(3);
    const routes = module.routes.filter((route) => String(route.path).startsWith("hr/hiring"));
    expect(routes.map((route) => [route.path, route.name, route.meta?.perm])).toEqual([
      ["hr/hiring", "hr.hiring", "hr.hiring"],
      ["hr/hiring/:vacancyId(\\d+)", "hr.vacancy", "hr.hiring"],
    ]);
    expect(module.deepLinks?.vacancy?.("4")).toBe("hr/hiring/4");
    expect(Object.keys(en).some((key) => key.startsWith("hr.soon.hiring"))).toBe(false);
  });
});

describe("Hiring page", () => {
  it("shows the vacancies working ones first, with what waits and the numbers on top", async () => {
    stub({ "hr/vacancies/": { count: 2, next: null, previous: null, results: [vacancy(), vacancy({ id: 5, title: "Kuryer", status: "draft", accepting: false, counts: { new: 0, screening: 0, interview: 0, offer: 0, hired: 0, rejected: 0, total: 0 }, link_opens: 0 })] } });
    const app = await testApp("/c/1/hr/hiring");
    const { wrapper } = mountWithProviders(HiringPage, { plugins: app.plugins });
    await flushPromises();
    await flushPromises();
    const cards = wrapper.findAll("[data-vacancy-card]");
    expect(cards).toHaveLength(1); // the draft waits in its own tab
    expect(cards[0]!.text()).toContain("Farmatsevt");
    expect(cards[0]!.find("[data-new-count]").text()).toContain("2");
    expect(cards[0]!.find("[data-stage-bar]").text()).toContain("Screening");
    expect(wrapper.text()).toContain(en["hr.hiring.kpi.new"]);
    const draftsTab = wrapper.findAll("[data-tab]").find((tab) => tab.text().includes(en["hr.hiring.tab.drafts"]));
    await draftsTab!.trigger("click");
    await flushPromises();
    expect(wrapper.findAll("[data-vacancy-card]").map((card) => card.text())).toEqual([expect.stringContaining("Kuryer")]);
  });

  it("explains the steps when there is no vacancy yet", async () => {
    stub({ "hr/vacancies/": { count: 0, next: null, previous: null, results: [] } });
    const app = await testApp("/c/1/hr/hiring");
    const { wrapper } = mountWithProviders(HiringPage, { plugins: app.plugins });
    await flushPromises();
    await flushPromises();
    const empty = wrapper.find("[data-hiring-empty]");
    expect(empty.text()).toContain(en["hr.hiring.empty.step2"]);
    expect(empty.findAll("li")).toHaveLength(4);
  });
});

describe("Vacancy page", () => {
  async function mountVacancy(routes: Record<string, unknown>, query = "") {
    const calls = stub(routes);
    const app = await testApp("/c/1/hr/hiring");
    app.router.addRoute({ path: "/c/:companyId/hr/hiring/:vacancyId", name: "hr.vacancy", component: { render: () => null } });
    await app.router.push(`/c/1/hr/hiring/4${query}`);
    const { wrapper } = mountWithProviders(VacancyPage, { plugins: app.plugins });
    await flushPromises();
    await flushPromises();
    return { wrapper, calls, app };
  }

  const board = () => ({
    "hr/vacancies/4/": vacancy(),
    "hr/applicants/?": {
      count: 3,
      next: null,
      previous: null,
      results: [applicant(), applicant({ id: 32, name: "Sanjar Qosimov", stage: "interview", source: "link", has_document: false }), applicant({ id: 33, name: "Ulug‘bek Hamroyev", stage: "rejected", rejected_reason: "Diplom yo‘q" })],
    },
    "hr/applicants/31/": detail(),
  });

  it("lays the applicants out by stage, with their answers on the cards", async () => {
    const { wrapper, calls } = await mountVacancy(board());
    expect(calls.some((c) => c.url === "hr/applicants/?vacancy=4&page_size=500")).toBe(true);
    const column = (stage: string) => wrapper.find(`[data-column="${stage}"]`);
    expect(column("new").text()).toContain("Dilfuza Raximova");
    expect(column("new").text()).toContain("Kunduzgi");
    expect(column("interview").text()).toContain("Sanjar Qosimov");
    // The turned-down column waits behind its toggle, so the pipeline fits the page.
    expect(column("rejected").exists()).toBe(false);
    await wrapper.find("[data-toggle-rejected]").trigger("click");
    await flushPromises();
    expect(column("rejected").text()).toContain("Diplom yo‘q");
    expect(wrapper.text()).toContain("47"); // the link's openings
  });

  it("opens the applicant's panel with answers, the diploma photo and the history", async () => {
    const { wrapper } = await mountVacancy(board(), "?applicant=31");
    const panel = document.body.querySelector("[data-applicant-drawer]");
    expect(panel?.textContent).toContain("+998 90 123 44 01");
    expect(panel?.querySelector("[data-answers]")?.textContent).toContain("Kunduzgi");
    expect(panel?.querySelector("[data-document] img")?.getAttribute("src")).toBe("/api/v1/files/signed-token/");
    expect(panel?.querySelector("[data-history]")?.textContent).toContain("Qo‘ng‘iroq qildim");
    expect(document.body.querySelector("[data-hire]")?.hasAttribute("disabled")).toBe(false);
    wrapper.unmount();
  });

  it("can't hire where the hirer may not give the position's access", async () => {
    const routes = { ...board(), "hr/vacancies/4/": vacancy({ hire_blocker: "Ask an owner to hire." }) };
    await mountVacancy(routes, "?applicant=31");
    expect(document.body.querySelector("[data-hire]")?.hasAttribute("disabled")).toBe(true);
    expect(document.body.querySelector("[data-hire-blocker]")?.textContent).toContain("Ask an owner");
  });
});

describe("dialogs", () => {
  it("asks for a reason before turning someone down, and tells them only if wanted", async () => {
    const calls = stub({ "hr/applicants/32/reject/": detail({ id: 32, stage: "rejected" }) });
    const app = await testApp("/c/1/hr/hiring/4");
    const { wrapper, inner } = mountWithProviders(DecisionDialog, { plugins: app.plugins, props: { decision: { mode: "reject", applicant: { id: 32, name: "Sanjar Qosimov", stage: "interview" } }, vacancy: vacancy() } });
    await flushPromises();
    const decide = () => (document.body.querySelector("[data-decide]") as HTMLButtonElement).click();
    decide();
    await flushPromises();
    expect(document.body.querySelector("[data-decision-error]")?.textContent).toContain(en["hr.hiring.decide.reasonRequired"]);
    (document.body.querySelector("[data-reason-chips] button") as HTMLButtonElement).click();
    await flushPromises();
    (document.body.querySelector("[data-notify] [role='switch']") as HTMLButtonElement).click();
    await flushPromises();
    decide();
    await flushPromises();
    const sent = calls.find((c) => c.url === "hr/applicants/32/reject/");
    expect(sent?.body).toEqual({ reason: en["hr.hiring.reason.experience"], message: "", notify: false });
    expect(inner.emitted("done")).toHaveLength(1);
    wrapper.unmount();
  });

  it("invites to an interview with the message, told by default", async () => {
    const calls = stub({ "hr/applicants/31/move/": detail({ stage: "interview" }) });
    const app = await testApp("/c/1/hr/hiring/4");
    mountWithProviders(DecisionDialog, { plugins: app.plugins, props: { decision: { mode: "move", applicant: { id: 31, name: "Dilfuza Raximova", stage: "screening" }, stage: "interview" }, vacancy: vacancy() } });
    await flushPromises();
    const area = document.body.querySelector("[data-notify] textarea") as HTMLTextAreaElement;
    area.value = "Payshanba 10:00, Chilonzor";
    area.dispatchEvent(new Event("input"));
    await flushPromises();
    (document.body.querySelector("[data-decide]") as HTMLButtonElement).click();
    await flushPromises();
    expect(calls.find((c) => c.url === "hr/applicants/31/move/")?.body).toEqual({ stage: "interview", message: "Payshanba 10:00, Chilonzor", notify: true });
  });

  it("shares the link and the QR code, or says the bot isn't connected", async () => {
    stub();
    const app = await testApp("/c/1/hr/hiring");
    const { wrapper } = mountWithProviders(ShareDialog, { plugins: app.plugins, props: { open: true, vacancy: vacancy() } });
    await flushPromises();
    expect(document.body.querySelector("[data-share-link]")?.textContent).toBe("https://t.me/daybook_bot?start=job_Ab3dE5fG7h");
    expect(document.body.querySelector("[data-share-closed]")).toBeNull();
    wrapper.unmount();
    mountWithProviders(ShareDialog, { plugins: app.plugins, props: { open: true, vacancy: vacancy({ link: "", qr_link: "" }) } });
    await flushPromises();
    expect(document.body.textContent).toContain(en["hr.hiring.share.noBot"]);
  });

  it("checks the vacancy form, then publishes with the questions cleaned", async () => {
    const calls = stub({ "hr/vacancies/": vacancy({ id: 9 }), "positions/": [] });
    const app = await testApp("/c/1/hr/hiring");
    const { inner } = mountWithProviders(VacancyFormDialog, { plugins: app.plugins, props: { open: true } });
    await flushPromises();
    const publish = () => (document.body.querySelector("[data-publish]") as HTMLButtonElement).click();
    publish();
    await flushPromises();
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(0);
    expect(document.body.textContent).toContain(en["hr.hiring.problem.title"]);

    const title = document.body.querySelector("[data-vacancy-form] input") as HTMLInputElement;
    title.value = "Farmatsevt";
    title.dispatchEvent(new Event("input"));
    (document.body.querySelector("[data-suggest]") as HTMLButtonElement).click();
    await flushPromises();
    expect(document.body.querySelectorAll("[data-question]")).toHaveLength(5);
    publish();
    await flushPromises();
    const sent = calls.find((c) => c.method === "POST" && c.url === "hr/vacancies/");
    expect(sent?.body).toMatchObject({ title: "Farmatsevt", branch_id: 1, asks_document: true, publish: true });
    const questions = (sent?.body as { questions: Array<{ kind: string }> }).questions;
    expect(questions.map((question) => question.kind)).toEqual(["yes_no", "yes_no", "number", "choice", "text"]);
    expect(questions.every((question) => !("key" in question))).toBe(true);
    expect(inner.emitted("saved")?.[0]).toEqual([expect.objectContaining({ id: 9 }), true]);
  });
});
