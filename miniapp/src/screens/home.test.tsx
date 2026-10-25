/**
 * Home for tonight's details: requests waiting for the giver's answer, and no "nothing due today"
 * right above late work.
 */
import { cleanup, fireEvent, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { keys } from "../api/hooks";
import type { Summary, Task } from "../api/types";
import { makeTask, membership, navigationState, NOW, person, renderApp } from "../test/harness";
import { Home } from "./Home";

const api = vi.hoisted(() => vi.fn(() => Promise.reject(new Error("no network in tests"))));
vi.mock("../api/client", async (importOriginal) => ({ ...(await importOriginal<typeof import("../api/client")>()), api }));

function show(options: { board?: Task[]; given?: Task[]; summary?: Partial<Summary>; permissions?: string[] } = {}) {
  return renderApp(<Home />, {
    me: person([membership({ id: 3, permissions: (options.permissions ?? []) as never })]),
    seed: (client) => {
      client.setQueryData(keys.board(1), options.board ?? []);
      client.setQueryData(keys.given(1), options.given ?? []);
      client.setQueryData(keys.activity(1), []);
      client.setQueryData(keys.summary(1), { today_total: 0, today_done: 0, unread_activity: 0, awaiting_review: 0, streak_days: 0, week: [], ...options.summary });
    },
  });
}

beforeEach(() => vi.useFakeTimers({ now: NOW, shouldAdvanceTime: true }));
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("Home", () => {
  it("tells the giver about requests waiting for an answer, and opens the one", () => {
    const blocked = makeTask({ blocker: { reason_code: "no_stock", note: "", at: NOW.toISOString() } });
    show({ permissions: ["tasks.assign"], given: [blocked, makeTask()] });
    fireEvent.click(screen.getByText("1 request waits for your answer"));
    expect(navigationState().stack.at(-1)?.params?.id).toBe(blocked.id);
  });

  it("greets a night shift with good evening, not good morning", () => {
    vi.setSystemTime(new Date("2026-10-26T02:30:00+05:00"));
    show();
    expect(screen.getByText(/^Good evening/)).toBeTruthy();
    expect(screen.queryByText(/^Good morning/)).toBeNull();
  });

  it("doesn't say nothing is due today right above late work", () => {
    show({ board: [makeTask({ due_at: "2026-10-20T18:00:00+05:00" })] });
    expect(screen.getByText("No new tasks today")).toBeTruthy();
    expect(screen.queryByText("Nothing due today")).toBeNull();
  });
});
