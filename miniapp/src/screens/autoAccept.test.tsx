/**
 * Finished tasks accepted automatically (PLAN-OWNER §15.3) as the app shows them: "Accepted" at
 * once (the toast, the list line, the task screen), not "sent for checking"; "I'll check it" starting
 * from the company's rule; and one company everywhere (a pick in the company sheet moves the bot).
 */
import { act, cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { keys } from "../api/hooks";
import type { Membership, Task } from "../api/types";
import { DICTIONARIES } from "../i18n";
import { useDoneToast } from "../lib/actions";
import { resetQuickAdd } from "../lib/quickAdd";
import { rowMeta } from "../lib/taskView";
import { useSession } from "../state/session";
import { ctxFor, makeTask, membership, NOW, person, renderApp } from "../test/harness";
import { TaskDetail } from "./TaskDetail";

const api = vi.hoisted(() => vi.fn());
vi.mock("../api/client", async (importOriginal) => ({ ...(await importOriginal<typeof import("../api/client")>()), api }));

type Call = [string, { json?: Record<string, unknown>; method?: string } | undefined];
const callsTo = (path: string) => (api.mock.calls as Call[]).filter(([called]) => called === path);

beforeEach(() => {
  vi.useFakeTimers({ now: NOW, shouldAdvanceTime: true });
  resetQuickAdd();
});

afterEach(() => {
  cleanup();
  api.mockReset();
  vi.useRealTimers();
});

const accepted = (fields: Partial<Task> = {}) =>
  makeTask({ status: "done", completed_at: "2026-10-21T10:30:00+05:00", accepted_automatically: true, actions: [], ...fields });

describe("work accepted at once", () => {
  it("reads Accepted in the list, in every language, with no emoji", () => {
    expect(rowMeta(accepted(), ctxFor("en"))).toBe("Accepted · 10:30");
    expect(rowMeta(accepted(), ctxFor("uz"))).toBe("Qabul qilindi · 10:30");
    expect(rowMeta(accepted(), ctxFor("ru"))).toBe("Принято · 10:30");
    const emoji = /[\p{Extended_Pictographic}\u{FE0F}]/u;
    for (const key of ["toast.accepted", "status.accepted", "detail.banner.accepted", "detail.banner.acceptedAfterWait", "complete.withProof", "add.illCheckRule"]) {
      for (const dictionary of Object.values(DICTIONARIES)) {
        expect(dictionary[key], key).toBeTruthy();
        expect(emoji.test(dictionary[key]!), key).toBe(false);
      }
    }
  });

  it("says Accepted in the toast after Done, not sent for checking", async () => {
    function Probe({ task }: { task: Task }) {
      const toast = useDoneToast();
      return (
        <button type="button" onClick={() => toast(task)}>
          finish
        </button>
      );
    }
    renderApp(<Probe task={accepted()} />, { lang: "uz", me: person([membership()], "uz") });
    fireEvent.click(screen.getByRole("button", { name: "finish" }));
    expect(await screen.findByText("Qabul qilindi")).toBeTruthy();
    expect(screen.queryByText(/Tekshiruvga yuborildi/)).toBeNull();
  });

  it("shows Accepted on the task screen, and why when the wait for a review did it", async () => {
    const waited = accepted({ confirmed_at: "2026-10-21T18:30:00+05:00" });
    api.mockImplementation((path: string) => (path === `/companies/1/tasks/${waited.id}/` ? Promise.resolve(waited) : Promise.resolve([])));
    renderApp(<TaskDetail taskId={waited.id} />, {
      init: { tab: "tasks", stack: [{ feature: "core", page: "task", params: { id: waited.id } }] },
      seed: (client) => {
        client.setQueryData(keys.task(1, waited.id), waited);
        client.setQueryData(keys.comments(1, waited.id), []);
        client.setQueryData(keys.activity(1), []);
        client.setQueryData(keys.summary(1), { quiet_from: null, quiet_until: null });
        client.setQueryData(keys.review(1), []);
        client.setQueryData(keys.members(1), []);
      },
    });
    expect(await screen.findByText("Accepted automatically at 18:30")).toBeTruthy();
    expect(screen.getByText("Nobody checked it in time, so it was accepted.")).toBeTruthy();
    expect(screen.getAllByText("Accepted").length).toBeGreaterThan(0);
  });
});

describe("I'll check it starts from the company's rule", () => {
  function openSheet(rule: string) {
    api.mockImplementation((path: string) => {
      if (path === "/companies/1/tasks/finish-rule/") return Promise.resolve({ on_finish: rule });
      if (path === "/companies/1/tasks/parse/") return Promise.resolve({ title: "Kassa", due_at: null, due_label: null, priority: null, repeat: null });
      if (path === "/companies/1/tasks/") return Promise.resolve({ id: 900 });
      if (path === "/companies/1/members/") return Promise.resolve([{ id: 12, name: "Madina Saidova", position: "Pharmacist" }]);
      return Promise.reject(new Error(`unexpected ${path}`));
    });
    const me = person([membership({ id: 7, permissions: ["tasks.assign"] as Membership["permissions"] })]);
    return renderApp(null, { me, init: { sheet: { kind: "add" } }, seed: (client) => client.setQueryData(keys.members(1), undefined) });
  }

  async function give() {
    const forWhom = (await screen.findByLabelText("For")) as HTMLSelectElement;
    await waitFor(() => expect(forWhom.options.length).toBe(2));
    fireEvent.change(forWhom, { target: { value: "12" } });
    fireEvent.change(screen.getByLabelText("What needs doing?"), { target: { value: "Kassa" } });
  }

  const created = () => callsTo("/companies/1/tasks/").map(([, options]) => options?.json);

  it("is on when the company always asks, and leaves the choice to the rule untouched", async () => {
    openSheet("ask");
    await give();
    const chip = screen.getByRole("button", { name: "I'll check it" });
    await waitFor(() => expect(chip.getAttribute("aria-pressed")).toBe("true"));
    fireEvent.click(screen.getByRole("button", { name: /Give task/ }));
    await waitFor(() => expect(created()).toHaveLength(1));
    expect(created()[0]).not.toHaveProperty("needs_confirmation");
  });

  it("says the proof rule, and sends the giver's own choice once tapped", async () => {
    openSheet("proof");
    await give();
    expect(await screen.findByText("Company rule: accepted at once with a photo or a note")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "I'll check it" }));
    fireEvent.click(screen.getByRole("button", { name: /Give task/ }));
    await waitFor(() => expect(created()).toHaveLength(1));
    expect(created()[0]).toMatchObject({ needs_confirmation: false });
  });
});

describe("one company everywhere", () => {
  it("moves the bot to the company picked here, once", async () => {
    api.mockResolvedValue({});
    let switchTo: (id: number) => void = () => undefined;
    function Probe() {
      const session = useSession();
      switchTo = session.switchCompany;
      return <span data-testid="company">{session.membership?.company.id}</span>;
    }
    const two = person([membership({ companyId: 1 }), membership({ id: 8, companyId: 2, companyName: "Demo Distribyutor" })]);
    localStorage.removeItem("daybook.company");
    renderApp(<Probe />, { me: two });
    expect((await screen.findByTestId("company")).textContent).toBe("1");
    act(() => switchTo(2));
    await waitFor(() => expect(screen.getByTestId("company").textContent).toBe("2"));
    expect(callsTo("/me/")).toEqual([["/me/", { method: "PATCH", json: { bot_company: 2 } }]]);
    act(() => switchTo(2)); // already there: nothing to move
    expect(callsTo("/me/")).toHaveLength(1);
    localStorage.removeItem("daybook.company");
  });
});
