/**
 * The Tasks screen: urgency on rows, empty lists that teach, and "Given by me" for whoever hands
 * out work (what needs them first, then work to check, then the rest, with seen receipts).
 */
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { keys } from "../api/hooks";
import type { Membership, Task } from "../api/types";
import { resetQuickAdd } from "../lib/quickAdd";
import { makeTask, membership, navigationState, NOW, person, renderApp } from "../test/harness";
import { Tasks } from "./Tasks";

const api = vi.hoisted(() => vi.fn((_path: string): Promise<unknown> => Promise.reject(new Error("no network in tests"))));
vi.mock("../api/client", async (importOriginal) => ({ ...(await importOriginal<typeof import("../api/client")>()), api }));

function show(options: { board?: Task[]; given?: Task[]; permissions?: Membership["permissions"]; tab?: "daily" | "assigned" | "personal" | "given" } = {}) {
  return renderApp(<Tasks />, {
    me: person([membership({ id: 3, permissions: options.permissions ?? [] })]),
    init: { tab: "tasks", tasksTab: options.tab ?? "assigned" },
    seed: (client) => {
      client.setQueryData(keys.board(1), options.board ?? []);
      client.setQueryData(keys.review(1), []);
      client.setQueryData(keys.given(1), options.given ?? []);
    },
  });
}

beforeEach(() => {
  vi.useFakeTimers({ now: NOW, shouldAdvanceTime: true });
  resetQuickAdd();
});
afterEach(() => {
  cleanup();
  api.mockReset();
  vi.useRealTimers();
});

describe("rows", () => {
  it("say Urgent with a flag, put urgent work first, and count down the last hour", () => {
    show({
      board: [
        makeTask({ title: "Shelf labels", due_at: "2026-10-21T10:20:00+05:00" }),
        makeTask({ title: "Insulin order", priority: "urgent", due_at: "2026-10-21T17:00:00+05:00" }),
      ],
    });
    const rows = screen.getAllByRole("button", { name: /Shelf labels|Insulin order/ });
    expect(rows.map((row) => within(row).getByText(/Shelf labels|Insulin order/).textContent)).toEqual(["Insulin order", "Shelf labels"]);
    expect(within(rows[0]).getByText("Urgent")).toBeTruthy();
    expect(within(rows[1]).getByText("20 min left")).toBeTruthy();
  });
});

describe("rewards on rows", () => {
  it("are in the company's own currency", () => {
    renderApp(<Tasks />, {
      me: person([membership({ id: 3, company: { id: 1, name: "Shop", timezone: "Asia/Tashkent", base_currency: "USD" } } as never)]),
      init: { tab: "tasks", tasksTab: "assigned" },
      seed: (client) => {
        client.setQueryData(keys.board(1), [makeTask({ title: "Count the till", reward: "10.00" })]);
        client.setQueryData(keys.review(1), []);
        client.setQueryData(keys.given(1), []);
      },
    });
    expect(screen.getByText(/\+\$10/)).toBeTruthy();
  });
});

describe("the round tick", () => {
  it("shows done at once and goes back if the server refuses", async () => {
    let refuse: (error: unknown) => void = () => undefined;
    api.mockImplementation((path: string) =>
      path.endsWith("/complete/") ? new Promise((_resolve, reject) => (refuse = reject)) : Promise.reject(new Error("no network in tests")),
    );
    show({ board: [makeTask({ title: "Shelf labels", due_at: "2026-10-21T17:00:00+05:00" })] });
    const tick = () => screen.getByRole("button", { name: /Shelf labels/ }).querySelector(".glyph") as HTMLElement;
    fireEvent.click(tick());
    await waitFor(() => expect(tick().className).toContain("glyph--done"));
    act(() => refuse(new Error("offline")));
    await waitFor(() => expect(tick().className).toContain("glyph--todo"));
    expect(await screen.findByText("No connection. Check your internet and try again.")).toBeTruthy();
  });
});

describe("groups by day", () => {
  it("keeps work a week or more away folded under Later", () => {
    show({
      board: [
        makeTask({ title: "Shelf labels", due_at: "2026-10-21T17:00:00+05:00" }),
        makeTask({ title: "Inventory count", due_at: "2026-11-14T10:00:00+05:00" }),
      ],
    });
    expect(screen.getByText("Today")).toBeTruthy();
    const later = screen.getByRole("button", { name: /Later/ });
    expect(later.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByText("Inventory count")).toBeNull();
    fireEvent.click(later);
    expect(screen.getByText("Inventory count")).toBeTruthy();
  });
});

describe("empty lists", () => {
  it("teach quick add on Mine and open the sheet", () => {
    show({ tab: "personal" });
    expect(screen.getByText("Add your own reminders. Try: “Order insulin tomorrow 10:00”.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "New task" }));
    expect(navigationState().sheet).toEqual({ kind: "add" });
  });

  it("say what will appear on Assigned", () => {
    show({ tab: "assigned" });
    expect(screen.getByText("No tasks from others")).toBeTruthy();
    expect(screen.getByText("When someone gives you one, it appears here and the bot tells you.")).toBeTruthy();
  });
});

describe("Given by me", () => {
  it("is a tab only for whoever hands out work", () => {
    show();
    expect(screen.queryByRole("tab", { name: /Given by me/ })).toBeNull();
    cleanup();
    show({ permissions: ["tasks.assign"] });
    expect(screen.getByRole("tab", { name: /Given by me/ })).toBeTruthy();
  });

  it("puts what needs me first, then work to check, then the rest, each with who has it", () => {
    const given = [
      makeTask({ title: "Count the safe", seen_at: "2026-10-21T09:12:00+05:00", assignee: { id: 12, name: "Madina Saidova", position: null } }),
      makeTask({ title: "Fridge", blocker: { reason_code: "broken", note: "", at: NOW.toISOString() }, assignee: { id: 12, name: "Madina Saidova", position: null } }),
      makeTask({ title: "Z-report", status: "review", completed_at: "2026-10-21T09:40:00+05:00" }),
      makeTask({ title: "My own", kind: "personal" }),
    ];
    show({ permissions: ["tasks.assign"], tab: "given", given });
    const heads = [...document.querySelectorAll(".section-head")].map((head) => head.firstElementChild?.textContent);
    expect(heads).toEqual(["Needs attention", "Waiting for your check", "In progress"]);
    expect(screen.getByText("Madina Saidova · Can't be done: equipment broken")).toBeTruthy();
    expect(screen.getByText("Alisher Valiyev · Done at 09:40")).toBeTruthy();
    expect(screen.getByText("Madina Saidova · Seen 09:12")).toBeTruthy();
    // Someone's own task never shows as work given.
    expect(screen.queryByText("My own")).toBeNull();
    // The tab counts what needs me.
    expect(within(screen.getByRole("tab", { name: /Given by me/ })).getByText("1")).toBeTruthy();
  });

  it("starts with a way to give the first task", () => {
    show({ permissions: ["tasks.assign"], tab: "given" });
    expect(screen.getByText("You haven't given anyone a task")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "New task" }));
    expect(navigationState().sheet).toEqual({ kind: "add" });
  });
});
