/**
 * The app as Telegram hosts it: its back button and its events, on a fresh module graph so
 * telegram.ts reads the stub (kept apart from app.test.tsx, whose lazily loaded screens a module
 * reset would load from another graph).
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { keys } from "./api/hooks";
import type { Me, Membership, Summary } from "./api/types";

const registry = vi.hoisted(() => ({ list: [] as unknown[] }));
vi.mock("./features/registry", async (importOriginal) => {
  const real = await importOriginal<typeof import("./features/registry")>();
  return { ...real, features: registry.list };
});

function me(status: string, permissions: string[] = [], extra: Record<string, unknown> = {}): Me {
  const membership = {
    ...extra,
    id: 7,
    company: { id: 1, name: "Demo Dorixona", timezone: "Asia/Tashkent" },
    status,
    first_name: "Alisher",
    last_name: "Valiyev",
    position: null,
    role: "Employee",
    permissions,
    is_onboarded: true,
    onboarded_at: null,
    decided_at: null,
    rejoin_available_at: null,
  } as unknown as Membership;
  return { id: 1, telegram_id: 4242, telegram_username: "", first_name: "Alisher", last_name: "Valiyev", phone: "", language: "en", memberships: [membership] } as Me;
}

/**
 * The app as Telegram hosts it (back button, events): a fresh module graph, so telegram.ts reads
 * the stub. Returns the stub's parts, the App and the query keys of that graph.
 */
async function insideTelegram() {
  const back = { show: vi.fn(), hide: vi.fn(), onClick: vi.fn(), offClick: vi.fn() };
  const webApp = {
    platform: "android",
    initData: "",
    initDataUnsafe: {},
    isVersionAtLeast: () => true,
    BackButton: back,
    onEvent: vi.fn(),
    offEvent: vi.fn(),
    setHeaderColor: vi.fn(),
    setBackgroundColor: vi.fn(),
    setBottomBarColor: vi.fn(),
    HapticFeedback: { impactOccurred: vi.fn(), notificationOccurred: vi.fn(), selectionChanged: vi.fn() },
  };
  vi.stubGlobal("Telegram", { WebApp: webApp });
  vi.resetModules();
  const { App: InTelegram } = await import("./App");
  const { keys: freshKeys } = await import("./api/hooks");
  return { back, webApp, InTelegram, freshKeys };
}

/** A query client with what Home and Me read already there (nothing reaches the network). */
function seededClient(freshKeys: typeof keys, person: Me) {
  const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } });
  client.setQueryData(freshKeys.me, person);
  client.setQueryData(freshKeys.summary(1), { today_total: 0, today_done: 0, unread_activity: 0, awaiting_review: 0, week: [] } as unknown as Summary);
  client.setQueryData(freshKeys.board(1), []);
  client.setQueryData(freshKeys.activity(1), []);
  return client;
}

/** The fields of a task the task screen reads. */
function taskFields(fields: Record<string, unknown>) {
  return {
    kind: "assigned",
    routine: null,
    description: "",
    status: "todo",
    priority: "normal",
    due_at: null,
    proof: "none",
    needs_confirmation: false,
    proof_text: "",
    proof_photo: null,
    proof_thumb: null,
    reward: null,
    assignee: { id: 7, name: "Alisher Valiyev", position: null },
    created_by: { id: 3, name: "Bekzod Mirzayev", position: null },
    confirmed_by: null,
    checklist: [],
    reminder: null,
    repeat_weekdays: null,
    actions: ["start", "complete"],
    created_at: "2026-10-21T08:00:00+05:00",
    ...fields,
  };
}


beforeEach(() => {
  vi.stubEnv("VITE_DEV_INIT_DATA", "user=%7B%22id%22%3A4242%7D&hash=abc");
  // Nothing may reach the network: every query is seeded.
  vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new Error("no network in tests"))));
});

