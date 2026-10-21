// The registry first, as in the app: it is what loads every module's index.ts (see core/modules.ts).
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import KanbanBoard from "@/components/KanbanBoard.vue";
import { toasts } from "@/components/useToast";
import { mergeModuleMessages } from "@/i18n";
import { json } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

import { applyMove, createCard, listProjects, logTime, moveCard, projectKeys, scheduleCard } from "../api";
import BoardTab from "../components/BoardTab.vue";
import ProjectCard from "../components/ProjectCard.vue";
import en from "../i18n/en.json";
import { declutterMilestones, dropPosition, dueState, hhmm, parseDuration } from "../lib";
import ProjectsPage from "../pages/ProjectsPage.vue";
import type { Board, Card, ProjectDetail, ProjectItem } from "../types";

interface Call {
  method: string;
  url: string;
  body: unknown;
}

function stubApi(routes: Record<string, (call: Call) => Response | Promise<Response>>): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init?: RequestInit) => {
      const body = init?.body && typeof init.body === "string" ? JSON.parse(init.body) : undefined;
      const call = { method: init?.method ?? "GET", url: input, body };
      calls.push(call);
      const path = input.replace("/api/v1/owner/companies/1/", "").split("?")[0]!;
      const handler = routes[`${call.method} ${path}`];
      return handler ? handler(call) : json({ detail: "Not found." }, 404);
    }),
  );
  return calls;
}

const person = (id: number, name: string) => ({ id, name, photo_url: null });

function item(overrides: Partial<ProjectItem> = {}): ProjectItem {
  return {
    id: 1,
    key: "OPEN",
    name: "Chilonzor branch opening",
    color: "chart-1",
    icon: "store",
    status: "active",
    priority: "high",
    visibility: "members",
    lead: person(12, "Bekzod Mirzayev"),
    branch: { id: 1, name: "Chilonzor" },
    client: null,
    start_on: "2026-09-11",
    due_on: "2026-10-27",
    completed_at: null,
    archived_at: null,
    progress: { done: 16, total: 30, overdue: 1, percent: 53 },
    health: "at_risk",
    reported: null,
    members: [person(12, "Bekzod Mirzayev"), person(13, "Alisher Valiyev")],
    member_count: 2,
    next_milestone: { id: 2, name: "Fit-out complete", due_on: "2026-10-23" },
    my_role: "member",
    currency: "UZS",
    budget: "120000000.00",
    budget_currency: "UZS",
    spent: "86400000.00",
    burn: 72,
    ...overrides,
  };
}

function detail(overrides: Partial<ProjectDetail> = {}): ProjectDetail {
  return {
    ...item(),
    description: "",
    created_at: "2026-09-06T09:00:00Z",
    created_by: null,
    lists: [
      { id: 10, name: "To do", position: 1024, is_done: false, wip_limit: null },
      { id: 11, name: "In progress", position: 2048, is_done: false, wip_limit: 3 },
      { id: 12, name: "Done", position: 3072, is_done: true, wip_limit: null },
    ],
    labels: [{ id: 5, name: "Urgent", color: "chart-1" }],
    milestones: [],
    capabilities: { manage: true, edit_cards: true, post_update: true, see_money: true, add_expense: true, see_labour: true, see_all_time: true },
    ...overrides,
  };
}

function card(overrides: Partial<Card> = {}): Card {
  return {
    id: 100,
    number: 1,
    key: "OPEN-1",
    title: "Paint the walls",
    list_id: 10,
    position: 1024,
    status: "todo",
    priority: "normal",
    due_at: "2026-10-25T13:00:00Z",
    start_on: null,
    assignee: person(13, "Alisher Valiyev"),
    label_ids: [5],
    milestone_id: null,
    checklist_done: 1,
    checklist_total: 3,
    comments: 2,
    proof: "none",
    proof_thumb: null,
    needs_confirmation: false,
    overdue: false,
    completed_at: null,
    minutes: 90,
    can_move: true,
    ...overrides,
  };
}

function board(cards: Card[]): Board {
  const project = detail();
  return { project: item(), lists: project.lists, cards, labels: project.labels, milestones: [], people: [person(13, "Alisher Valiyev")], capabilities: project.capabilities };
}

beforeEach(() => {
  mergeModuleMessages("projects", { en, ru: en, uz: en });
  toasts.splice(0, toasts.length);
});

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

