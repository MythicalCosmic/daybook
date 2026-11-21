// Unchangeable lists (O‘zgarmas ro‘yxatlar) against a stubbed API: the cell logic (the line a cell
// holds, its history, corrections either way round), the progress counts and the journal; the lists
// page (rows, the state filter, the empty state, a new list that opens); one list (the grid, the
// integrity line, writing a line, reading and correcting one, sealing, a sealed list, the journal,
// print) and what a viewer without `learning.manage` can do.
import "@/core/modules";

import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query";
import { flushPromises } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createMemoryHistory, createRouter, type RouteRecordRaw } from "vue-router";

import { confirmQueue, settleConfirm } from "@/components/useConfirm";
import { i18n, mergeModuleMessages, setLanguage } from "@/i18n";
import { todayIn } from "@/lib/dates";
import { useCompanyStore } from "@/stores/company";
import { useSessionStore } from "@/stores/session";
import { company, json, manager, me } from "@/test/fixtures";
import { mountWithProviders as mountRaw } from "@/test/plugins";

import en from "../i18n/en.json";
import { cellHistory, cellKey, cellsOf, dayMonth, dottedDay, journalOf, parseTitles, percentOf, progressOf, shortDigest, shortName, standingLine, stateCounts } from "../lists";
import ListPage from "../pages/ListPage.vue";
import ListsPage from "../pages/ListsPage.vue";
import { routes } from "../routes";
import type { StudyListDetail, StudyListRow, StudyMark, StudyStudent, StudyTopic } from "../types";

vi.setConfig({ testTimeout: 20_000 });

const mounted: Array<{ unmount: () => void }> = [];
const mountWithProviders: typeof mountRaw = (component, options) => {
  const result = mountRaw(component, options);
  mounted.push(result.wrapper);
  return result;
};

interface Call {
  method: string;
  path: string;
  body: unknown;
}

class NoResize {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

function stub(routesByCall: Record<string, (call: Call) => Response>): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal("ResizeObserver", NoResize);
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const path = url.replace(/^.*\/api\/v1\/owner\/companies\/1\//, "").split("?")[0]!;
      const body = init?.body && typeof init.body === "string" ? JSON.parse(init.body) : undefined;
      const call = { method: init?.method ?? "GET", path, body };
      calls.push(call);
      return routesByCall[`${call.method} ${path}`]?.(call) ?? json([], 200);
    }),
  );
  return calls;
}

async function settle(): Promise<void> {
  for (let i = 0; i < 8; i += 1) await flushPromises();
}

async function pageApp(path: string, perms: "owner" | "viewer" = "owner") {
  const pinia = createPinia();
  setActivePinia(pinia);
  const current = perms === "owner" ? company({ features: ["learning"] }) : manager(["learning.view"], { id: 1, features: ["learning"] });
  useSessionStore().me = me([current]);
  useCompanyStore().setCurrent(1);
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/c/:companyId", children: routes.map((route) => ({ ...route, component: { render: () => null } }) as RouteRecordRaw) },
      { path: "/:any(.*)*", component: { render: () => null } },
    ],
  });
  await router.push(path);
  setLanguage("en");
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return { router, plugins: [pinia, router, i18n, [VueQueryPlugin, { queryClient: client }]] as never };
}

beforeEach(() => {
  mergeModuleMessages("learning", { en, ru: en, uz: en });
  localStorage.clear();
  confirmQueue.value = [];
});

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  document.body.innerHTML = "";
});

const body = () => document.body;
const inBody = <T extends Element = HTMLElement>(selector: string) => body().querySelector<T>(selector);
function type(element: HTMLInputElement | HTMLTextAreaElement | null, value: string): void {
  if (!element) throw new Error("no field");
  element.value = value;
  element.dispatchEvent(new Event("input", { bubbles: true }));
}

