/**
 * The sheets about one task: snooze choices that say the deadline didn't move, send-back reasons
 * in one tap, more time, and the giver's answers to "can't do it" (someone else, a new time).
 */
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { keys } from "../api/hooks";
import type { Task } from "../api/types";
import type { Sheet } from "../state/navigation";
import { makeTask, membership, navigationState, NOW, person, renderApp } from "../test/harness";

const api = vi.hoisted(() => vi.fn());
vi.mock("../api/client", async (importOriginal) => ({ ...(await importOriginal<typeof import("../api/client")>()), api }));

type Call = [string, { json?: unknown; method?: string } | undefined];
const sent = (end: string) => (api.mock.calls as Call[]).filter(([path]) => path.endsWith(end)).map(([, options]) => options?.json);

function open(task: Task, sheet: Sheet, options: { members?: unknown[]; manager?: boolean } = {}) {
  const me = options.manager ? person([membership({ id: 3, permissions: ["tasks.assign"] })]) : person();
  api.mockImplementation((path: string, request: { json?: Record<string, unknown> } | undefined) => {
    if (path.endsWith("/members/")) return Promise.resolve(options.members ?? []);
    if (path.endsWith("/comments/")) return Promise.resolve([]);
    if (path.includes("/activity/") || path.includes("/tasks/?")) return Promise.resolve({ results: [] });
    if (path.endsWith("/summary/")) return Promise.resolve({});
    if (path.endsWith("/snooze/")) {
      const preset = request?.json?.preset;
      return Promise.resolve(
        preset === "tomorrow_morning"
          ? { ...task, due_at: "2026-10-22T09:00:00+05:00" }
          : { ...task, snoozed_until: preset === "1h" ? "2026-10-21T11:00:00+05:00" : "2026-10-21T10:15:00+05:00" },
      );
    }
    return Promise.resolve(task);
  });
  return renderApp(null, {
    me,
    init: { sheet },
    seed: (client) => client.setQueryData(keys.task(1, task.id), task),
  });
}

beforeEach(() => vi.useFakeTimers({ now: NOW, shouldAdvanceTime: true }));
afterEach(() => {
  cleanup();
  api.mockReset();
  vi.useRealTimers();
});

