/**
 * Routines read apart from one-off work: the worker's Routines tab (today's progress, finished
 * runs kept under "Done today") and the manager's To check (runs grouped by routine, confirmed
 * together, sent back one by one; one-off tasks on their own below).
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Me, Membership, Task } from "../api/types";
import { I18nProvider, LOCALES, translate } from "../i18n";
import { groupByRoutine, routineProgress } from "../lib/routines";
import type { ViewContext } from "../lib/taskView";
import { NavigationProvider, useNavigation } from "../state/navigation";
import { SessionProvider } from "../state/session";
import { ToastProvider } from "../state/toast";
import { ReviewQueue, RoutinesTab } from "./Routines";

const api = vi.hoisted(() => vi.fn());
vi.mock("../api/client", async (importOriginal) => ({ ...(await importOriginal<typeof import("../api/client")>()), api }));

const NOW = new Date("2026-10-21T10:00:00+05:00");

function ctx(lang: "en" | "uz" | "ru" = "en"): ViewContext {
  return { t: (key, vars) => translate(lang, key, vars), timeZone: "Asia/Tashkent", locale: LOCALES[lang], now: NOW };
}

let ids = 100;
function task(fields: Partial<Task> = {}): Task {
  ids += 1;
  return {
    id: ids,
    kind: "daily",
    title: "Fridge temperature",
    description: "",
    status: "todo",
    priority: "normal",
    due_at: "2026-10-21T09:30:00+05:00",
    for_date: "2026-10-21",
    proof: "photo",
    needs_confirmation: true,
    proof_text: "",
    proof_photo: null,
    proof_thumb: null,
    assignee: { id: 7, name: "Alisher Valiyev", position: null },
    created_by: { id: 3, name: "Dilnoza Karimova", position: null },
    confirmed_by: null,
    checklist: [],
    reminder: null,
    repeat_weekdays: [0, 1, 2, 3, 4, 5, 6],
    started_at: null,
    completed_at: null,
    confirmed_at: null,
    is_overdue: false,
    actions: [],
    created_at: "2026-10-21T00:00:00Z",
    routine: 5,
    ...fields,
  } as unknown as Task;
}

function Sheet() {
  const { sheet } = useNavigation();
  return <div data-testid="sheet">{sheet ? JSON.stringify(sheet) : ""}</div>;
}

function renderWith(node: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } });
  const membership = { id: 3, company: { id: 1, name: "Demo Dorixona", timezone: "Asia/Tashkent" }, status: "approved", is_onboarded: true, permissions: ["tasks.confirm"] } as unknown as Membership;
  const me = { id: 1, telegram_id: 1002, first_name: "Bekzod", last_name: "Mirzayev", phone: "", memberships: [membership] } as unknown as Me;
  return render(
    <QueryClientProvider client={client}>
      <I18nProvider lang="en">
        <ToastProvider>
          <SessionProvider me={me}>
            <NavigationProvider>
              {node}
              <Sheet />
            </NavigationProvider>
          </SessionProvider>
        </ToastProvider>
      </I18nProvider>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  api.mockReset();
});

describe("routine helpers", () => {
  it("count today's routines, with runs waiting for a check as finished", () => {
    const tasks = [
      task({ status: "done", completed_at: "2026-10-21T09:20:00+05:00" }),
      task({ status: "review", completed_at: "2026-10-21T09:40:00+05:00" }),
      task({ status: "todo" }),
      task({ status: "cancelled" }),
      task({ status: "todo", due_at: "2026-10-22T09:30:00+05:00" }), // tomorrow's
      task({ kind: "assigned", routine: null }), // one-off work
    ];
    expect(routineProgress(tasks, ctx())).toEqual({ done: 2, total: 3 });
  });

  it("group runs by routine (the busiest first), falling back to the title", () => {
    const groups = groupByRoutine([
      task({ routine: 5, completed_at: "2026-10-21T09:40:00+05:00", assignee: { id: 8, name: "Madina", position: null } }),
      task({ routine: 9, title: "Expiry dates" }),
      task({ routine: 5, completed_at: "2026-10-21T09:10:00+05:00" }),
      task({ routine: undefined, title: "Opening checklist" }),
    ]);
    expect(groups.map((group) => [group.title, group.tasks.length])).toEqual([
      ["Fridge temperature", 2],
      ["Expiry dates", 1],
      ["Opening checklist", 1],
    ]);
    // In the order they were finished.
    expect(groups[0].tasks[0].completed_at).toBe("2026-10-21T09:10:00+05:00");
  });
});

describe("the Routines tab", () => {
  const tasks = () => [
    task({ status: "done", completed_at: "2026-10-21T09:12:00+05:00", proof_text: "+4 °C", proof: "text" }),
    task({ title: "Opening checklist", status: "done", completed_at: "2026-10-21T08:41:00+05:00", proof_thumb: "/media/proofs/thumbs/a.webp" }),
    task({ title: "Expiry dates", status: "review", completed_at: "2026-10-21T09:50:00+05:00" }),
    task({ title: "Clean the counter", due_at: "2026-10-21T12:00:00+05:00" }),
  ];

  it("shows today's progress and keeps finished runs folded under Done today", () => {
    const { container } = renderWith(<RoutinesTab tasks={tasks()} ctx={ctx()} onOpen={() => undefined} onTick={() => undefined} />);
    expect(screen.getByText("3 of 4 routines done today")).toBeTruthy();
    expect(screen.getByText("Routines come back every day they're due.")).toBeTruthy();
    expect(screen.getByText("Clean the counter")).toBeTruthy();
    // Waiting for a check stays in sight: it may still come back.
    expect(screen.getByText("Expiry dates")).toBeTruthy();
    const toggle = screen.getByRole("button", { name: /Done today/ });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByText("Opening checklist")).toBeNull();

    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    // When, and how: the note it was finished with, or the photo.
    expect(screen.getByText("Done at 09:12 · “+4 °C”")).toBeTruthy();
    expect(screen.getByText("Opening checklist")).toBeTruthy();
    expect(container.querySelector("img.row-thumb")?.getAttribute("src")).toBe("/media/proofs/thumbs/a.webp");
  });

  it("says when there are no routines today", () => {
    renderWith(<RoutinesTab tasks={[]} ctx={ctx()} onOpen={() => undefined} onTick={() => undefined} />);
    expect(screen.getByText("No routines today")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Done today/ })).toBeNull();
  });
});

describe("To check", () => {
  const queue = () => [
    task({ id: 1, status: "review", completed_at: "2026-10-21T09:12:00+05:00", proof_thumb: "/media/a.webp", actions: ["confirm", "return"] }),
    task({ id: 2, status: "review", completed_at: "2026-10-21T09:20:00+05:00", proof_thumb: "/media/b.webp", assignee: { id: 8, name: "Madina Saidova", position: null }, actions: ["confirm", "return"] }),
    task({ id: 3, status: "review", kind: "assigned", routine: null, title: "Count the safe", completed_at: "2026-10-21T08:00:00+05:00", actions: ["confirm", "return"] }),
  ];

  it("groups a routine's runs with their photos, apart from one-off tasks", () => {
    const { container } = renderWith(<ReviewQueue tasks={queue()} loading={false} error={null} onRetry={() => undefined} ctx={ctx()} onOpen={() => undefined} />);
    const card = container.querySelector(".routine-check") as HTMLElement;
    expect(within(card).getByText("Fridge temperature")).toBeTruthy();
    expect(within(card).getByText("Every day · 2 to check")).toBeTruthy();
    expect([...card.querySelectorAll(".run-tile img")].map((img) => img.getAttribute("src"))).toEqual(["/media/a.webp", "/media/b.webp"]);
    expect(within(card).getByRole("button", { name: "Confirm all (2)" })).toBeTruthy();
    // One-off work keeps the one-by-one review, under its own heading.
    expect(screen.getByText("One-off tasks")).toBeTruthy();
    expect(card.textContent).not.toContain("Count the safe");
    expect(screen.getByText("Count the safe")).toBeTruthy();
  });

  it("puts a routine's Confirm under its name, above the runs, and lets one run take the card's width", () => {
    const expiry = task({ id: 4, routine: 9, title: "Expiry dates", status: "review", completed_at: "2026-10-21T09:40:00+05:00", actions: ["confirm", "return"] });
    const { container } = renderWith(<ReviewQueue tasks={[...queue(), expiry]} loading={false} error={null} onRetry={() => undefined} ctx={ctx()} onOpen={() => undefined} />);
    const [fridge, single] = [...container.querySelectorAll<HTMLElement>(".routine-check")];
    // Never at the card's foot, where the tab bar and the (+) cover the end of the screen.
    const confirmAll = within(fridge).getByRole("button", { name: "Confirm all (2)" });
    const grid = fridge.querySelector(".routine-check-grid") as HTMLElement;
    expect(confirmAll.compareDocumentPosition(grid) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(grid.classList.contains("routine-check-grid--one")).toBe(false);
    // One run waiting: "Confirm", and the run across the whole card.
    expect(within(single).getByRole("button", { name: "Confirm" })).toBeTruthy();
    expect(single.querySelector(".routine-check-grid")?.classList.contains("routine-check-grid--one")).toBe(true);
  });

  it("confirms all of a routine's runs in one go, after a moment to undo it", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      api.mockResolvedValue({ done: 2, failed: 0, results: [{ id: 1, ok: true, error: "" }, { id: 2, ok: true, error: "" }] });
      renderWith(<ReviewQueue tasks={queue()} loading={false} error={null} onRetry={() => undefined} ctx={ctx()} onOpen={() => undefined} />);
      fireEvent.click(screen.getByRole("button", { name: "Confirm all (2)" }));
      // Said at once, with Undo; nothing has gone out yet (the server can't take a confirm back).
      expect(await screen.findByText("2 tasks confirmed")).toBeTruthy();
      expect(screen.getByRole("button", { name: "Undo" })).toBeTruthy();
      expect(api).not.toHaveBeenCalled();
      await act(() => vi.advanceTimersByTimeAsync(5000));
      expect(api).toHaveBeenCalledWith("/companies/1/tasks/confirm/", { json: { ids: [1, 2] }, keepalive: true });
    } finally {
      vi.useRealTimers();
    }
  });

  it("takes Confirm all back with Undo before anything goes out", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      renderWith(<ReviewQueue tasks={queue()} loading={false} error={null} onRetry={() => undefined} ctx={ctx()} onOpen={() => undefined} />);
      fireEvent.click(screen.getByRole("button", { name: "Confirm all (2)" }));
      fireEvent.click(await screen.findByRole("button", { name: "Undo" }));
      expect(await screen.findByText("Not confirmed. It's back in To check.")).toBeTruthy();
      await act(() => vi.advanceTimersByTimeAsync(6000));
      expect(api).not.toHaveBeenCalled();
    } finally {
      vi.useRealTimers();
    }
  });

  it("sends one run back with a reason, from its own tile", () => {
    renderWith(<ReviewQueue tasks={queue()} loading={false} error={null} onRetry={() => undefined} ctx={ctx()} onOpen={() => undefined} />);
    fireEvent.click(screen.getByRole("button", { name: "Send back: Madina Saidova" }));
    expect(screen.getByTestId("sheet").textContent).toBe(JSON.stringify({ kind: "return", taskId: 2 }));
  });

  it("opens a run to see it whole", () => {
    const onOpen = vi.fn();
    renderWith(<ReviewQueue tasks={queue()} loading={false} error={null} onRetry={() => undefined} ctx={ctx()} onOpen={onOpen} />);
    fireEvent.click(screen.getByRole("button", { name: "Open Alisher Valiyev's run" }));
    expect(onOpen).toHaveBeenCalledWith(expect.objectContaining({ id: 1 }));
  });
});