// The fixture: three topics, two students, five lines; line 1 was taken back by line 3 and the
// cell written anew by line 4.
const topic = (id: number, number: number, title: string, locked = false): StudyTopic => ({ id, number, title, locked });
const student = (id: number, number: number, name: string, extra: Partial<StudyStudent> = {}): StudyStudent => ({
  id,
  number,
  name,
  note: "",
  member_id: null,
  position: null,
  locked: false,
  ...extra,
});
const mark = (fields: Partial<StudyMark> & Pick<StudyMark, "id" | "number" | "topic_id" | "student_id">): StudyMark => ({
  kind: "studied",
  studied_on: "2026-11-18",
  note: "",
  corrects_id: null,
  corrected_by_id: null,
  written_by: "Dilnoza Karimova",
  written_at: "2026-11-18T09:00:00Z",
  digest: `${String(fields.number).padStart(2, "0")}${"c0ffee".repeat(10)}ab`,
  ...fields,
});
const SEAL = "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08";
const REASON = "Boshqa o‘quvchi belgilangan";

const marks = (): StudyMark[] => [
  mark({ id: 101, number: 1, topic_id: 1, student_id: 11, corrected_by_id: 103 }),
  mark({ id: 102, number: 2, topic_id: 1, student_id: 12 }),
  mark({ id: 103, number: 3, kind: "correction", topic_id: 1, student_id: 11, studied_on: null, note: REASON, corrects_id: 101, written_at: "2026-11-18T09:20:00Z" }),
  mark({ id: 104, number: 4, topic_id: 1, student_id: 11, studied_on: "2026-11-19", written_at: "2026-11-19T08:00:00Z" }),
  mark({ id: 105, number: 5, topic_id: 2, student_id: 12, studied_on: "2026-11-20", written_by: "Nodira Rahimova", written_at: "2026-11-20T08:00:00Z" }),
];

const detail = (overrides: Partial<StudyListDetail> = {}): StudyListDetail => ({
  id: 7,
  title: "Amaliyotchilar, noyabr",
  description: "",
  teacher: "Nodira Rahimova",
  branch: { id: 1, name: "Chilonzor" },
  state: "open",
  created_at: "2026-11-17T05:00:00Z",
  created_by: "Dilnoza Karimova",
  sealed_at: null,
  sealed_by: "",
  seal_digest: "",
  intact: true,
  topics: [topic(1, 1, "Tovarni qabul qilish", true), topic(2, 2, "Sovuq zanjir", true), topic(3, 3, "Kassa intizomi")],
  students: [student(11, 1, "Alisher Valiyev", { member_id: 3, position: "Farmatsevt", locked: true }), student(12, 2, "Madina Saidova", { note: "intern, pharmacy college", locked: true })],
  marks: marks(),
  ...overrides,
});

const row = (overrides: Partial<StudyListRow> = {}): StudyListRow => ({
  id: 7,
  title: "Amaliyotchilar, noyabr",
  teacher: "Nodira Rahimova",
  branch: { id: 1, name: "Chilonzor" },
  state: "open",
  topics: 3,
  students: 2,
  studied: 3,
  cells: 6,
  created_at: "2026-11-17T05:00:00Z",
  sealed_at: null,
  ...overrides,
});

