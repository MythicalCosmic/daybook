/**
 * Projects in the mini app (PLAN-OWNER §13.3): the feature plugs in (Me row, Home cards, (+)
 * action, deep links), the list and the board render, my own cards move (and snap back when the
 * server says no), and "Log time" sends what the person picked.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../../api/client";
import type { Me, Membership, Task } from "../../api/types";
import { I18nProvider } from "../../i18n";
import { NavigationProvider, useNavigation, type Navigation } from "../../state/navigation";
import { SessionProvider } from "../../state/session";
import { ToastProvider } from "../../state/toast";
import { collectFeatures, routeTarget, type Feature } from "../registry";
import type { Board, Card, Project, Timer } from "./api";
import { ProjectsCard, TimerCard } from "./HomeCards";
import { elapsed, endOf, hhmm, positionBetween } from "./lib";
import { messages } from "./messages";
import TaskTimer from "./TaskTimer";

const server = vi.hoisted(() => ({
  calls: [] as { path: string; method: string; json: unknown }[],
  handler: (() => undefined) as (path: string, method: string, json: unknown) => unknown,
}));

vi.mock("../../api/client", async (importOriginal) => {
  const real = await importOriginal<typeof import("../../api/client")>();
  return {
    ...real,
    api: vi.fn(async (path: string, options: { method?: string; json?: unknown } = {}) => {
      const method = options.method ?? "GET";
      server.calls.push({ path, method, json: options.json });
      const result = server.handler(path, method, options.json);
      if (result instanceof Error) throw result;
      return result;
    }),
  };
});

const { default: feature } = await import("./index");
const { default: ProjectsPage } = await import("./ProjectsPage");
const { default: BoardPage } = await import("./BoardPage");
const { default: CardSheet } = await import("./CardSheet");
const { default: LogTimeSheet } = await import("./LogTimeSheet");
const api = await import("./api");

const ME = 7;
const person = (id: number, name: string) => ({ id, name, photo_url: null });

function membership(): Membership {
  return {
    id: ME,
    company: {
      id: 1,
      name: "Demo Dorixona",
      timezone: "Asia/Tashkent",
      features: [],
      owner_sees_personal_tasks: false,
      base_currency: "UZS",
      team_directory_phones: false,
    },
    status: "approved",
    first_name: "Alisher",
    last_name: "Valiyev",
    position: null,
    role: "Employee",
    permissions: [],
    is_onboarded: true,
    onboarded_at: null,
    decided_at: null,
    rejoin_available_at: null,
    home_branch: null,
    branch_ids: [],
    suspended_until: null,
  };
}

const project: Project = {
  id: 5,
  key: "OPEN",
  name: "Chilonzor branch opening",
  color: "chart-2",
  icon: "store",
  status: "active",
  lead: person(3, "Dilnoza Karimova"),
  due_on: "2026-11-20",
  progress: { done: 4, total: 10, overdue: 1, percent: 40 },
  health: "at_risk",
  members: [person(3, "Dilnoza Karimova"), person(ME, "Alisher Valiyev")],
  member_count: 2,
  next_milestone: { id: 1, name: "Soft opening", due_on: "2026-11-10" },
  my_role: "member",
  my_open: 2,
};

function card(id: number, list: number, overrides: Partial<Card> = {}): Card {
  return {
    id,
    number: id,
    key: `OPEN-${id}`,
    title: `Card ${id}`,
    list_id: list,
    position: id * 1024,
    status: "todo",
    priority: "normal",
    due_at: null,
    assignee: person(ME, "Alisher Valiyev"),
    label_ids: [],
    milestone_id: null,
    checklist_done: 0,
    checklist_total: 0,
    comments: 0,
    proof: "none",
    overdue: false,
    minutes: 0,
    can_move: true,
    ...overrides,
  };
}

function board(): Board {
  const { my_open: _, ...rest } = project;
  return {
    project: rest,
    lists: [
      { id: 10, name: "To do", position: 1, is_done: false, wip_limit: null },
      { id: 11, name: "In progress", position: 2, is_done: false, wip_limit: 1 },
      { id: 12, name: "Done", position: 3, is_done: true, wip_limit: null },
    ],
    cards: [
      card(1, 10, { title: "Paint the back wall", label_ids: [1], checklist_done: 1, checklist_total: 3 }),
      card(2, 11, { title: "Hang the sign", minutes: 95 }),
      card(3, 11, { title: "Order shelves", assignee: person(3, "Dilnoza Karimova"), can_move: false }),
    ],
    labels: [{ id: 1, name: "Fit-out", color: "chart-4" }],
    people: [person(3, "Dilnoza Karimova"), person(ME, "Alisher Valiyev")],
    capabilities: { manage: false, edit_cards: false, post_update: false },
  };
}

let state: { board: Board; projects: Project[]; timer: Timer | null };
let nav: Navigation | null = null;
function Probe() {
  nav = useNavigation();
  return null;
}

function renderWith(node: ReactNode, client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } })) {
  const me = { id: 1, telegram_id: 4242, telegram_username: "", first_name: "Alisher", last_name: "Valiyev", phone: "", memberships: [membership()] } as Me;
  return {
    client,
    ...render(
      <QueryClientProvider client={client}>
        <I18nProvider lang="en">
          <ToastProvider>
            <SessionProvider me={me}>
              <NavigationProvider>
                {node}
                <Probe />
              </NavigationProvider>
            </SessionProvider>
          </ToastProvider>
        </I18nProvider>
      </QueryClientProvider>,
    ),
  };
}

beforeEach(() => {
  server.calls.splice(0);
  state = { board: board(), projects: [project], timer: null };
  server.handler = (path, method) => {
    if (path === "/companies/1/projects/" && method === "GET") return state.projects;
    if (path === "/companies/1/projects/5/board/") return state.board;
    if (path === "/companies/1/projects/timer/") return { timer: state.timer };
    if (path === "/companies/1/projects/time/" && method === "GET") return { start: "", end: "", days: [], total: 150, entries: [] };
    return undefined;
  };
});

afterEach(() => {
  cleanup();
  nav = null;
});

describe("the Me row", () => {
  function Status() {
    const item = feature.meItems![0]!;
    const member = { ...membership(), timeZone: "Asia/Tashkent", companyId: 1 };
    const status = item.useStatus!({ member, summary: undefined });
    return <span data-testid="status">{String(status.value ?? "")}|{String(status.badge ?? "")}</span>;
  }

  it("shows my open cards as its value, not as a bubble beside the project count", async () => {
    state.projects = [project, { ...project, id: 6, my_open: 9 }];
    renderWith(<Status />);
    expect(await screen.findByText("11 open|")).toBeTruthy();
  });

  it("counts my projects when no card of mine is open", async () => {
    state.projects = [{ ...project, my_open: 0 }];
    renderWith(<Status />);
    expect(await screen.findByText("1|")).toBeTruthy();
  });
});

describe("the feature", () => {
  it("plugs into Me, Home, the (+) sheet and deep links", () => {
    const { features, problems } = collectFeatures({ "./projects/index.ts": { default: feature } });
    expect(problems).toEqual([]);
    const registered = features as Feature[];
    expect(registered[0]!.meItems?.map((item) => [item.group, item.label])).toEqual([["work", "me.projects"]]);
    expect(registered[0]!.homeCards?.map((slot) => slot.id)).toEqual(["timer"]);
    expect(registered[0]!.homeEnd?.map((slot) => slot.id)).toEqual(["projects"]);
    expect(registered[0]!.taskActions?.map((slot) => [slot.id, slot.order])).toEqual([["timer", 20]]);
    expect(registered[0]!.plusActions?.map((action) => action.open)).toEqual([{ sheet: "log" }]);
    expect(routeTarget(registered, "project", "5")).toEqual({ tab: "home", stack: [{ feature: "projects", page: "board", params: { id: 5 } }] });
    // The inbox's "added to a project" notification opens `projects.board:<id>`.
    expect(routeTarget(registered, "projects.board", "5")).toEqual({ tab: "home", stack: [{ feature: "projects", page: "board", params: { id: 5 } }] });
    expect(routeTarget(registered, "projects.updates", "5")?.stack?.[0]).toEqual({ feature: "projects", page: "updates", params: { id: 5 } });
  });

  it("hides from people who aren't approved or are suspended", () => {
    const member = { ...membership(), timeZone: "Asia/Tashkent", companyId: 1 };
    expect(feature.visible?.(member, undefined)).toBe(true);
    expect(feature.visible?.({ ...member, status: "pending" }, undefined)).toBe(false);
    expect(feature.visible?.({ ...member, status: "suspended" as Membership["status"] }, undefined)).toBe(false);
  });

  it("has every message in English, Russian and Uzbek", () => {
    const base = (dictionary: Record<string, string>) =>
      [...new Set(Object.keys(dictionary).map((key) => key.replace(/_(one|few|many|other)$/, "")))].sort();
    expect(base(messages.ru)).toEqual(base(messages.en));
    expect(base(messages.uz)).toEqual(base(messages.en));
    for (const value of Object.values(messages.uz)) expect(value).not.toMatch(/[a-z]'[a-z]/i);
  });
});

describe("helpers and endpoints", () => {
  it("format time and place cards", () => {
    expect(hhmm(65)).toBe("1:05");
    expect(hhmm(0)).toBe("0:00");
    expect(elapsed("2026-10-21T08:00:00Z", Date.parse("2026-10-21T08:42:05Z"))).toBe("42:05");
    expect(elapsed("2026-10-21T08:00:00Z", Date.parse("2026-10-21T09:05:09Z"))).toBe("1:05:09");
    const cards = board().cards;
    expect(endOf(cards, 11)).toBe(3 * 1024 + 1024);
    expect(endOf(cards, 12)).toBe(1024);
    expect(positionBetween(cards[0], cards[1])).toBe(1536);
  });

  it("call the employee endpoints", async () => {
    server.handler = () => ({});
    await api.moveCard(1, 5, 9, 11, 2048);
    await api.logTime(1, { day: "2026-10-21", minutes: 90, project: 5, task: null, note: "" });
    await api.startTimer(1, { task: 9 });
    await api.stopTimer(1);
    await api.postUpdate(1, 5, "at_risk", "Waiting for the sign");
    expect(server.calls.map((call) => [call.method, call.path, call.json])).toEqual([
      ["POST", "/companies/1/projects/5/cards/9/move/", { list: 11, position: 2048 }],
      ["POST", "/companies/1/projects/time/", { day: "2026-10-21", minutes: 90, project: 5, task: null, note: "" }],
      ["POST", "/companies/1/projects/timer/", { task: 9 }],
      ["POST", "/companies/1/projects/timer/stop/", undefined],
      ["POST", "/companies/1/projects/5/updates/", { health: "at_risk", text: "Waiting for the sign" }],
    ]);
  });
});

describe("screens", () => {
  it("list my projects with progress, health and my open cards", async () => {
    renderWith(<ProjectsPage />);
    expect(await screen.findByText("Chilonzor branch opening")).toBeTruthy();
    expect(screen.getByText("At risk")).toBeTruthy();
    expect(screen.getByText("2 cards of yours open")).toBeTruthy();
    act(() => fireEvent.click(screen.getByRole("button", { name: /Chilonzor branch opening/ })));
    expect(nav!.stack).toEqual([{ feature: "projects", page: "board", params: { id: 5 } }]);
  });

  it("show the board as stacked lists, with WIP counts and locked cards", async () => {
    const { container } = renderWith(<BoardPage params={{ id: 5 }} />);
    expect(await screen.findByText("Paint the back wall")).toBeTruthy();
    const heads = [...container.querySelectorAll(".prj-list-head")].map((node) => node.textContent);
    expect(heads).toEqual(["To do1", "In progress2 / 1", "Done0"]);
    expect(container.querySelector(".prj-wip--over")).toBeTruthy();
    expect(screen.getByText("Fit-out")).toBeTruthy();
    expect(screen.getByText("1/3")).toBeTruthy();
    expect(screen.getByText("1:35")).toBeTruthy();
    expect(screen.getAllByLabelText("Only the person it's for moves this card")).toHaveLength(1);
    // "My cards" leaves out the lead's card.
    act(() => fireEvent.click(screen.getByRole("radio", { name: /My cards/ })));
    expect(screen.queryByText("Order shelves")).toBeNull();
  });

  it("open a card on tap", async () => {
    renderWith(<BoardPage params={{ id: 5 }} />);
    const tile = (await screen.findByText("Hang the sign")).closest("button")!;
    act(() => {
      fireEvent.pointerDown(tile, { pointerId: 1, clientX: 10, clientY: 10, button: 0 });
      fireEvent.pointerUp(tile, { pointerId: 1 });
    });
    expect(nav!.sheet).toEqual({ kind: "feature", feature: "projects", sheet: "card", params: { project: 5, id: 2 } });
  });

  it("move my card at once and keep the server's answer", async () => {
    let release: (value: unknown) => void = () => {};
    server.handler = (path, method, json) => {
      if (path.endsWith("/cards/1/move/") && method === "POST") {
        const body = json as { list: number; position: number };
        return new Promise((resolve) => {
          release = () => resolve({ card: card(1, body.list, { title: "Paint the back wall", status: "in_progress", position: body.position }), message: "" });
        });
      }
      if (path === "/companies/1/projects/5/board/") return state.board;
      if (path === "/companies/1/projects/timer/") return { timer: null };
      return undefined;
    };
    const { client } = renderWith(<CardSheet params={{ project: 5, id: 1 }} close={() => {}} />);
    await screen.findByText("Move to");
    expect(screen.queryByRole("button", { name: "To do" })).toBeNull();
    act(() => fireEvent.click(screen.getByRole("button", { name: "In progress" })));
    await waitFor(() => expect(client.getQueryData<Board>(api.projectKeys.board(1, 5))?.cards[0]!.list_id).toBe(11));
    state.board = { ...state.board, cards: state.board.cards.map((c) => (c.id === 1 ? { ...c, list_id: 11, status: "in_progress" } : c)) };
    await act(async () => release(undefined));
    expect(await screen.findByText("Moved to In progress")).toBeTruthy();
    expect(server.calls.find((call) => call.method === "POST")?.json).toEqual({ list: 11, position: 4096 });
  });

  it("snap the card back when it needs a photo first", async () => {
    server.handler = (path, method) => {
      if (path.endsWith("/move/") && method === "POST") return new ApiError(400, { detail: "Needs a photo.", code: "needs_proof" });
      if (path === "/companies/1/projects/5/board/") return state.board;
      if (path === "/companies/1/projects/timer/") return { timer: null };
      return undefined;
    };
    const { client } = renderWith(<CardSheet params={{ project: 5, id: 1 }} close={() => {}} />);
    await screen.findByText("Move to");
    act(() => fireEvent.click(screen.getByRole("button", { name: "Done" })));
    expect(await screen.findByText("Finish it from the task: it needs a photo or a report.")).toBeTruthy();
    expect(client.getQueryData<Board>(api.projectKeys.board(1, 5))?.cards[0]!.list_id).toBe(10);
  });

  it("don't offer moves on someone else's card", async () => {
    renderWith(<CardSheet params={{ project: 5, id: 3 }} close={() => {}} />);
    expect(await screen.findByText("Order shelves")).toBeTruthy();
    expect(screen.queryByText("Move to")).toBeNull();
    expect(screen.queryByRole("button", { name: "Start timer" })).toBeNull();
    expect(screen.getByRole("button", { name: "Log time" })).toBeTruthy();
  });

  it("start the timer on my card", async () => {
    renderWith(<CardSheet params={{ project: 5, id: 2 }} close={() => {}} />);
    const start = await screen.findByRole("button", { name: "Start timer" });
    act(() => fireEvent.click(start));
    await waitFor(() => expect(server.calls.some((call) => call.path === "/companies/1/projects/timer/" && call.method === "POST")).toBe(true));
    expect(server.calls.find((call) => call.method === "POST")?.json).toEqual({ task: 2 });
  });

  it("log time in 15-minute steps on the card it opened from", async () => {
    const close = vi.fn();
    renderWith(<LogTimeSheet params={{ project: 5, task: 2 }} close={close} />);
    expect(await screen.findByText("This week: 2:30")).toBeTruthy();
    act(() => fireEvent.click(screen.getByRole("button", { name: "15 minutes more" })));
    act(() => fireEvent.click(screen.getByRole("button", { name: "15 minutes more" })));
    act(() => fireEvent.change(screen.getByPlaceholderText("e.g. Set up the new vitamins shelf"), { target: { value: " Sign brackets " } }));
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Save 1:30" })));
    const post = server.calls.find((call) => call.method === "POST");
    expect(post?.path).toBe("/companies/1/projects/time/");
    expect(post?.json).toMatchObject({ minutes: 90, project: 5, task: 2, note: "Sign brackets" });
    expect((post?.json as { day: string }).day).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    await waitFor(() => expect(close).toHaveBeenCalled());
  });

  it("explain that logging needs a project", async () => {
    state.projects = [];
    renderWith(<LogTimeSheet params={{}} close={() => {}} />);
    expect(await screen.findByText("Join a project first to log time on it.")).toBeTruthy();
  });
});

describe("home cards", () => {
  const slot = { member: { ...membership(), timeZone: "Asia/Tashkent", companyId: 1 }, summary: undefined };

  it("show my live projects, and nothing without any", async () => {
    renderWith(<ProjectsCard {...slot} />);
    expect(await screen.findByText("Your projects")).toBeTruthy();
    cleanup();
    state.projects = [{ ...project, status: "completed" }];
    const { container } = renderWith(<ProjectsCard {...slot} />);
    await waitFor(() => expect(server.calls.filter((call) => call.path === "/companies/1/projects/").length).toBe(2));
    expect(container.textContent).toBe("");
  });

  it("show the running timer with Stop", async () => {
    state.timer = { id: 1, project: { id: 5, name: project.name }, project_key: "OPEN", task: { id: 2, name: "Hang the sign" }, task_key: "OPEN-2", started_at: new Date(Date.now() - 125_000).toISOString() };
    server.handler = ((previous) => (path: string, method: string, json: unknown) => {
      if (path === "/companies/1/projects/timer/stop/") {
        state.timer = null;
        return { id: 9, minutes: 2, day: "2026-10-21", note: "", project: null, project_key: null, task: null };
      }
      return previous(path, method, json);
    })(server.handler);
    renderWith(<TimerCard {...slot} />);
    expect(await screen.findByText("OPEN-2 · Hang the sign")).toBeTruthy();
    expect(screen.getByText(/^2:0\d$/)).toBeTruthy();
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Stop" })));
    expect(await screen.findByText("0:02 logged")).toBeTruthy();
  });
});

describe("the timer on the task screen", () => {
  const slot = { member: { ...membership(), timeZone: "Asia/Tashkent", companyId: 1 }, summary: undefined };
  const task = (id: number, overrides: Partial<Task> = {}) =>
    ({
      id,
      title: `Card ${id}`,
      status: "todo",
      assignee: { id: ME, name: "Alisher Valiyev", position: null },
      card: { project_id: 5, project_key: "OPEN", number: id, key: `OPEN-${id}` },
      ...overrides,
    }) as Task;
  const running = (taskId: number): Timer => ({
    id: 1,
    project: { id: 5, name: project.name },
    project_key: "OPEN",
    task: { id: taskId, name: `Card ${taskId}` },
    task_key: `OPEN-${taskId}`,
    started_at: new Date(Date.now() - 125_000).toISOString(),
  });
  const loaded = () =>
    waitFor(() => {
      expect(server.calls.some((call) => call.path === "/companies/1/projects/5/board/")).toBe(true);
      expect(server.calls.some((call) => call.path === "/companies/1/projects/timer/")).toBe(true);
    });

  it("starts on my card, showing what's logged on it", async () => {
    renderWith(<TaskTimer {...slot} task={task(2)} />);
    expect(await screen.findByText("OPEN-2 · 1:35 logged")).toBeTruthy();
    expect(screen.getByText("Timer")).toBeTruthy();
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Start timer" })));
    expect(server.calls.find((call) => call.method === "POST")).toMatchObject({ path: "/companies/1/projects/timer/", json: { task: 2 } });
    expect(await screen.findByText("Timer started")).toBeTruthy();
  });

  it("shows the running clock on its own task, and stops it", async () => {
    state.timer = running(2);
    server.handler = ((previous) => (path: string, method: string, json: unknown) => {
      if (path === "/companies/1/projects/timer/stop/") {
        state.timer = null;
        return { id: 9, minutes: 2, day: "2026-10-21", note: "", project: null, project_key: null, task: null };
      }
      return previous(path, method, json);
    })(server.handler);
    renderWith(<TaskTimer {...slot} task={task(2)} />);
    expect(await screen.findByText("Timer running · OPEN-2")).toBeTruthy();
    expect(screen.getByText(/^2:0\d$/)).toBeTruthy();
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Stop" })));
    expect(await screen.findByText("0:02 logged")).toBeTruthy();
    // Stopped and refetched: the block goes back to Start.
    expect(await screen.findByRole("button", { name: "Start timer" })).toBeTruthy();
  });

  it("keeps Stop on a finished task while the timer still runs on it", async () => {
    state.timer = running(2);
    renderWith(<TaskTimer {...slot} task={task(2, { status: "done" })} />);
    expect(await screen.findByRole("button", { name: "Stop" })).toBeTruthy();
  });

  it("says where the timer runs when it's on another card", async () => {
    state.timer = running(1);
    renderWith(<TaskTimer {...slot} task={task(2)} />);
    expect(await screen.findByText("Your timer is on OPEN-1 now")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Start timer" })).toBeTruthy();
  });

  it("asks for nothing on a task that isn't a card", async () => {
    const { container } = renderWith(<TaskTimer {...slot} task={task(8, { card: null })} />);
    await act(async () => {});

    expect(server.calls).toEqual([]);
    expect(container.textContent).toBe("");
  });

  it("shows nothing for a card the board doesn't show me, someone else's card, or a finished one", async () => {
    const cases: [number, Partial<Task>][] = [
      [99, {}],
      [3, { assignee: { id: 3, name: "Dilnoza Karimova", position: null } }],
      [2, { status: "done" }],
      [2, { status: "cancelled" }],
      // Waiting for a check: no timer to start (the reviewer sees the card, not work to time).
      [2, { status: "review" }],
    ];
    for (const [id, overrides] of cases) {
      server.calls.splice(0);
      const { container } = renderWith(<TaskTimer {...slot} task={task(id, overrides)} />);
      await loaded();
      await act(async () => {});
      expect(container.textContent).toBe("");
      cleanup();
    }
  });

  it("lets a card editor time someone else's card", async () => {
    state.board = { ...state.board, capabilities: { ...state.board.capabilities, edit_cards: true } };
    renderWith(<TaskTimer {...slot} task={task(3, { assignee: { id: 3, name: "Dilnoza Karimova", position: null } })} />);
    expect(await screen.findByRole("button", { name: "Start timer" })).toBeTruthy();
  });

  it("loads only the card's own board, never the list of projects", async () => {
    renderWith(<TaskTimer {...slot} task={task(2)} />);
    await screen.findByRole("button", { name: "Start timer" });

    expect(server.calls.map((call) => call.path).sort()).toEqual(["/companies/1/projects/5/board/", "/companies/1/projects/timer/"]);
  });

  it("offers no timer on a finished project's card", async () => {
    state.board = { ...state.board, project: { ...state.board.project, status: "completed" } };
    const { container } = renderWith(<TaskTimer {...slot} task={task(2)} />);
    await loaded();
    await act(async () => {});
    expect(container.textContent).toBe("");
  });
});
