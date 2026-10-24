/**
 * The task screen with tonight's details: priority and reward, who sent it back and why, steps
 * asked about before Done, Undo after Done, Confirm with a moment to undo, @ to bring someone in,
 * blockers and more-time requests as each side sees them, the task menu, and seen receipts.
 */
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../api/client";
import { keys } from "../api/hooks";
import type { Activity, Comment, Task } from "../api/types";
import { useNavigation } from "../state/navigation";
import { makeTask, membership, navigationState, NOW, person, renderApp } from "../test/harness";
import { returnInfo, TaskDetail } from "./TaskDetail";

const api = vi.hoisted(() => vi.fn());
vi.mock("../api/client", async (importOriginal) => ({ ...(await importOriginal<typeof import("../api/client")>()), api }));

type Options = { json?: unknown; method?: string; keepalive?: boolean } | undefined;
type Call = [string, Options];
const callsTo = (path: string) => (api.mock.calls as Call[]).filter(([called]) => called === path);

/**
 * Answers by path: the handlers given (matched on the end of the path, or a whole path), then what
 * the screen refetches after a change (the task, its comments, the feed, the numbers, lists).
 */
function routes(task: Task, handlers: Record<string, (options: Options) => unknown> = {}) {
  api.mockImplementation((path: string, options: Options) => {
    for (const [end, handler] of Object.entries(handlers)) {
      if (path.endsWith(end)) {
        try {
          return Promise.resolve(handler(options));
        } catch (error) {
          return Promise.reject(error);
        }
      }
    }
    if (path.endsWith("/comments/")) return Promise.resolve([]);
    if (path.includes("/activity/")) return Promise.resolve({ results: [] });
    if (path.endsWith("/summary/")) return Promise.resolve({ quiet_from: null, quiet_until: null });
    if (path.includes("/tasks/?")) return Promise.resolve({ results: [] });
    if (path.endsWith("/members/")) return Promise.resolve([]);
    if (path === `/companies/1/tasks/${task.id}/`) return Promise.resolve(task);
    return Promise.reject(new Error(`unexpected ${path}`));
  });
}

function show(task: Task, options: { me?: ReturnType<typeof person>; comments?: Comment[]; activity?: Activity[] } = {}) {
  return renderApp(<TaskDetail taskId={task.id} />, {
    me: options.me,
    init: { tab: "tasks", stack: [{ feature: "core", page: "task", params: { id: task.id } }] },
    seed: (client) => {
      client.setQueryData(keys.task(1, task.id), task);
      client.setQueryData(keys.comments(1, task.id), options.comments ?? []);
      client.setQueryData(keys.activity(1), options.activity ?? []);
      client.setQueryData(keys.summary(1), { quiet_from: null, quiet_until: null });
      client.setQueryData(keys.review(1), []);
      client.setQueryData(keys.members(1), []);
    },
  });
}

const manager = () => person([membership({ id: 3, first_name: "Bekzod", last_name: "Mirzayev", permissions: ["tasks.assign", "tasks.confirm"] })]);

/** The task on top of the stack, as the app renders it (so opening the next one shows it). */
function NextTask() {
  const { stack } = useNavigation();
  const top = stack.at(-1);
  return top ? <TaskDetail key={String(top.params?.id)} taskId={Number(top.params?.id)} /> : null;
}

beforeEach(() => {
  vi.useFakeTimers({ now: NOW, shouldAdvanceTime: true });
});