describe("the cells of a list", () => {
  it("hold their latest line that no correction took back, with every line in the history", () => {
    const lines = marks();
    expect(standingLine(lines, 1, 11)?.number).toBe(4);
    expect(cellHistory(lines, 1, 11).map((line) => line.number)).toEqual([1, 3, 4]);
    expect(standingLine(lines, 1, 12)?.number).toBe(2);
    expect(cellHistory(lines, 1, 12).map((line) => line.number)).toEqual([2]);
    expect(standingLine(lines, 3, 11)).toBeNull();
    expect(cellHistory(lines, 3, 11)).toEqual([]);
    const cells = cellsOf(lines);
    expect(cells.get(cellKey(1, 11))?.corrected).toBe(true);
    expect(cells.get(cellKey(1, 12))?.corrected).toBe(false);
    // Lines out of order still read oldest first.
    expect(cellHistory([...lines].reverse(), 1, 11).map((line) => line.number)).toEqual([1, 3, 4]);
  });

  it("are empty again once their only line is corrected, whichever line says so", () => {
    const byLine = [
      mark({ id: 1, number: 1, topic_id: 1, student_id: 11, corrected_by_id: 2 }),
      mark({ id: 2, number: 2, kind: "correction", topic_id: 1, student_id: 11, studied_on: null, corrects_id: 1, note: REASON }),
    ];
    expect(standingLine(byLine, 1, 11)).toBeNull();
    expect(cellHistory(byLine, 1, 11).map((line) => line.number)).toEqual([1, 2]);
    // Only the correction names it (and carries other ids): it still sits in that cell.
    const byCorrection = [
      mark({ id: 1, number: 1, topic_id: 1, student_id: 11 }),
      mark({ id: 2, number: 2, kind: "correction", topic_id: 9, student_id: 99, studied_on: null, corrects_id: 1, note: REASON }),
    ];
    expect(standingLine(byCorrection, 1, 11)).toBeNull();
    expect(cellHistory(byCorrection, 1, 11).map((line) => line.number)).toEqual([1, 2]);
    expect(cellsOf(byCorrection).get(cellKey(1, 11))?.corrected).toBe(true);
  });

  it("count the progress overall, per topic and per student", () => {
    const progress = progressOf(detail());
    expect(progress).toMatchObject({ studied: 3, cells: 6, percent: 50 });
    expect(progress.byTopic).toEqual({ 1: 2, 2: 1, 3: 0 });
    expect(progress.byStudent).toEqual({ 11: 1, 12: 2 });
    expect(progressOf({ topics: [], students: [], marks: [] })).toMatchObject({ studied: 0, cells: 0, percent: 0 });
    expect(percentOf(199, 200)).toBe(99);
    expect(percentOf(200, 200)).toBe(100);
    expect(percentOf(0, 0)).toBe(0);
  });

  it("read as a journal in order, each line with what it points at", () => {
    const lines = journalOf(detail());
    expect(lines.map((line) => line.mark.number)).toEqual([1, 2, 3, 4, 5]);
    expect(lines[0]!.correctedBy?.number).toBe(3);
    expect(lines[2]!.corrects?.number).toBe(1);
    expect(lines[2]!.student?.name).toBe("Alisher Valiyev");
    expect(lines[2]!.topic?.title).toBe("Tovarni qabul qilish");
    expect(lines[3]!.correctedBy).toBeNull();
  });

  it("read topics one per line and write days, names and digests short", () => {
    expect(parseTitles("1. Sovuq zanjir\n\n  - Tovarni   qabul qilish \r\n• Kassa\n2) Retsept\n")).toEqual(["Sovuq zanjir", "Tovarni qabul qilish", "Kassa", "Retsept"]);
    expect(shortName("Dilnoza Karimova")).toBe("Dilnoza K.");
    expect(shortName(" Nodira ")).toBe("Nodira");
    expect(dayMonth("2026-11-08")).toBe("08.11");
    expect(dottedDay("2026-11-08")).toBe("08.11.2026");
    expect(shortDigest(SEAL, 12)).toBe("9f86d081884c");
    expect(stateCounts([{ state: "open" }, { state: "sealed" }, { state: "open" }])).toEqual({ open: 2, sealed: 1, all: 3 });
  });
});

