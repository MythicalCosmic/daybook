/**
 * The app's wiring: a launch link picks the first screen, and a suspended membership gets the
 * "Access paused" screen (a feature's, or the built-in one).
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { keys } from "./api/hooks";
import type { Me, Membership, Summary } from "./api/types";
import { App } from "./App";
import { defineFeature, type Feature, type GateProps } from "./features/registry";

const registry = vi.hoisted(() => ({ list: [] as unknown[] }));
vi.mock("./features/registry", async (importOriginal) => {
  const real = await importOriginal<typeof import("./features/registry")>();
  return { ...real, features: registry.list };
});

function me(status: string, permissions: string[] = []): Me {
  const membership = {
    id: 7,
    company: { id: 1, name: "Demo Shop", timezone: "Asia/Tashkent" },
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

function renderApp(person: Me) {
  const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } });
  client.setQueryData(keys.me, person);
  client.setQueryData(keys.summary(1), { today_total: 0, today_done: 0, unread_activity: 0, awaiting_review: 0, week: [] } as unknown as Summary);
  client.setQueryData(keys.board(1), []);
  client.setQueryData(keys.activity(1), []);
  client.setQueryData(keys.timeOff(1), []);
  client.setQueryData(keys.holidays(1), []);
  return render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.stubEnv("VITE_DEV_INIT_DATA", "user=%7B%22id%22%3A4242%7D&hash=abc");
  // Nothing may reach the network: every query is seeded.
  vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new Error("no network in tests"))));
});

afterEach(() => {
  cleanup();
  registry.list.splice(0);
  window.history.replaceState(null, "", "/");
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("app", () => {
  it("opens on Home with the tab bar by default", async () => {
    renderApp(me("approved"));
    expect(await screen.findByText("Home", {}, { timeout: 3000 })).toBeTruthy();
    expect(document.querySelector(".tabbar")).not.toBeNull();
  });

  it("opens the screen a launch link asks for", async () => {
    window.history.replaceState(null, "", "/app/?screen=team");
    renderApp(me("approved", ["reports.view"]));
    expect(await screen.findByRole("heading", { name: "Team results" }, { timeout: 3000 })).toBeTruthy();
    // A page covers the tabs, as when it is opened from Me.
    expect(document.querySelector(".tabbar")).toBeNull();
  });

  it("shows a calm paused screen to a suspended person", async () => {
    renderApp(me("suspended"));
    expect(await screen.findByText("Your access is paused", {}, { timeout: 3000 })).toBeTruthy();
    expect(document.querySelector(".tabbar")).toBeNull();
  });

  it("uses the lifecycle feature's paused screen when there is one", async () => {
    const Paused = ({ membership }: GateProps) => <h1>{`Paused for ${membership.first_name}`}</h1>;
    const lifecycle: Feature = defineFeature({ id: "lifecycle", messages: { en: {}, ru: {}, uz: {} }, gates: { suspended: Paused } });
    registry.list.push(lifecycle);
    renderApp(me("suspended"));
    expect(await screen.findByText("Paused for Alisher", {}, { timeout: 3000 })).toBeTruthy();
  });
});