describe("finishing with proof", () => {
  it("sends the photo, and offers Undo after", async () => {
    const task = makeTask({ proof: "photo", needs_confirmation: true });
    open(task, { kind: "complete", taskId: task.id });
    const file = new File(["jpeg"], "shelf.jpg", { type: "image/jpeg" });
    const input = document.querySelector('.sheet input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [file] } });
    fireEvent.click(await screen.findByRole("button", { name: "Send for checking" }));
    await waitFor(() => {
      const form = (api.mock.calls as [string, { form?: FormData }][]).find(([path]) => path.endsWith("/complete/"))?.[1]?.form;
      expect((form?.get("proof_photo") as File | null)?.name).toBe("shelf.jpg");
    });
    expect(await screen.findByRole("button", { name: "Undo" })).toBeTruthy();
  });

  it("starts a sent-back report from the one that went with it", () => {
    const task = makeTask({ proof: "text", status: "returned", proof_text: "Till: 4 250 000" });
    open(task, { kind: "complete", taskId: task.id });
    expect((screen.getByLabelText("Note (needed)") as HTMLTextAreaElement).value).toBe("Till: 4 250 000");
  });
});

describe("snooze choices (R2 T15)", () => {
  it("pause the reminders of someone's work and say the deadline stays", async () => {
    const task = makeTask({ due_at: "2026-10-21T09:30:00+05:00", snoozed_until: null, reminder: { snoozes_left: 2 } as Task["reminder"] });
    open(task, { kind: "snooze", taskId: task.id });
    expect(screen.queryByRole("button", { name: /Tomorrow 09:00/ })).toBeNull();
    expect(screen.getByText("The deadline stays today, 09:30. Only the reminders pause.")).toBeTruthy();
    expect(screen.getByText("Snoozes left: 2")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "In 1 hour" }));
    await waitFor(() => expect(sent("/snooze/")).toEqual([{ preset: "1h" }]));
    expect(await screen.findByText("Snoozed. Next reminder at 11:00. The deadline stays: today, 09:30.")).toBeTruthy();
  });

  it("can move my own task to tomorrow morning, and says so", async () => {
    const task = makeTask({ kind: "personal", created_by: null, due_at: "2026-10-21T09:30:00+05:00", snoozed_until: null });
    open(task, { kind: "snooze", taskId: task.id });
    expect(screen.getByText("Moves the deadline to tomorrow morning.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Tomorrow 09:00/ }));
    await waitFor(() => expect(sent("/snooze/")).toEqual([{ preset: "tomorrow_morning" }]));
    expect(await screen.findByText("Deadline moved: tomorrow, 09:00.")).toBeTruthy();
  });
});

describe("sending work back (R2 T30)", () => {
  it("takes a reason in one tap and an optional note after it", async () => {
    const task = makeTask({ status: "review" });
    open(task, { kind: "return", taskId: task.id }, { manager: true });
    const send = screen.getByRole("button", { name: "Send back" }) as HTMLButtonElement;
    expect(send.disabled).toBe(true);
    fireEvent.click(screen.getByRole("radio", { name: "Photo is unclear" }));
    expect(screen.getByLabelText("What to fix (optional)")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("What to fix (optional)"), { target: { value: "Retake it in daylight" } });
    fireEvent.click(send);
    await waitFor(() => expect(sent("/return/")).toEqual([{ reason: "Photo is unclear. Retake it in daylight" }]));
  });

  it("needs words for Other", () => {
    const task = makeTask({ status: "review" });
    open(task, { kind: "return", taskId: task.id }, { manager: true });
    fireEvent.click(screen.getByRole("radio", { name: "Other" }));
    expect(screen.getByLabelText("What needs to be fixed?")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Send back" }) as HTMLButtonElement).disabled).toBe(true);
  });
});

describe("need more time (R2 T17)", () => {
  it("asks for a later deadline, counted from the current one", async () => {
    const task = makeTask({ due_at: "2026-10-21T18:00:00+05:00", extension: null });
    open(task, { kind: "extension", taskId: task.id });
    expect(screen.getByText("New deadline: today, 18:30")).toBeTruthy();
    fireEvent.click(screen.getByRole("radio", { name: "+1 hour" }));
    fireEvent.change(screen.getByLabelText("Why? (optional)"), { target: { value: "Delivery is late" } });
    fireEvent.click(screen.getByRole("button", { name: "Ask for more time" }));
    await waitFor(() => expect(sent("/extension/")).toEqual([{ until: "2026-10-21T14:00:00.000Z", note: "Delivery is late" }]));
    expect(await screen.findByText("Request sent. The answer comes in the bot.")).toBeTruthy();
  });
});

describe("the giver's answers to a blocker", () => {
  it("hands the work to someone else on the team", async () => {
    const task = makeTask({ blocker: { reason_code: "not_mine", note: "", at: NOW.toISOString() } });
    open(task, { kind: "reassign", taskId: task.id }, { manager: true, members: [{ id: 7, name: "Alisher Valiyev", position: null }, { id: 12, name: "Madina Saidova", position: "Pharmacist" }] });
    // Not the person who has it now.
    fireEvent.click(await screen.findByRole("button", { name: /Madina Saidova/ }));
    await waitFor(() => expect(sent("/blocker/resolve/")).toEqual([{ action: "reassign", assignee_id: 12 }]));
    expect(screen.queryByRole("button", { name: /Alisher Valiyev/ })).toBeNull();
    expect(await screen.findByText("Now with Madina Saidova.")).toBeTruthy();
  });

  it("sets a new time", async () => {
    const task = makeTask({ due_at: "2026-10-21T09:00:00+05:00", blocker: { reason_code: "no_stock", note: "", at: NOW.toISOString() } });
    open(task, { kind: "due", taskId: task.id, resolve: true }, { manager: true });
    fireEvent.change(screen.getByLabelText("Day"), { target: { value: "2026-10-22" } });
    fireEvent.change(screen.getByLabelText("Time"), { target: { value: "12:00" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(sent("/blocker/resolve/")).toEqual([{ action: "new_due", due_at: "2026-10-22T07:00:00.000Z" }]));
    expect(navigationState().sheet).toBeNull();
  });
});