describe("the lists page", () => {
  it("shows each list with its teacher, size, progress and state, and filters by state", async () => {
    const calls = stub({
      "GET learning/lists/": () => json([row(), row({ id: 8, title: "Kassa intizomi", teacher: "", branch: null, state: "sealed", studied: 6, sealed_at: "2026-11-20T10:00:00Z" })]),
    });
    const app = await pageApp("/c/1/learning/lists");
    const { wrapper } = mountWithProviders(ListsPage, { plugins: app.plugins });
    await settle();
    const text = wrapper.text();
    expect(text).toContain("Amaliyotchilar, noyabr");
    expect(text).toContain("Nodira Rahimova · Chilonzor");
    expect(text).toContain("3 topics");
    expect(text).toContain("2 students");
    expect(text).toContain("3/6");
    expect(text).toContain(en["learning.lists.state.sealed"]);
    expect(wrapper.find('[data-testid="lists-new"]').exists()).toBe(true);
    // The state is picked on the page, so every row comes once and the filter counts them.
    expect(calls.filter((call) => call.path === "learning/lists/")).toHaveLength(1);

    await app.router.push("/c/1/learning/lists?state=sealed");
    await settle();
    expect(wrapper.text()).toContain("Kassa intizomi");
    expect(wrapper.text()).not.toContain("Amaliyotchilar, noyabr");
  });

  it("explains the idea when there are no lists yet", async () => {
    stub({ "GET learning/lists/": () => json([]) });
    const app = await pageApp("/c/1/learning/lists");
    const { wrapper } = mountWithProviders(ListsPage, { plugins: app.plugins });
    await settle();
    expect(wrapper.text()).toContain(en["learning.lists.emptyTitle"]);
    expect(wrapper.text()).toContain(en["learning.lists.emptyBody"]);
  });

  it("asks for a title, creates the list and opens it", async () => {
    const calls = stub({
      "GET learning/lists/": () => json([]),
      "POST learning/lists/": () => json(detail({ topics: [], students: [], marks: [] }), 201),
    });
    const app = await pageApp("/c/1/learning/lists?new=1");
    mountWithProviders(ListsPage, { plugins: app.plugins });
    await settle();
    expect((inBody<HTMLButtonElement>('[data-testid="list-save"]'))?.disabled).toBe(true);
    type(inBody('[data-testid="list-form"] input'), "  Amaliyotchilar, noyabr ");
    await settle();
    inBody<HTMLButtonElement>('[data-testid="list-save"]')!.click();
    await settle();
    expect(calls.find((call) => call.method === "POST" && call.path === "learning/lists/")?.body).toEqual({
      title: "Amaliyotchilar, noyabr",
      teacher: "",
      branch_id: null,
      description: "",
    });
    expect(app.router.currentRoute.value.path).toBe("/c/1/learning/lists/7");
  });

  it("offers no New list to someone who may only look", async () => {
    stub({ "GET learning/lists/": () => json([row()]) });
    const app = await pageApp("/c/1/learning/lists", "viewer");
    const { wrapper } = mountWithProviders(ListsPage, { plugins: app.plugins });
    await settle();
    expect(wrapper.text()).toContain("Amaliyotchilar, noyabr");
    expect(wrapper.find('[data-testid="lists-new"]').exists()).toBe(false);
  });
});