afterEach(() => {
  cleanup();
  window.history.replaceState(null, "", "/");
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("app inside Telegram", () => {
  it("wires Telegram's back button to the stack: it closes the top page, then hands the button back", async () => {
    const back = { show: vi.fn(), hide: vi.fn(), onClick: vi.fn(), offClick: vi.fn() };
    vi.stubGlobal("Telegram", {
      WebApp: {
        platform: "android",
        initData: "",
        initDataUnsafe: {},
        isVersionAtLeast: () => true,
        BackButton: back,
        onEvent: vi.fn(),
        offEvent: vi.fn(),
        setHeaderColor: vi.fn(),
        setBackgroundColor: vi.fn(),
        setBottomBarColor: vi.fn(),
        HapticFeedback: { impactOccurred: vi.fn(), notificationOccurred: vi.fn(), selectionChanged: vi.fn() },
      },
    });
    vi.resetModules();
    const { App: InTelegram } = await import("./App");
    const { keys: freshKeys } = await import("./api/hooks");
    window.history.replaceState(null, "", "/app/?screen=team");
    const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } });
    client.setQueryData(freshKeys.me, me("approved", ["reports.view"]));
    client.setQueryData(freshKeys.summary(1), { today_total: 0, today_done: 0, unread_activity: 0, awaiting_review: 0, week: [] } as unknown as Summary);
    render(
      <QueryClientProvider client={client}>
        <InTelegram />
      </QueryClientProvider>,
    );
    expect(await screen.findByRole("heading", { name: "Team results" }, { timeout: 10_000 })).toBeTruthy();
    const press = () => act(() => (back.onClick.mock.calls.at(-1)![0] as () => void)());
    expect(back.show).toHaveBeenCalled();
    press();
    await waitFor(() => expect(document.querySelector(".tabbar")).not.toBeNull());
    expect(screen.queryByRole("heading", { name: "Team results" })).toBeNull();
    // Nothing left to close: Telegram hides the button and its press goes to Telegram again.
    expect(back.hide).toHaveBeenCalled();
    expect(back.offClick).toHaveBeenCalled();
    // A fresh module graph (to load telegram.ts with the stub) is slow when every file runs at once.
  }, 20_000);

  it("opens a task link without drawing Home under it, and draws Home once back there", async () => {
    const { back, InTelegram, freshKeys } = await insideTelegram();
    window.history.replaceState(null, "", "/app/?screen=task:5");
    const client = seededClient(freshKeys, me("approved"));
    client.setQueryData(freshKeys.task(1, 5), taskFields({ id: 5, title: "Count the till" }));
    client.setQueryData(freshKeys.comments(1, 5), []);
    render(
      <QueryClientProvider client={client}>
        <InTelegram />
      </QueryClientProvider>,
    );
    expect(await screen.findByRole("heading", { name: "Count the till" }, { timeout: 10_000 })).toBeTruthy();
    // Home's cards and lists (a dozen requests) wait: nobody sees them under the task.
    expect(screen.queryByRole("heading", { name: /^Good (morning|afternoon|evening)/ })).toBeNull();
    act(() => (back.onClick.mock.calls.at(-1)![0] as () => void)());
    expect(await screen.findByRole("heading", { name: /^Good (morning|afternoon|evening)/ })).toBeTruthy();
  }, 20_000);

  it("asks before Back throws away a task being written in the (+) sheet", async () => {
    const { back, webApp, InTelegram, freshKeys } = await insideTelegram();
    const answers = [false, true];
    const showConfirm = vi.fn((_message: string, done: (ok: boolean) => void) => done(answers.shift()!));
    Object.assign(webApp, { showConfirm, enableClosingConfirmation: vi.fn(), disableClosingConfirmation: vi.fn() });
    window.history.replaceState(null, "", "/app/?screen=add");
    render(
      <QueryClientProvider client={seededClient(freshKeys, me("approved"))}>
        <InTelegram />
      </QueryClientProvider>,
    );
    const what = await screen.findByRole("textbox", { name: "What needs doing?" }, { timeout: 10_000 });
    fireEvent.change(what, { target: { value: "Order insulin" } });
    // Back is wired in an effect, which may run a moment after the sheet shows on a busy machine.
    await waitFor(() => expect(back.onClick).toHaveBeenCalled());
    const press = () => act(() => (back.onClick.mock.calls.at(-1)![0] as () => void)());

    // Cancel: the sheet and the words stay.
    press();
    expect(showConfirm).toHaveBeenCalledWith("Close it? What you entered won't be saved.", expect.any(Function));
    await act(async () => undefined);
    expect(screen.getByRole("textbox", { name: "What needs doing?" })).toHaveProperty("value", "Order insulin");
    // OK: closed.
    press();
    await waitFor(() => expect(screen.queryByRole("textbox", { name: "What needs doing?" })).toBeNull());
    expect(showConfirm).toHaveBeenCalledTimes(2);
  }, 20_000);

  it("fetches the work again on coming back to the app, My team included, without cancelling what is on its way", async () => {
    const { webApp, InTelegram, freshKeys } = await insideTelegram();
    const client = seededClient(freshKeys, me("approved"));
    render(
      <QueryClientProvider client={client}>
        <InTelegram />
      </QueryClientProvider>,
    );
    await screen.findByRole("heading", { name: /^Good (morning|afternoon|evening)/ }, { timeout: 10_000 });
    // The listener is added in an effect, which may run a moment after Home shows on a busy machine.
    await waitFor(() => expect(webApp.onEvent.mock.calls.some(([name]) => name === "activated")).toBe(true));
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const activated = webApp.onEvent.mock.calls.find(([name]) => name === "activated")?.[1] as () => void;
    act(() => activated());
    const refreshed = invalidate.mock.calls.map(([filters, options]) => [JSON.stringify(filters?.queryKey), options?.cancelRefetch]);
    expect(refreshed).toEqual(
      expect.arrayContaining([
        ['["tasks",1]', false],
        ['["summary",1]', false],
        ['["activity",1]', false],
        ['["myTeam",1]', false],
      ]),
    );
  }, 20_000);

});