describe("api", () => {
  it("calls the projects endpoints with the right params and bodies", async () => {
    const calls = stubApi({
      "GET projects/": () => json({ count: 0, next: null, previous: null, results: [] }),
      "POST projects/1/cards/100/move/": () => json({ card: card(), message: "" }),
      "POST projects/1/cards/": () => json(card()),
      "POST projects/time/": () => json({}),
      "POST projects/1/cards/100/schedule/": () => json(card()),
    });
    await listProjects(1, { status: ["active", "planning"], mine: true, q: "chil" });
    await moveCard(1, 1, 100, 11, 1536.5);
    await createCard(1, 1, { title: "Order tiles", list: 10, assignee: 13 });
    await logTime(1, { day: "2026-10-21", minutes: 90, project: 1, note: "On site" });
    await scheduleCard(1, 1, 100, "2026-10-20", "2026-10-24");
    expect(calls.map((c) => `${c.method} ${c.url}`)).toEqual([
      "GET /api/v1/owner/companies/1/projects/?status=active&status=planning&q=chil&mine=1&page_size=200",
      "POST /api/v1/owner/companies/1/projects/1/cards/100/move/",
      "POST /api/v1/owner/companies/1/projects/1/cards/",
      "POST /api/v1/owner/companies/1/projects/time/",
      "POST /api/v1/owner/companies/1/projects/1/cards/100/schedule/",
    ]);
    expect(calls[1]!.body).toEqual({ list: 11, position: 1536.5 });
    expect(calls[2]!.body).toEqual({ title: "Order tiles", list: 10, assignee: 13 });
    expect(calls[3]!.body).toEqual({ day: "2026-10-21", minutes: 90, project: 1, note: "On site" });
    expect(calls[4]!.body).toEqual({ start_on: "2026-10-20", end_on: "2026-10-24" });
  });

  it("moves a card to the end of a list when no position is given", async () => {
    const calls = stubApi({ "POST projects/1/cards/100/move/": () => json({ card: card(), message: "" }) });
    await moveCard(1, 1, 100, 12);
    expect(calls[0]!.body).toEqual({ list: 12 });
  });
});

describe("helpers", () => {
  it("reads durations the way people type them", () => {
    expect(parseDuration("1:30")).toBe(90);
    expect(parseDuration("90m")).toBe(90);
    expect(parseDuration("2h")).toBe(120);
    expect(parseDuration("1.5")).toBe(90);
    expect(parseDuration("45")).toBe(45);
    expect(parseDuration("abc")).toBeNull();
    expect(hhmm(65)).toBe("1:05");
    expect(hhmm(0)).toBe("0:00");
  });

  it("places a dropped card between its neighbours", () => {
    expect(dropPosition({ position: 1024 }, { position: 2048 })).toBe(1536);
    expect(dropPosition(null, { position: 1024 })).toBe(0);
    expect(dropPosition({ position: 1024 }, null)).toBe(2048);
  });

  it("tells how close a deadline is", () => {
    const now = Date.parse("2026-10-21T08:00:00Z");
    expect(dueState(card({ due_at: "2026-10-20T13:00:00Z" }), now)).toBe("overdue");
    expect(dueState(card({ due_at: "2026-10-22T13:00:00Z" }), now)).toBe("soon");
    expect(dueState(card({ due_at: "2026-10-30T13:00:00Z" }), now)).toBe("later");
    expect(dueState(card({ status: "done", due_at: "2026-10-20T13:00:00Z" }), now)).toBe("done");
    expect(dueState(card({ due_at: null }), now)).toBeNull();
  });

  it("shortens milestone labels that would run into the next diamond", () => {
    const out = declutterMilestones(
      [
        { id: 1, date: "2026-10-23", label: "Fit-out complete" },
        { id: 2, date: "2026-10-25", label: "Staff hired and trained" },
        { id: 3, date: "2026-11-20", label: "Grand opening" },
      ],
      16,
    );
    expect(out.map((m) => m.label)).toEqual(["", "Staff hired and trained", "Grand opening"]);
    expect(declutterMilestones([{ date: "2026-10-23", label: "Fit-out complete" }, { date: "2026-10-25", label: "Launch" }], 40)[0]!.label).toBe("Fit-ou…");
    expect(declutterMilestones([{ date: "2026-10-23", label: "Fit-out complete" }, { date: "2026-10-27", label: "Launch" }], 40)[0]!.label).toBe("Fit-out complete");
  });

  it("moves a card in the cached board", () => {
    const moved = applyMove(board([card(), card({ id: 101, key: "OPEN-2" })]), card(), 11, 3000);
    expect(moved.cards.find((c) => c.id === 100)).toMatchObject({ list_id: 11, position: 3000 });
    expect(moved.cards.find((c) => c.id === 101)).toMatchObject({ list_id: 10 });
  });
});

