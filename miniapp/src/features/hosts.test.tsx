/**
 * The real Home, Me and add sheet with fake feature folders registered: every slot host,
 * `replaces` and `plusActions` work in place (PLAN-OWNER §9.4 item 13 keeps this green).
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { CalendarCheck, HandCoins, Receipt, Trophy } from "lucide-react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { keys } from "../api/hooks";
import type { Me, Membership, Summary, Task } from "../api/types";
import { I18nProvider } from "../i18n";
import { Home } from "../screens/Home";
import { Tasks } from "../screens/Tasks";
import { ActivityScreen } from "../screens/Activity";
import { Profile } from "../screens/Profile";
import { Sheets } from "../sheets/Sheets";
import { NavigationProvider, useNavigation, type Navigation, type NavigationInit } from "../state/navigation";
import { SessionProvider } from "../state/session";
import { ToastProvider } from "../state/toast";
import { TaskDetail } from "../screens/TaskDetail";
import { defineFeature, type Feature, type PageProps, type SheetProps, type SlotProps, type TaskSlotProps } from "./registry";

const registry = vi.hoisted(() => ({ list: [] as unknown[] }));
vi.mock("./registry", async (importOriginal) => {
  const real = await importOriginal<typeof import("./registry")>();
  return { ...real, features: registry.list };
});

const Page = (_: PageProps) => <div className="detail-layer">page</div>;
const SheetBody = (_: SheetProps) => <div>sheet</div>;

const attendance: Feature = defineFeature({
  id: "attendance",
  messages: {
    en: { me: "Attendance", plus: "Swap a shift" },
    ru: { me: "Посещаемость", plus: "Обменять смену" },
    uz: { me: "Davomat", plus: "Smenani almashtirish" },
  },
  pages: { month: Page },
  sheets: { swap: SheetBody },
  homeHero: [{ id: "checkin", component: ({ member }: SlotProps) => <div data-testid="hero">{`Check in, ${member.first_name}`}</div> }],
  meItems: [{ id: "month", group: "work", label: "me", icon: CalendarCheck, open: { page: "month" }, useStatus: () => ({ value: "21/22" }) }],
  plusActions: [{ id: "swap", label: "plus", icon: CalendarCheck, open: { sheet: "swap" } }],
});

const wallet: Feature = defineFeature({
  id: "wallet",
  messages: { en: { me: "Pay" }, ru: { me: "Зарплата" }, uz: { me: "Maosh" } },
  pages: { home: Page },
  homeCards: [{ id: "earned", component: ({ summary }: SlotProps) => <div data-testid="card">{`Done today: ${summary?.today_done}`}</div> }],
  homeEnd: [{ id: "history", component: () => <div data-testid="end">Pay history</div> }],
  taskActions: [{ id: "bonus", component: ({ task }: TaskSlotProps) => <div data-testid="task-block">{`Bonus for ${task.title}`}</div> }],
  meItems: [{ id: "pay", group: "money", label: "me", icon: HandCoins, open: { page: "home" }, useStatus: () => ({ badge: 1 }) }],
});

const leave: Feature = defineFeature({
  id: "leave",
  messages: { en: { me: "Time off" }, ru: { me: "Отпуск" }, uz: { me: "Ta’til" } },
  replaces: ["timeOff"],
  pages: { home: Page },
  meItems: [{ id: "leave", group: "work", label: "me", icon: Receipt, open: { page: "home" }, order: 10 }],
});

const kudos: Feature = defineFeature({
  id: "kudos",
  messages: { en: { me: "Leaderboard" }, ru: { me: "Рейтинг" }, uz: { me: "Reyting" } },
  replaces: ["teamResults"],
  visible: (member) => member.permissions.includes("reports.view"),
  pages: { board: Page },
  meItems: [{ id: "board", group: "team", label: "me", icon: Trophy, open: { page: "board" } }],
});

function membership(permissions: string[]): Membership {
  return {
    id: 7,
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
    permissions: permissions as Membership["permissions"],
    is_onboarded: true,
    onboarded_at: null,
    decided_at: null,
    rejoin_available_at: null,
    home_branch: null,
    branch_ids: [],
    suspended_until: null,
  };
}

const summary: Summary = {
  today_total: 8,
  today_done: 3,
  late: 0,
  streak_days: 0,
  week: [],
  month_done: 8,
  month_on_time_percent: 67,
  quiet_from: null,
  quiet_until: null,
  unread_activity: 0,
  awaiting_review: 0,
  off_today: null,
};

let nav: Navigation | null = null;
function Probe() {
  nav = useNavigation();
  return null;
}

function renderWith(
  node: ReactNode,
  {
    permissions = [] as string[],
    initial = undefined as NavigationInit | undefined,
    seed = undefined as { task: Task; comments: [] } | undefined,
    numbers = summary as Summary | null,
    board = [] as Task[] | null,
    activity = [] as unknown[] | null,
  } = {},
) {
  const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } });
  if (numbers) client.setQueryData(keys.summary(1), numbers);
  if (seed) {
    client.setQueryData(keys.task(1, seed.task.id), seed.task);
    client.setQueryData(keys.comments(1, seed.task.id), seed.comments);
  }
  if (board) client.setQueryData(keys.board(1), board);
  if (activity) client.setQueryData(keys.activity(1), activity);
  client.setQueryData(keys.timeOff(1), []);
  client.setQueryData(keys.holidays(1), []);
  const me = { id: 1, telegram_id: 4242, telegram_username: "", first_name: "Alisher", last_name: "Valiyev", phone: "", memberships: [membership(permissions)] } as Me;
  return render(
    <QueryClientProvider client={client}>
      <I18nProvider lang="en">
        <ToastProvider>
          <SessionProvider me={me}>
            <NavigationProvider initial={initial}>
              {node}
              <Probe />
            </NavigationProvider>
          </SessionProvider>
        </ToastProvider>
      </I18nProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  registry.list.push(attendance, wallet, leave, kudos);
});

afterEach(() => {
  registry.list.splice(0);
  cleanup();
});

describe("feature hosts in the real screens", () => {
  it("put the hero under the greeting and cards after the banners on Home", () => {
    const { container } = renderWith(<Home />);
    const hero = screen.getByTestId("hero");
    const card = screen.getByTestId("card");
    expect(hero.textContent).toBe("Check in, Alisher");
    expect(card.textContent).toBe("Done today: 3");
    const order = [...container.querySelectorAll("[data-testid], .page-head, .section-head")].map((node) =>
      node.getAttribute("data-testid") ?? node.className,
    );
    expect(order.slice(0, 4)).toEqual(["page-head", "hero", "card", "section-head"]);
    // Overviews come last, after the day's tasks ("Up next").
    expect(order.at(-1)).toBe("end");
    expect(order.indexOf("end")).toBeGreaterThan(order.indexOf("section-head"));
  });

  it("say nothing is due once on Home: a sun instead of 0/0 and no empty Up next", () => {
    const { container } = renderWith(<Home />, { numbers: { ...summary, today_total: 0, today_done: 0, streak_days: 4 } });
    expect(screen.getByText("Nothing due today")).toBeTruthy();
    expect(screen.getByText("4 days in a row")).toBeTruthy();
    expect(screen.queryByText("0/0")).toBeNull();
    expect(container.querySelector(".home-today-free")).toBeTruthy();
    expect(screen.queryByText("Up next")).toBeNull();
    expect(screen.queryByText("Nothing else due today.")).toBeNull();
    cleanup();

    renderWith(<Home />);
    expect(screen.getByText("3/8")).toBeTruthy();
    expect(screen.getByText("Up next")).toBeTruthy();
  });

  it("tell routines and one-off work apart on Home's day card, when today has both", () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-10-21T10:00:00+05:00"));
    try {
      const due = "2026-10-21T15:00:00+05:00";
      const base = { description: "", priority: "normal", proof: "none", needs_confirmation: false, proof_text: "", proof_photo: null, checklist: [], reminder: null, repeat_weekdays: null, started_at: null, completed_at: null, confirmed_at: null, confirmed_by: null, is_overdue: false, actions: [], created_at: due, for_date: null, assignee: { id: 7, name: "Alisher Valiyev", position: null }, created_by: null };
      const board = [
        { ...base, id: 1, kind: "daily", title: "Fridge temperature", status: "done", due_at: due },
        { ...base, id: 2, kind: "daily", title: "Expiry dates", status: "todo", due_at: due },
        { ...base, id: 3, kind: "assigned", title: "Count the safe", status: "todo", due_at: due },
      ] as unknown as Task[];
      const { container } = renderWith(<Home />, { board, numbers: { ...summary, today_total: 3, today_done: 1 } });
      expect(container.querySelector(".home-today-split")?.textContent).toBe("Routines 1/2 · Tasks 0/1");
      // A routine's row carries the repeat mark; one-off work doesn't.
      const rows = [...container.querySelectorAll(".row")];
      expect(rows.find((row) => row.textContent?.includes("Expiry dates"))?.querySelector(".row-meta-routine")).toBeTruthy();
      expect(rows.find((row) => row.textContent?.includes("Count the safe"))?.querySelector(".row-meta-routine")).toBeNull();
      cleanup();

      renderWith(<Home />, { board: board.filter((task) => task.kind === "daily"), numbers: { ...summary, today_total: 2, today_done: 1 } });
      expect(document.querySelector(".home-today-split")).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it("say nothing they don't know yet: no guesses while loading, and a list that failed says so", async () => {
    // The summary and the board never arrive (no network in tests).
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new TypeError("Failed to fetch"))));
    try {
      const home = renderWith(<Home />, { numbers: null, board: null });
      expect(screen.queryByText("Nothing due today")).toBeNull();
      expect(home.container.querySelector(".home-today-loading")).toBeTruthy();
      expect(home.container.querySelector(".ui-ring-label")?.textContent).toBe("");
      // Up next doesn't claim "Nothing else due today" about a list it couldn't load.
      expect(await screen.findByText("This part didn't open")).toBeTruthy();
      expect(screen.queryByText("Nothing else due today.")).toBeNull();
      cleanup();

      renderWith(<Tasks />, { board: null });
      expect(screen.queryByText(/tasks? left for today/)).toBeNull();
      expect(await screen.findByText("This part didn't open")).toBeTruthy();
      expect(screen.queryByText("All done here")).toBeNull();
      cleanup();

      renderWith(<ActivityScreen />, { activity: null });
      expect(await screen.findByText("This part didn't open")).toBeTruthy();
      expect(screen.queryByText("You're all caught up")).toBeNull();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("claim no streak and keep no endless placeholder when the day's numbers fail", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new TypeError("Failed to fetch"))));
    try {
      const me = renderWith(<Profile />, { numbers: null });
      // Loading: a placeholder line, not "Finish today's tasks to start a streak" to someone mid-streak.
      expect(me.container.querySelector(".profile-streak .skeleton")).toBeTruthy();
      expect(screen.queryByText(/start a streak/)).toBeNull();
      // Failed: no streak card at all, rather than a claim or a placeholder that never ends.
      await waitFor(() => expect(me.container.querySelector(".profile-streak")).toBeNull());
      expect(screen.queryByText(/start a streak/)).toBeNull();
      cleanup();

      const home = renderWith(<Home />, { numbers: null });
      expect(home.container.querySelector(".home-today-loading")).toBeTruthy();
      await waitFor(() => expect(home.container.querySelector(".home-today")).toBeNull());
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("keep quiet hours with the settings on Me, under no group of their own", () => {
    const { container } = renderWith(<Profile />, { numbers: { ...summary, quiet_from: "22:00:00", quiet_until: "08:00:00" } });
    const headings = [...container.querySelectorAll(".section-head")].map((node) => node.textContent);
    expect(headings).not.toContain("My work");
    const settings = [...container.querySelectorAll(".card.list-card")].at(-1)!;
    expect(settings.textContent).toContain("Quiet hours");
    expect(settings.textContent).toContain("22:00–08:00");
  });

  it("group feature rows on Me and let features take over time off and team results", () => {
    const { container } = renderWith(<Profile />, { permissions: ["reports.view"] });
    const headings = [...container.querySelectorAll(".section-head")].map((node) => node.textContent);
    expect(headings).toEqual(["Money", "Work", "Team", "Settings"]);
    expect(screen.queryByText("Ask for days off")).toBeNull();
    expect(screen.queryByText("Team results")).toBeNull();
    const work = [...container.querySelectorAll(".card.list-card")][1];
    expect([...work.querySelectorAll(".list-item-label")].map((node) => node.textContent)).toEqual(["Time off", "Attendance"]);
    expect(screen.getByRole("button", { name: /Attendance/ }).textContent).toContain("21/22");
    act(() => fireEvent.click(screen.getByRole("button", { name: /Pay/ })));
    expect(nav!.stack).toEqual([{ feature: "wallet", page: "home", params: undefined }]);
  });

  it("keep the built-in entries for people the replacing feature isn't for", () => {
    renderWith(<Profile />, { permissions: [] });
    // kudos is hidden without reports.view (and so is the built-in team row); leave is visible.
    expect(screen.queryByText("Leaderboard")).toBeNull();
    expect(screen.queryByText("Team results")).toBeNull();
    expect(screen.queryByText("Ask for days off")).toBeNull();
    registry.list.splice(registry.list.indexOf(leave), 1);
    cleanup();
    renderWith(<Profile />, { permissions: [] });
    expect(screen.getByText("Ask for days off")).toBeTruthy();
  });

  it("put the task screen's blocks after the checklist, before the details", () => {
    const task: Task = {
      id: 42,
      kind: "assigned",
      title: "Open the till",
      description: "Count the float first.",
      status: "todo",
      priority: "normal",
      due_at: null,
      for_date: null,
      proof: "none",
      needs_confirmation: false,
      proof_text: "",
      proof_photo: null,
      assignee: { id: 7, name: "Alisher Valiyev", position: null },
      created_by: { id: 3, name: "Dilnoza Karimova", position: null },
      confirmed_by: null,
      checklist: [{ id: 1, text: "Count the float", is_done: false }],
      reminder: null,
      repeat_weekdays: null,
      started_at: null,
      completed_at: null,
      confirmed_at: null,
      is_overdue: false,
      actions: ["start", "complete"],
      created_at: "2026-10-18T10:00:00Z",
    } as Task;
    const { container } = renderWith(<TaskDetail taskId={42} />, { seed: { task, comments: [] } });
    expect(screen.getByTestId("task-block").textContent).toBe("Bonus for Open the till");
    const order = [...container.querySelectorAll(".check-item, [data-testid], .detail-line")].map((node) =>
      node.getAttribute("data-testid") ?? node.className,
    );
    expect(order.slice(0, 3)).toEqual(["check-item", "task-block", "detail-line"]);
  });

  it("put the task's actions in the bottom bar: the step that finishes it, the other beside it", () => {
    const base = {
      id: 43,
      kind: "assigned",
      title: "Count the safe",
      description: "",
      status: "todo",
      priority: "normal",
      due_at: null,
      for_date: null,
      proof: "none",
      needs_confirmation: false,
      proof_text: "",
      proof_photo: null,
      assignee: { id: 7, name: "Alisher Valiyev", position: null },
      created_by: { id: 3, name: "Dilnoza Karimova", position: null },
      confirmed_by: null,
      checklist: [],
      reminder: null,
      repeat_weekdays: null,
      started_at: null,
      completed_at: null,
      confirmed_at: null,
      is_overdue: false,
      actions: ["start", "complete"],
      created_at: "2026-10-18T10:00:00Z",
    } as unknown as Task;
    const bar = (container: HTMLElement) => [...container.querySelectorAll(".action-bar button")].map((button) => button.textContent);

    const mine = renderWith(<TaskDetail taskId={43} />, { seed: { task: base, comments: [] } });
    expect(bar(mine.container)).toEqual(["Start", "Mark as done"]);
    cleanup();

    const review = { ...base, status: "review", assignee: { id: 9, name: "Jasur Tursunov", position: null }, actions: ["return", "confirm"] } as Task;
    const checking = renderWith(<TaskDetail taskId={43} />, { seed: { task: { ...review, proof: "photo", completed_at: "2026-10-21T04:04:00Z" } as Task, comments: [] } });
    expect(bar(checking.container)).toEqual(["Send back", "Confirm"]);
    // The checker hears who finished it and what to do, not "it will be checked soon"; the photo
    // is attached, so no "Photo needed".
    expect(checking.container.textContent).toContain("Jasur Tursunov finished it at 09:04");
    expect(checking.container.textContent).toContain("Look at the proof, then confirm it or send it back.");
    expect(checking.container.textContent).not.toContain("Photo needed");
    cleanup();

    // Work that needed no proof: nothing to look at, so the note doesn't ask for it.
    const bare = renderWith(<TaskDetail taskId={43} />, { seed: { task: { ...review, proof: "none", completed_at: "2026-10-21T04:04:00Z" } as Task, comments: [] } });
    expect(bare.container.textContent).toContain("Confirm it, or send it back with what to fix.");
    cleanup();

    const waiting = { ...base, status: "review", actions: [] } as unknown as Task;
    const sent = renderWith(<TaskDetail taskId={43} />, { seed: { task: waiting, comments: [] } });
    expect(bar(sent.container)).toEqual(["Waiting for check"]);
    expect((sent.container.querySelector(".action-bar button") as HTMLButtonElement).disabled).toBe(true);
  });

  it("show quick-add actions above the personal task form", () => {
    const { container } = renderWith(<Sheets />, { initial: { sheet: { kind: "add" } } });
    const sheet = container.querySelector(".sheet")!;
    const firstLabel = sheet.querySelector(".field-label")?.textContent;
    expect(firstLabel).toBe("Quick add");
    expect(sheet.querySelector(".heading")?.textContent).toBe("New task");
    act(() => fireEvent.click(screen.getByRole("button", { name: "Swap a shift" })));
    expect(nav!.sheet).toEqual({ kind: "feature", feature: "attendance", sheet: "swap", params: undefined });
    expect(screen.getByText("sheet")).toBeTruthy();
  });
});