describe("one list", () => {
  it("shows the grid with each line's day and who wrote it, the corrected cell's marker and the integrity line", async () => {
    stub({ "GET learning/lists/7/": () => json(detail()) });
    const app = await pageApp("/c/1/learning/lists/7");
    const { wrapper } = mountWithProviders(ListPage, { plugins: app.plugins });
    await settle();
    const text = wrapper.text();
    expect(text).toContain("Amaliyotchilar, noyabr");
    expect(text).toContain("Teacher: Nodira Rahimova");
    expect(text).toContain("Chilonzor");
    expect(text).toContain("All 5 lines intact");
    expect(text).toContain("3 of 6 · 50%");
    expect(text).toContain("intern, pharmacy college");
    const held = wrapper.find('[data-cell="1:11"]');
    expect(held.text()).toContain("19.11");
    expect(held.text()).toContain("Dilnoza K.");
    expect(held.find("[data-corrected]").exists()).toBe(true);
    expect(wrapper.find('[data-cell="1:12"] [data-corrected]').exists()).toBe(false);
    // An empty cell is ready to be written; the actions are there while the list is open.
    expect(wrapper.find('[data-cell="3:11"]').exists()).toBe(true);
    for (const action of ["list-add-topics", "list-add-students", "list-seal", "list-print"]) expect(wrapper.find(`[data-testid="${action}"]`).exists()).toBe(true);
  });

  it("warns that a line stays for good and writes it for today", async () => {
    let shown = detail();
    const calls = stub({
      "GET learning/lists/7/": () => json(shown),
      "POST learning/lists/7/marks/": (call) => {
        const sent = call.body as { topic_id: number; student_id: number; studied_on: string };
        shown = { ...shown, marks: [...shown.marks, mark({ id: 106, number: 6, topic_id: sent.topic_id, student_id: sent.student_id, studied_on: sent.studied_on })] };
        return json(shown);
      },
    });
    const app = await pageApp("/c/1/learning/lists/7");
    const { wrapper } = mountWithProviders(ListPage, { plugins: app.plugins });
    await settle();
    await wrapper.find('[data-cell="3:11"]').trigger("click");
    await settle();
    const dialog = inBody('[data-testid="cell-dialog"]')!;
    expect(dialog.textContent).toContain(en["learning.lists.mark.warning"]);
    expect(dialog.textContent).toContain("Alisher Valiyev");
    expect(dialog.textContent).toContain("Kassa intizomi");
    inBody<HTMLButtonElement>('[data-testid="mark-write"]')!.click();
    await settle();
    const today = todayIn("Asia/Tashkent");
    expect(calls.find((call) => call.method === "POST" && call.path === "learning/lists/7/marks/")?.body).toEqual({ topic_id: 3, student_id: 11, studied_on: today });
    expect(wrapper.find('[data-cell="3:11"]').text()).toContain(dayMonth(today));
  });

  it("shows a line with its history and corrects it only with a reason", async () => {
    const calls = stub({
      "GET learning/lists/7/": () => json(detail()),
      "POST learning/lists/7/marks/104/correct/": () => json(detail()),
    });
    const app = await pageApp("/c/1/learning/lists/7");
    const { wrapper } = mountWithProviders(ListPage, { plugins: app.plugins });
    await settle();
    await wrapper.find('[data-cell="1:11"]').trigger("click");
    await settle();
    expect(inBody('[role="dialog"]')?.textContent).toContain("Line #4");
    const history = inBody('[data-testid="cell-history"]')!;
    expect(history.textContent).toContain(REASON);
    expect(history.textContent).toContain("Takes back #1");
    expect(history.querySelectorAll("[data-struck]")).toHaveLength(1);

    inBody<HTMLButtonElement>('[data-testid="cell-correct"]')!.click();
    await settle();
    const confirmButton = () => inBody<HTMLButtonElement>('[data-testid="correct-confirm"]')!;
    expect(confirmButton().disabled).toBe(true);
    type(inBody<HTMLTextAreaElement>('[data-testid="correct-form"] textarea'), "Noto‘g‘ri kun yozilgan");
    await settle();
    expect(confirmButton().disabled).toBe(false);
    confirmButton().click();
    await settle();
    expect(calls.find((call) => call.method === "POST" && call.path === "learning/lists/7/marks/104/correct/")?.body).toEqual({ reason: "Noto‘g‘ri kun yozilgan" });
  });

  it("seals only after a confirm that says it is final", async () => {
    const calls = stub({
      "GET learning/lists/7/": () => json(detail()),
      "POST learning/lists/7/seal/": () => json(detail({ state: "sealed", sealed_at: "2026-11-21T06:00:00Z", sealed_by: "Dilnoza Karimova", seal_digest: SEAL })),
    });
    const app = await pageApp("/c/1/learning/lists/7");
    const { wrapper } = mountWithProviders(ListPage, { plugins: app.plugins });
    await settle();
    await wrapper.find('[data-testid="list-seal"]').trigger("click");
    await settle();
    expect(confirmQueue.value).toHaveLength(1);
    const entry = confirmQueue.value[0]!;
    expect(entry.request.message).toBe(en["learning.lists.sealBody"]);
    expect(calls.some((call) => call.path === "learning/lists/7/seal/")).toBe(false);
    await entry.request.onConfirm?.("");
    settleConfirm(entry.id, { reason: "" }, 0);
    await settle();
    expect(calls.some((call) => call.method === "POST" && call.path === "learning/lists/7/seal/")).toBe(true);
    expect(wrapper.find('[data-testid="list-seal-line"]').text()).toContain("9f86d081884c");
    expect(wrapper.find('[data-testid="list-seal"]').exists()).toBe(false);
  });

  it("a sealed list says who sealed it with the seal's start, prints the whole seal and takes no new lines", async () => {
    stub({ "GET learning/lists/7/": () => json(detail({ state: "sealed", sealed_at: "2026-11-20T10:00:00Z", sealed_by: "Dilnoza Karimova", seal_digest: SEAL })) });
    const app = await pageApp("/c/1/learning/lists/7");
    const { wrapper } = mountWithProviders(ListPage, { plugins: app.plugins });
    await settle();
    const seal = wrapper.find('[data-testid="list-seal-line"]').text();
    expect(seal).toContain("Sealed by Dilnoza Karimova");
    expect(seal).toContain("9f86d081884c");
    expect(seal).not.toContain(SEAL);
    for (const action of ["list-add-topics", "list-add-students", "list-seal", "list-more"]) expect(wrapper.find(`[data-testid="${action}"]`).exists()).toBe(false);
    expect(wrapper.find('[data-cell="3:11"]').exists()).toBe(false);
    // A held cell still opens to be read.
    expect(wrapper.find('[data-cell="1:11"]').exists()).toBe(true);

    const sheet = inBody(".study-list-print")!;
    expect(sheet.textContent).toContain(SEAL);
    expect(sheet.textContent).toContain(REASON);
    expect(sheet.textContent).toContain("19.11.2026");
    const print = vi.spyOn(window, "print").mockImplementation(() => undefined);
    await wrapper.find('[data-testid="list-print"]').trigger("click");
    expect(print).toHaveBeenCalledTimes(1);
  });

  it("warns when the chain of lines doesn't check out", async () => {
    stub({ "GET learning/lists/7/": () => json(detail({ intact: false })) });
    const app = await pageApp("/c/1/learning/lists/7");
    const { wrapper } = mountWithProviders(ListPage, { plugins: app.plugins });
    await settle();
    expect(wrapper.text()).toContain(en["learning.lists.brokenTitle"]);
    expect(wrapper.text()).not.toContain("All 5 lines intact");
  });

  it("reads as a journal: every line in order, the corrected one pointing at its correction", async () => {
    stub({ "GET learning/lists/7/": () => json(detail()) });
    const app = await pageApp("/c/1/learning/lists/7");
    const { wrapper } = mountWithProviders(ListPage, { plugins: app.plugins });
    await settle();
    const tab = wrapper.findAll("button").find((button) => button.text().includes(en["learning.lists.tabJournal"]));
    await tab!.trigger("click");
    await settle();
    const journal = wrapper.find('[data-testid="list-journal"]').text();
    for (const n of [1, 2, 3, 4, 5]) expect(journal).toContain(`#${n}`);
    expect(journal).toContain("Corrected by #3");
    expect(journal).toContain("Takes back #1");
    expect(journal).toContain(REASON);
    expect(journal).toContain(marks()[3]!.digest.slice(0, 8));
  });

  it("lets someone who may only look read lines but not write them", async () => {
    stub({ "GET learning/lists/7/": () => json(detail()) });
    const app = await pageApp("/c/1/learning/lists/7", "viewer");
    const { wrapper } = mountWithProviders(ListPage, { plugins: app.plugins });
    await settle();
    expect(wrapper.find('[data-cell="3:11"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="list-seal"]').exists()).toBe(false);
    await wrapper.find('[data-cell="1:11"]').trigger("click");
    await settle();
    expect(inBody('[data-testid="cell-line"]')).not.toBeNull();
    expect(inBody('[data-testid="cell-correct"]')).toBeNull();
  });
});
