/**
 * The (+) sheet: what the typed title says about when is read on the server and shown back with
 * the weekday and the date before anything is saved; "Not a date" keeps the words; the sheet works
 * as before on a backend that can't read dates; managers give tasks to colleagues.
 */
import { act, cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../api/client";
import { keys } from "../api/hooks";
import type { Membership } from "../api/types";
import { resetQuickAdd } from "../lib/quickAdd";
import { membership, NOW, person, renderApp } from "../test/harness";

const api = vi.hoisted(() => vi.fn());
vi.mock("../api/client", async (importOriginal) => ({ ...(await importOriginal<typeof import("../api/client")>()), api }));

const TOMORROW_18 = "2026-10-22T18:00:00+05:00";
const READ = { title: "Kassani sanash", due_at: TOMORROW_18, due_label: "Tomorrow, 22 Oct (Thu), 18:00", priority: null, repeat: null };

type Call = [string, { json?: Record<string, unknown>; method?: string } | undefined];
const calls = (path: string) => (api.mock.calls as Call[]).filter(([called]) => called === path);
const created = () => calls("/companies/1/tasks/").map(([, options]) => options?.json);

function answer(parse: unknown = READ) {
  api.mockImplementation((path: string) => {
    if (path === "/companies/1/tasks/parse/") return typeof parse === "function" ? (parse as () => unknown)() : Promise.resolve(parse);
    if (path === "/companies/1/tasks/") return Promise.resolve({ id: 900 });
    if (path === "/companies/1/members/") {
      return Promise.resolve([
        { id: 7, name: "Bekzod Mirzayev", position: "Head" },
        { id: 12, name: "Madina Saidova", position: "Pharmacist" },
      ]);
    }
    return Promise.reject(new Error(`unexpected ${path}`));
  });
}

function openSheet(permissions: Membership["permissions"] = []) {
  const me = person([membership({ id: 7, permissions, first_name: "Bekzod", last_name: "Mirzayev" })]);
  return renderApp(null, {
    me,
    init: { sheet: { kind: "add" } },
    seed: (client) => client.setQueryData(keys.members(1), undefined),
  });
}

const title = () => screen.getByLabelText("What needs doing?") as HTMLInputElement;
const type = (text: string) => fireEvent.change(title(), { target: { value: text } });
const add = () => fireEvent.click(screen.getByRole("button", { name: /Add task|Give task/ }));

beforeEach(() => {
  vi.useFakeTimers({ now: NOW, shouldAdvanceTime: true });
  resetQuickAdd();
});

afterEach(() => {
  cleanup();
  api.mockReset();
  vi.useRealTimers();
});

describe("quick add in the (+) sheet", () => {
  it("reads the date in the title and saves exactly what it showed", async () => {
    answer();
    openSheet();
    type("Kassani sanash ertaga 18:00");
    expect(await screen.findByText("Tomorrow, 22 Oct (Thu), 18:00")).toBeTruthy();
    expect(screen.getByText("Title: “Kassani sanash”")).toBeTruthy();
    expect(calls("/companies/1/tasks/parse/").at(-1)?.[1]?.json).toEqual({ text: "Kassani sanash ertaga 18:00" });
    // The reading is the "When": no second set of day chips to contradict it.
    expect(screen.queryByRole("button", { name: "Tomorrow" })).toBeNull();
    add();
    await waitFor(() => expect(created()).toEqual([{ title: "Kassani sanash", due_at: TOMORROW_18, repeat: "none" }]));
  });

  it("keeps the words in the title with Not a date", async () => {
    answer();
    openSheet();
    type("Juma namozi");
    fireEvent.click(await screen.findByRole("button", { name: "Not a date" }));
    expect(screen.queryByText("Tomorrow, 22 Oct (Thu), 18:00")).toBeNull();
    // The plain day chips are back: the next full hour today is the default.
    expect(screen.getByRole("button", { name: "Today" }).getAttribute("aria-pressed")).toBe("true");
    add();
    await waitFor(() => expect(created()).toEqual([{ title: "Juma namozi", due_at: "2026-10-21T06:00:00.000Z", repeat: "none" }]));
  });

  it("works as before on a backend that can't read dates, and stops asking it", async () => {
    answer(() => Promise.reject(new ApiError(405, { detail: 'Method "POST" not allowed.' })));
    openSheet();
    type("Kassani sanash ertaga 18:00");
    await waitFor(() => expect(calls("/companies/1/tasks/parse/")).toHaveLength(1));
    type("Kassani sanash ertaga 18:00 va hisobot");
    await act(() => vi.advanceTimersByTimeAsync(600));
    expect(calls("/companies/1/tasks/parse/")).toHaveLength(1);
    // Nothing read: the placeholder no longer suggests typing a date.
    expect(title().placeholder).toBe("e.g. Check the expiry dates");
    add();
    await waitFor(() => expect(created()[0]).toMatchObject({ title: "Kassani sanash ertaga 18:00 va hisobot", due_at: "2026-10-21T06:00:00.000Z" }));
  });

  it("makes a task without a deadline, and then offers no repeat", async () => {
    answer({ title: "Shelf labels", due_at: null, due_label: null, priority: null, repeat: null });
    openSheet();
    type("Shelf labels");
    fireEvent.click(screen.getByRole("button", { name: "No deadline" }));
    expect(screen.queryByLabelText("Time")).toBeNull();
    expect(screen.queryByLabelText("Repeat")).toBeNull();
    add();
    await waitFor(() => expect(created()).toEqual([{ title: "Shelf labels", due_at: null, repeat: "none" }]));
  });

  it("asks for the title when the text was only a date", async () => {
    answer({ ...READ, title: "" });
    openSheet();
    type("ertaga 18:00");
    expect(await screen.findByText("Now add what needs doing.")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Add task" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("shows the reading first when Add comes before the text was read", async () => {
    answer();
    openSheet();
    type("Kassani sanash ertaga 18:00");
    fireEvent.keyDown(title(), { key: "Enter" });
    // Read at once, shown, not saved: a deadline nobody saw is never set.
    expect(await screen.findByText("Tomorrow, 22 Oct (Thu), 18:00")).toBeTruthy();
    expect(created()).toEqual([]);
    fireEvent.keyDown(title(), { key: "Enter" });
    await waitFor(() => expect(created()).toHaveLength(1));
  });

  it("rolls a time that has passed today to tomorrow, and says so", async () => {
    answer({ title: "Fridge", due_at: null, due_label: null, priority: null, repeat: null });
    openSheet();
    type("Fridge");
    fireEvent.change(screen.getByLabelText("Time"), { target: { value: "09:00" } });
    expect(screen.getByText("Today's 09:00 has passed, so it's set for tomorrow.")).toBeTruthy();
    add();
    await waitFor(() => expect(created()[0]).toMatchObject({ due_at: "2026-10-22T04:00:00.000Z" }));
  });
});

describe("giving a task from the (+) sheet", () => {
  it("lets whoever hands out work give it to a colleague, with urgency, photo and check", async () => {
    answer({ title: "Kassa lentasi", due_at: null, due_label: null, priority: null, repeat: null });
    openSheet(["tasks.assign"]);
    const forWhom = (await screen.findByLabelText("For")) as HTMLSelectElement;
    await waitFor(() => expect(forWhom.options.length).toBe(2));
    // Me first, then the team without me.
    expect([...forWhom.options].map((option) => option.textContent)).toEqual(["Me", "Madina Saidova · Pharmacist"]);
    fireEvent.change(forWhom, { target: { value: "12" } });
    type("Kassa lentasi");
    fireEvent.click(screen.getByRole("button", { name: "Urgent" }));
    fireEvent.click(screen.getByRole("button", { name: "Photo needed" }));
    fireEvent.click(screen.getByRole("button", { name: "I'll check it" }));
    fireEvent.click(screen.getByRole("button", { name: "Description and checklist" }));
    fireEvent.change(screen.getByLabelText("Description (optional)"), { target: { value: "From the back room" } });
    fireEvent.click(screen.getByRole("button", { name: "Add a step" }));
    fireEvent.change(screen.getByLabelText("Step 1"), { target: { value: "Two rolls" } });
    add();
    await waitFor(() =>
      expect(created()).toEqual([
        {
          title: "Kassa lentasi",
          due_at: "2026-10-21T06:00:00.000Z",
          repeat: "none",
          priority: "urgent",
          assignee_id: 12,
          proof: "photo",
          needs_confirmation: true,
          description: "From the back room",
          checklist: ["Two rolls"],
        },
      ]),
    );
    expect(await screen.findByText("Task given: Madina Saidova.")).toBeTruthy();
  });

  it("says a colleague's task won't repeat instead of dropping the repeat silently", async () => {
    answer({ title: "Kassani sanash", due_at: TOMORROW_18, due_label: "Tomorrow, 22 Oct (Thu), 18:00", priority: null, repeat: "daily", repeat_weekdays: [0, 1, 2, 3, 4, 5, 6] });
    openSheet(["tasks.assign"]);
    const forWhom = (await screen.findByLabelText("For")) as HTMLSelectElement;
    await waitFor(() => expect(forWhom.options.length).toBe(2));
    type("Kassani sanash har kuni 18:00");
    // The reading is in (the repeat select's own "Every day" option doesn't count).
    expect(await screen.findByText("Tomorrow, 22 Oct (Thu), 18:00")).toBeTruthy();
    expect(screen.getByText("Every day", { selector: ".qa-read-tag" })).toBeTruthy();
    fireEvent.change(forWhom, { target: { value: "12" } });
    expect(screen.queryByText("Every day")).toBeNull();
    expect(screen.getByText("A task given to a colleague doesn't repeat: routines are set up on the dashboard.")).toBeTruthy();
  });

  it("shows no For field to someone who doesn't hand out work", () => {
    answer();
    openSheet();
    expect(screen.queryByLabelText("For")).toBeNull();
    expect(calls("/companies/1/members/")).toHaveLength(0);
  });
});