describe("index", () => {
  it("shows the projects as cards with progress, health and budget burn", async () => {
    stubApi({
      "GET projects/": () => json({ count: 1, next: null, previous: null, results: [item()] }),
      "GET projects/summary/": () =>
        json({ active: 1, planning: 0, at_risk: 1, off_track: 0, overdue_cards: 1, due_this_week: 0, hours_this_week: 57, budget: "120000000.00", spent: "86400000.00", currency: "UZS" }),
      "GET projects/people/": () => json([]),
      "GET projects/options/": () => json({ branches: [], clients: [], currency: "UZS", can_create: true }),
    });
    const { plugins } = await testApp("/c/1/projects");
    const { wrapper } = mountWithProviders(ProjectsPage, { plugins });
    await flushPromises();
    await flushPromises();
    const text = wrapper.text();
    expect(text).toContain("Chilonzor branch opening");
    expect(text).toContain("16 of 30 cards done");
    expect(text).toContain("1 overdue");
    expect(text).toContain("Fit-out complete");
    expect(text).toContain("New project");
    wrapper.unmount();
  });

  it("hides the budget burn from people who don't see the project's money", async () => {
    const { plugins } = await testApp("/c/1/projects");
    const { spent: _spent, burn: _burn, ...noMoney } = item();
    const { wrapper } = mountWithProviders(ProjectCard, { props: { project: noMoney, companyId: 1 }, plugins });
    expect(wrapper.text()).not.toContain("Budget");
    const withMoney = mountWithProviders(ProjectCard, { props: { project: item(), companyId: 1 }, plugins });
    expect(withMoney.wrapper.text()).toContain("Budget");
    wrapper.unmount();
    withMoney.wrapper.unmount();
  });
});

describe("board", () => {
  async function mountBoard(cards: Card[], move: (call: Call) => Response) {
    const calls = stubApi({
      "GET projects/1/board/": () => json(board(cards)),
      "POST projects/1/cards/100/move/": move,
      "GET projects/": () => json({ count: 0, next: null, previous: null, results: [] }),
    });
    const app = await testApp("/c/1/projects/1/board");
    const { wrapper } = mountWithProviders(BoardTab, { props: { project: detail() }, plugins: app.plugins });
    await flushPromises();
    await flushPromises();
    return { calls, app, wrapper };
  }

  it("invites the first card on an empty board", async () => {
    const { wrapper } = await mountBoard([], () => json({}));
    expect(wrapper.text()).toContain(en["projects.board.startTitle"]);
    expect(wrapper.text()).toContain(en["projects.board.startAction"]);
  });

  it("renders lists with WIP limits and cards with their key, labels and counts", async () => {
    const { wrapper } = await mountBoard([card()], () => json({}));
    const text = wrapper.text();
    expect(text).toContain("In progress");
    expect(text).toContain("0 / 3");
    expect(text).toContain("OPEN-1");
    expect(text).toContain("Urgent");
    expect(text).toContain("1/3");
    expect(text).toContain("1:30");
    wrapper.unmount();
  });

  it("moves a card at once and keeps it there when the server agrees", async () => {
    let answer: (response: Response) => void = () => undefined;
    const pending = new Promise<Response>((resolve) => (answer = resolve));
    const cards = [card()];
    const { calls, app, wrapper } = await mountBoard(cards, () => pending as unknown as Response);
    wrapper.findComponent(KanbanBoard).vm.$emit("move", { item: card(), from: "10", to: "11", index: 0, before: null, after: null });
    await flushPromises();
    // Before the server answers, the card is already in its new list.
    expect(app.client.getQueryData<Board>(projectKeys.board(1, 1))?.cards[0]).toMatchObject({ list_id: 11 });
    cards[0] = card({ list_id: 11, position: 1024 });
    answer(json({ card: cards[0], message: "" }));
    await flushPromises();
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({ list: 11, position: 1024 });
    expect(app.client.getQueryData<Board>(projectKeys.board(1, 1))?.cards[0]).toMatchObject({ list_id: 11 });
    wrapper.unmount();
  });

  it("snaps a card back and opens it when it needs proof to be finished", async () => {
    const { app, wrapper } = await mountBoard([card({ proof: "photo" })], () => json({ detail: "This card needs a photo.", code: "needs_proof" }, 400));
    wrapper.findComponent(KanbanBoard).vm.$emit("move", { item: card({ proof: "photo" }), from: "10", to: "12", index: 0, before: null, after: null });
    await flushPromises();
    await flushPromises();
    expect(app.client.getQueryData<Board>(projectKeys.board(1, 1))?.cards[0]).toMatchObject({ list_id: 10 });
    expect(app.router.currentRoute.value.query.card).toBe("100");
    expect(toasts.some((toast) => toast.title.includes("needs a photo"))).toBe(true);
    await flushPromises();
    wrapper.unmount();
  });

  it("filters cards by person, label and search from the URL", async () => {
    const other = card({ id: 101, key: "OPEN-2", title: "Order tiles", assignee: person(14, "Madina Saidova"), label_ids: [] });
    const { app, wrapper } = await mountBoard([card(), other], () => json({}));
    await app.router.push("/c/1/projects/1/board?label=5");
    await flushPromises();
    expect(wrapper.text()).toContain("Paint the walls");
    expect(wrapper.text()).not.toContain("Order tiles");
    await app.router.push("/c/1/projects/1/board?q=tiles");
    await flushPromises();
    expect(wrapper.text()).toContain("Order tiles");
    expect(wrapper.text()).not.toContain("Paint the walls");
    wrapper.unmount();
  });
});