afterEach(() => {
  cleanup();
  api.mockReset();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("what the task screen shows", () => {
  it("shows urgency and the reward next to the status", () => {
    show(makeTask({ priority: "urgent", reward: "20000.00" }));
    expect(screen.getByText("Urgent")).toBeTruthy();
    expect(screen.getAllByText(/\+20,000/).length).toBeGreaterThan(0);
    expect(screen.getByText("Reward")).toBeTruthy();
  });

  it("names who sent it back and their reason, not the latest comment", () => {
    const task = makeTask({ status: "returned", actions: ["complete"] });
    const comments = [
      { id: 1, author: { id: 3, name: "Bekzod Mirzayev", position: null }, text: "Add the terminal total, please", created_at: "2026-10-21T09:00:00+05:00" },
      { id: 2, author: { id: 7, name: "Alisher Valiyev", position: null }, text: "Terminal: 1 830 000", created_at: "2026-10-21T09:10:00+05:00" },
    ] as Comment[];
    const activity = [
      { id: 9, kind: "returned", actor: { id: 3, name: "Bekzod Mirzayev", position: null }, text: "Add the terminal total, please", task: { id: task.id, title: task.title }, is_read: false, created_at: "2026-10-21T09:00:00+05:00" },
    ] as unknown as Activity[];
    show(task, { comments, activity });
    expect(screen.getByText("Bekzod Mirzayev sent this back")).toBeTruthy();
    expect(screen.getByText("“Add the terminal total, please”")).toBeTruthy();
    // Without the feed entry: the latest word from someone other than the worker.
    expect(returnInfo(task, comments, undefined)).toEqual({ name: "Bekzod Mirzayev", reason: "Add the terminal total, please" });
  });

  it("tells the giver whether the worker has opened it", () => {
    show(makeTask({ seen_at: "2026-10-21T09:12:00+05:00", actions: ["edit", "cancel"] }), { me: manager() });
    expect(screen.getByText("Seen 09:12")).toBeTruthy();
    cleanup();
    show(makeTask({ seen_at: null, actions: ["edit", "cancel"] }), { me: manager() });
    expect(screen.getByText("Not seen yet")).toBeTruthy();
    cleanup();
    // A backend that doesn't say: nothing, rather than a false "not seen".
    show(makeTask({ actions: ["edit", "cancel"] }), { me: manager() });
    expect(screen.queryByText("Not seen yet")).toBeNull();
  });

  it("shows a reviewer the steps without boxes that look tappable", () => {
    const task = makeTask({ status: "review", actions: ["confirm", "return"], checklist: [{ id: 1, text: "Till balance", is_done: true }] });
    show(task, { me: manager() });
    const step = screen.getByRole("checkbox", { name: /Till balance/ });
    expect(step.tagName).toBe("DIV");
    expect(step.getAttribute("aria-disabled")).toBe("true");
  });
});

describe("finishing and undoing", () => {
  it("asks about unticked steps, ticks them and finishes, then offers Undo", async () => {
    const task = makeTask({ checklist: [{ id: 11, text: "Till balance", is_done: true }, { id: 12, text: "Z-report", is_done: false }] });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    routes(task, {
      "/checklist/12/": () => ({ ...task, checklist: task.checklist.map((item) => ({ ...item, is_done: true })) }),
      "/complete/": () => ({ ...task, status: "done" }),
      "/reopen/": () => ({ ...task, status: "todo" }),
    });
    show(task);
    fireEvent.click(screen.getByRole("button", { name: "Mark as done" }));
    await waitFor(() => expect(window.confirm).toHaveBeenCalledWith("1 step isn't ticked yet."));
    await waitFor(() => expect(callsTo(`/companies/1/tasks/${task.id}/complete/`)).toHaveLength(1));
    expect(callsTo(`/companies/1/tasks/${task.id}/checklist/12/`)[0][1]?.json).toEqual({ is_done: true });
    fireEvent.click(await screen.findByRole("button", { name: "Undo" }));
    await waitFor(() => expect(callsTo(`/companies/1/tasks/${task.id}/reopen/`)).toHaveLength(1));
    expect(await screen.findByText("Back on your list.")).toBeTruthy();
  });

  it("goes back without finishing when the steps aren't done", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(false);
    const task = makeTask({ checklist: [{ id: 12, text: "Z-report", is_done: false }] });
    routes(task);
    show(task);
    fireEvent.click(screen.getByRole("button", { name: "Mark as done" }));
    await waitFor(() => expect(window.confirm).toHaveBeenCalled());
    await act(() => vi.advanceTimersByTimeAsync(50));
    expect(callsTo(`/companies/1/tasks/${task.id}/complete/`)).toHaveLength(0);
    expect(callsTo(`/companies/1/tasks/${task.id}/checklist/12/`)).toHaveLength(0);
  });

  it("says plainly when Undo can't work on this backend", async () => {
    const task = makeTask();
    routes(task, {
      "/complete/": () => ({ ...task, status: "done" }),
      "/reopen/": () => {
        throw new ApiError(404, null);
      },
    });
    show(task);
    fireEvent.click(screen.getByRole("button", { name: "Mark as done" }));
    fireEvent.click(await screen.findByRole("button", { name: "Undo" }));
    expect(await screen.findByText("Couldn't undo it. Open the task to change it.")).toBeTruthy();
  });

  it("confirms after a moment to undo, and opens the next thing to check", async () => {
    const task = makeTask({ status: "review", actions: ["confirm", "return"] });
    const next = makeTask({ status: "review", title: "Fridge", actions: ["confirm", "return"] });
    routes(task, { "/confirm/": () => ({ ...task, status: "done" }) });
    const view = show(task, { me: manager() });
    act(() => view.client.setQueryData(keys.review(1), [task, next]));
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    expect(await screen.findByText("Confirmed.")).toBeTruthy();
    expect(navigationState().stack.at(-1)?.params?.id).toBe(next.id);
    expect(callsTo(`/companies/1/tasks/${task.id}/confirm/`)).toHaveLength(0);
    await act(() => vi.advanceTimersByTimeAsync(5000));
    expect(callsTo(`/companies/1/tasks/${task.id}/confirm/`)[0][1]).toEqual({ method: "POST", keepalive: true });
  });
});

describe("confirming safely", () => {
  it("takes a double tap as one Confirm: the next task isn't confirmed unseen", async () => {
    const task = makeTask({ status: "review", actions: ["confirm", "return"] });
    const next = makeTask({ status: "review", title: "Fridge", actions: ["confirm", "return"] });
    routes(task, { "/confirm/": () => ({ status: "done" }) });
    const view = renderApp(<NextTask />, {
      me: manager(),
      init: { tab: "tasks", stack: [{ feature: "core", page: "task", params: { id: task.id } }] },
      seed: (client) => {
        for (const item of [task, next]) {
          client.setQueryData(keys.task(1, item.id), item);
          client.setQueryData(keys.comments(1, item.id), []);
        }
        client.setQueryData(keys.activity(1), []);
        client.setQueryData(keys.summary(1), {});
        client.setQueryData(keys.review(1), [task, next]);
        client.setQueryData(keys.members(1), []);
      },
    });
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    // Now on the next task; the second tap of the double tap lands on its Confirm.
    expect(await screen.findByRole("heading", { name: "Fridge" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await act(() => vi.advanceTimersByTimeAsync(6000));
    expect(callsTo(`/companies/1/tasks/${task.id}/confirm/`)).toHaveLength(1);
    expect(callsTo(`/companies/1/tasks/${next.id}/confirm/`)).toHaveLength(0);
    expect(view.client.getQueryData(keys.review(1))).toBeTruthy();
  });

  it("keeps a typed comment when Ask for help adds the mention", async () => {
    const task = makeTask({
      due_at: "2026-10-21T09:00:00+05:00",
      reminder: { every_minutes: 20, sent: 1, max_reminders: 12, escalate_after: 3, next_at: null, escalated_at: null, escalate_to: "Bekzod Mirzayev", snooze_minutes: 10, snoozes_left: 1, snoozed_until: null },
    });
    show(task);
    const box = screen.getByPlaceholderText("Write a comment…") as HTMLInputElement;
    fireEvent.change(box, { target: { value: "The terminal receipt is missing", selectionStart: 31 } });
    fireEvent.click(screen.getByRole("button", { name: "Ask for help" }));
    await waitFor(() => expect(box.value).toBe("@Bekzod The terminal receipt is missing"));
  });
});

describe("comments with @", () => {
  it("offers the task's people after @ and sends who was mentioned", async () => {
    const task = makeTask();
    api.mockImplementation((_path: string, options: { json?: { text: string } }) =>
      Promise.resolve({ id: 70, author: { id: 7, name: "Alisher Valiyev", position: null }, text: options.json?.text, created_at: NOW.toISOString() }),
    );
    show(task);
    const box = screen.getByPlaceholderText("Write a comment…") as HTMLInputElement;
    fireEvent.change(box, { target: { value: "@", selectionStart: 1 } });
    const list = await screen.findByRole("listbox", { name: "Mention someone" });
    // The giver, not me.
    expect(within(list).getByText("Bekzod Mirzayev")).toBeTruthy();
    expect(within(list).getByText("Gave the task")).toBeTruthy();
    expect(within(list).queryByText("Alisher Valiyev")).toBeNull();
    fireEvent.click(within(list).getByRole("option"));
    expect(box.value).toBe("@Bekzod ");
    expect(screen.getByText("Gets it in the bot: Bekzod Mirzayev")).toBeTruthy();
    fireEvent.change(box, { target: { value: "@Bekzod the terminal receipt is missing", selectionStart: 39 } });
    fireEvent.keyDown(box, { key: "Enter" });
    await waitFor(() =>
      expect(callsTo(`/companies/1/tasks/${task.id}/comments/`)[0][1]?.json).toEqual({ text: "@Bekzod the terminal receipt is missing", mentions: [3] }),
    );
  });

  it("sends no mentions when the name was deleted again", async () => {
    const task = makeTask();
    api.mockResolvedValue({ id: 71, author: null, text: "x", created_at: NOW.toISOString() });
    show(task);
    const box = screen.getByPlaceholderText("Write a comment…") as HTMLInputElement;
    fireEvent.change(box, { target: { value: "@", selectionStart: 1 } });
    fireEvent.click(within(await screen.findByRole("listbox")).getByRole("option"));
    fireEvent.change(box, { target: { value: "never mind", selectionStart: 10 } });
    fireEvent.keyDown(box, { key: "Enter" });
    await waitFor(() => expect(callsTo(`/companies/1/tasks/${task.id}/comments/`)[0][1]?.json).toEqual({ text: "never mind" }));
  });
});

describe("can't do it and more time", () => {
  it("lets the worker report a blocker or ask for time only where the backend knows them", () => {
    show(makeTask({ blocker: null, extension: null }));
    expect(screen.getByRole("button", { name: "Can't do it" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Need more time" })).toBeTruthy();
    cleanup();
    show(makeTask());
    expect(screen.queryByRole("button", { name: "Can't do it" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Need more time" })).toBeNull();
  });

  it("sends the reason the worker picked", async () => {
    const task = makeTask({ blocker: null, extension: null });
    routes(task, { "/blocker/": () => ({ ...task, blocker: { reason_code: "no_stock", note: "", at: NOW.toISOString() } }) });
    show(task);
    fireEvent.click(screen.getByRole("button", { name: "Can't do it" }));
    fireEvent.click(await screen.findByRole("radio", { name: "Out of stock" }));
    fireEvent.click(screen.getByRole("button", { name: "Tell my manager" }));
    await waitFor(() => expect(callsTo(`/companies/1/tasks/${task.id}/blocker/`)[0][1]?.json).toEqual({ reason_code: "no_stock", note: "" }));
    expect(await screen.findByText("Your manager knows. Reminders are paused.")).toBeTruthy();
  });

  it("shows the giver the blocker with what they can do", async () => {
    const task = makeTask({ actions: ["edit", "cancel"], blocker: { reason_code: "broken", note: "The fridge display is off", at: "2026-10-21T09:40:00+05:00" } });
    routes(task, { "/blocker/resolve/": () => ({ ...task, status: "cancelled", blocker: null }) });
    show(task, { me: manager() });
    expect(screen.getByText("Alisher Valiyev can't do it: equipment broken")).toBeTruthy();
    expect(screen.getByText("“The fridge display is off”")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Give to someone else" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "New time" }));
    expect(navigationState().sheet).toEqual({ kind: "due", taskId: task.id, resolve: true });
    fireEvent.click(screen.getByRole("button", { name: "Cancel task" }));
    await waitFor(() => expect(callsTo(`/companies/1/tasks/${task.id}/blocker/resolve/`)[0][1]?.json).toEqual({ action: "cancel" }));
  });

  it("lets the giver allow more time in one tap", async () => {
    const until = "2026-10-21T19:00:00+05:00";
    const task = makeTask({ actions: ["edit", "cancel"], extension: { until, note: "Queue at the till", at: NOW.toISOString() } });
    routes(task, { "/extension/decide/": () => ({ ...task, due_at: until, extension: null }) });
    show(task, { me: manager() });
    expect(screen.getByText("Alisher Valiyev asks for more time")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Allow" }));
    await waitFor(() => expect(callsTo(`/companies/1/tasks/${task.id}/extension/decide/`)[0][1]?.json).toEqual({ approve: true }));
    expect(await screen.findByText("Deadline moved: today, 19:00.")).toBeTruthy();
  });
});

describe("the task menu", () => {
  it("deletes my own task after asking", async () => {
    const task = makeTask({ kind: "personal", created_by: null, actions: ["complete", "edit", "cancel"] });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    routes(task, { "/cancel/": () => ({ ...task, status: "cancelled" }) });
    show(task);
    fireEvent.click(screen.getByRole("button", { name: "More actions" }));
    fireEvent.click(await screen.findByRole("button", { name: "Delete task" }));
    await waitFor(() => expect(callsTo(`/companies/1/tasks/${task.id}/cancel/`)[0][1]?.json).toEqual({ stop_repeating: false }));
    expect(await screen.findByText("Task deleted.")).toBeTruthy();
    expect(navigationState().stack).toEqual([]);
  });

  it("edits the title", async () => {
    const task = makeTask({ kind: "personal", created_by: null, actions: ["complete", "edit", "cancel"] });
    routes(task);
    api.mockImplementationOnce((path: string, options: Options) =>
      options?.method === "PATCH" ? Promise.resolve({ ...task, title: "Count the till twice" }) : Promise.reject(new Error(path)),
    );
    show(task);
    fireEvent.click(screen.getByRole("button", { name: "More actions" }));
    fireEvent.click(await screen.findByRole("button", { name: "Edit" }));
    fireEvent.change(await screen.findByLabelText("Title"), { target: { value: "Count the till twice" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(callsTo(`/companies/1/tasks/${task.id}/`)[0][1]).toEqual({ method: "PATCH", json: { title: "Count the till twice", description: "" } }));
  });

  it("isn't there for someone who may only work on the task", () => {
    show(makeTask());
    expect(screen.queryByRole("button", { name: "More actions" })).toBeNull();
  });
});

describe("a link to a task in my other company", () => {
  it("finds it there and switches to that company", async () => {
    const task = makeTask({ id: 4040 });
    const me = person([membership({ companyId: 1 }), membership({ id: 70, companyId: 2, companyName: "Demo Distribyutor" })]);
    api.mockImplementation((path: string) => {
      if (path === "/companies/1/tasks/4040/") return Promise.reject(new ApiError(404, { detail: "Not found." }));
      if (path === "/companies/2/tasks/4040/") return Promise.resolve(task);
      if (path.startsWith("/companies/2/")) return Promise.resolve(path.includes("comments") ? [] : { results: [] });
      return Promise.reject(new ApiError(404, { detail: "Not found." }));
    });
    renderApp(<TaskDetail taskId={4040} />, { me });
    expect(await screen.findByRole("heading", { name: "Count the till" })).toBeTruthy();
    expect(localStorage.getItem("daybook.company")).toBe("2");
    localStorage.removeItem("daybook.company");
  });
});
