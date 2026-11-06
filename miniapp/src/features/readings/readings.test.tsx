/**
 * Storage readings on the task screen (PLAN-OWNER §14.10): nothing for other tasks; my open run
 * takes a value per reading ("5,2" or "5.2"), says whether it's in range, asks for the note once
 * one is out and saves with its own button; a finished run lists what was taken and offers the
 * second measurement only while it may come; someone else's open run shows what is measured.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../../api/client";
import type { Me, Membership, Task } from "../../api/types";
import { I18nProvider, type Lang } from "../../i18n";
import { NavigationProvider } from "../../state/navigation";
import { SessionProvider } from "../../state/session";
import { ToastProvider } from "../../state/toast";
import { collectFeatures, type Feature } from "../registry";
import type { ReadingSpec, ReadingTaken } from "./api";
import { entryOf, formatNumber, parseValue, rangeText, stillOut } from "./lib";
import { messages } from "./messages";

const server = vi.hoisted(() => ({
  calls: [] as { path: string; method: string; json: unknown }[],
  handler: (() => undefined) as (path: string, method: string, json: unknown) => unknown,
}));

vi.mock("../../api/client", async (importOriginal) => {
  const real = await importOriginal<typeof import("../../api/client")>();
  return {
    ...real,
    api: vi.fn(async (path: string, options: { method?: string; json?: unknown } = {}) => {
      const method = options.method ?? "GET";
      server.calls.push({ path, method, json: options.json });
      const result = server.handler(path, method, options.json);
      if (result instanceof Error) throw result;
      return result;
    }),
  };
});

const { default: feature } = await import("./index");
const { default: ReadingsBlock } = await import("./ReadingsBlock");

const ME = 7;
const FRIDGE: ReadingSpec = { key: "t", label: "Fridge 1 (vaccines)", unit: "°C", min: "2.0", max: "8.0", critical: true };
const HUMIDITY: ReadingSpec = { key: "h", label: "Humidity", unit: "%", min: null, max: "60.0", critical: false };

function membership(): Membership {
  return {
    id: ME,
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
    permissions: [],
    is_onboarded: true,
    onboarded_at: null,
    decided_at: null,
    rejoin_available_at: null,
    home_branch: null,
    branch_ids: [],
    suspended_until: null,
    joined_by_link: false,
    department: null,
    manager: null,
    team_size: 0,
    heads: [],
  };
}

const slot = { member: { ...membership(), timeZone: "Asia/Tashkent", companyId: 1 }, summary: undefined };

function task(overrides: Record<string, unknown> = {}): Task {
  return {
    id: 12,
    title: "Fridge 1: temperature, 09:00",
    status: "todo",
    kind: "daily",
    proof: "readings",
    readings: [FRIDGE],
    readings_taken: [],
    recheck_until: null,
    actions: ["start", "complete"],
    assignee: { id: ME, name: "Alisher Valiyev", position: null },
    checklist: [],
    ...overrides,
  } as unknown as Task;
}

function taken(overrides: Partial<ReadingTaken> = {}): ReadingTaken {
  return {
    id: 1,
    key: "t",
    label: "Fridge 1 (vaccines)",
    unit: "°C",
    value: "8.6",
    min: "2.0",
    max: "8.0",
    in_range: false,
    note: "Moved the vaccines to the spare fridge",
    is_recheck: false,
    recorded_at: "2026-11-06T04:05:00Z",
    recorded_by: { id: ME, name: "Alisher Valiyev" },
    ...overrides,
  };
}

function renderWith(node: ReactNode, lang: Lang = "en") {
  const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } });
  const me = { id: 1, telegram_id: 4242, telegram_username: "", first_name: "Alisher", last_name: "Valiyev", phone: "", memberships: [membership()] } as Me;
  return {
    client,
    ...render(
      <QueryClientProvider client={client}>
        <I18nProvider lang={lang}>
          <ToastProvider>
            <SessionProvider me={me}>
              <NavigationProvider>{node}</NavigationProvider>
            </SessionProvider>
          </ToastProvider>
        </I18nProvider>
      </QueryClientProvider>,
    ),
  };
}

/** The lazy block's first render: wait for its title (or for nothing at all). */
const field = (label: string) => screen.findByLabelText(label);
const saveButton = () => screen.getByRole("button", { name: "Save and complete" });

beforeEach(() => {
  server.calls.splice(0);
  server.handler = (path, method) => {
    if (path === "/companies/1/tasks/12/complete/" && method === "POST") return task({ status: "done", actions: [] });
    if (path === "/companies/1/tasks/12/recheck/" && method === "POST") return task({ status: "done", actions: [] });
    return undefined;
  };
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("values", () => {
  it("read a decimal comma or point, units and a minus sign", () => {
    expect(parseValue("5,2")).toBe(5.2);
    expect(parseValue("5.2")).toBe(5.2);
    expect(parseValue(" +5,2 °C")).toBe(5.2);
    expect(parseValue("58 %")).toBe(58);
    expect(parseValue("−3,5")).toBe(-3.5);
    expect(parseValue("five")).toBeNull();
    expect(parseValue("5,2,1")).toBeNull();
    expect(parseValue("")).toBeNull();
  });

  it("show back in the person's style, with the range", () => {
    expect(formatNumber(5.2, "uz")).toBe("5,2");
    expect(formatNumber("8.00", "en")).toBe("8");
    expect(formatNumber(-3.5, "ru")).toBe("−3,5");
    expect(rangeText(FRIDGE, "ru")).toBe("2–8 °C");
    expect(rangeText(HUMIDITY, "en")).toBe("≤ 60 %");
    expect(rangeText({ min: "15.0", max: null, unit: "°C" }, "uz")).toBe("≥ 15 °C");
  });

  it("know in range, out of range, typos and nonsense", () => {
    expect(entryOf("5,2", FRIDGE)).toEqual({ state: "in", value: 5.2 });
    expect(entryOf("8.5", FRIDGE)).toEqual({ state: "out", value: 8.5 });
    expect(entryOf("8", FRIDGE).state).toBe("in");
    expect(entryOf("150", FRIDGE).state).toBe("implausible");
    expect(entryOf("abc", FRIDGE).state).toBe("invalid");
    expect(entryOf("  ", FRIDGE).state).toBe("empty");
    expect(entryOf("61", HUMIDITY).state).toBe("out");
  });

  it("find the keys still out of range after rechecks", () => {
    const first = taken();
    const back = taken({ id: 2, value: "5.0", in_range: true, is_recheck: true, recorded_at: "2026-11-06T04:40:00Z" });
    expect(stillOut([first])).toEqual(["t"]);
    expect(stillOut([first, back])).toEqual([]);
  });
});

describe("the block on the task screen", () => {
  it("renders nothing for a task that takes no readings", async () => {
    const { container } = renderWith(<ReadingsBlock {...slot} task={task({ proof: "photo", readings: [] })} />);
    await act(async () => {});
    expect(container.textContent).toBe("");
    expect(server.calls).toEqual([]);
  });

  it("takes a value per reading and completes with it", async () => {
    renderWith(<ReadingsBlock {...slot} task={task({ readings: [FRIDGE, HUMIDITY] })} />);
    const fridge = await field("Fridge 1 (vaccines)");
    expect(screen.getByText("Allowed: 2–8 °C")).toBeTruthy();
    expect(screen.getByText("Allowed: ≤ 60 %")).toBeTruthy();
    expect(fridge.getAttribute("inputmode")).toBe("decimal");

    fireEvent.change(fridge, { target: { value: "5,2" } });
    expect(screen.getByText("In range")).toBeTruthy();
    expect((saveButton() as HTMLButtonElement).disabled).toBe(true); // humidity still empty
    fireEvent.change(await field("Humidity"), { target: { value: "48" } });
    expect((saveButton() as HTMLButtonElement).disabled).toBe(false);
    await act(async () => fireEvent.click(saveButton()));

    expect(server.calls).toEqual([
      { path: "/companies/1/tasks/12/complete/", method: "POST", json: { readings: { t: "5,2", h: "48" }, reading_note: "" } },
    ]);
    expect(await screen.findByText("Done")).toBeTruthy();
  });

  it("asks for the note once a value is out of range and won't save without it", async () => {
    renderWith(<ReadingsBlock {...slot} task={task()} />);
    fireEvent.change(await field("Fridge 1 (vaccines)"), { target: { value: "8.5" } });

    expect(screen.getByText("Out of range")).toBeTruthy();
    const note = screen.getByLabelText("What did you do about it?");
    expect((saveButton() as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText("Write what you did, then save.")).toBeTruthy();
    await act(async () => fireEvent.click(saveButton()));
    expect(server.calls).toEqual([]);

    fireEvent.change(note, { target: { value: "Moved the vaccines" } });
    await act(async () => fireEvent.click(saveButton()));
    expect(server.calls[0]).toMatchObject({ json: { readings: { t: "8.5" }, reading_note: "Moved the vaccines" } });
  });

  it("says when a value can't be a reading", async () => {
    renderWith(<ReadingsBlock {...slot} task={task()} />);
    const fridge = await field("Fridge 1 (vaccines)");
    fireEvent.change(fridge, { target: { value: "abc" } });
    expect(screen.getByText("Type a number, like 5.2")).toBeTruthy();
    fireEvent.change(fridge, { target: { value: "150" } });
    expect(screen.getByText("That can't be right: from −50 to 100")).toBeTruthy();
    expect((saveButton() as HTMLButtonElement).disabled).toBe(true);
  });

  it("shows the number back with a decimal comma in Uzbek", async () => {
    renderWith(<ReadingsBlock {...slot} task={task()} />, "uz");
    const fridge = (await field("Fridge 1 (vaccines)")) as HTMLInputElement;
    fireEvent.change(fridge, { target: { value: "5.2" } });
    fireEvent.blur(fridge);
    expect(fridge.value).toBe("5,2");
    expect(screen.getByText("Me’yor: 2–8 °C")).toBeTruthy();
  });

  it("shows the server's answer when it refuses", async () => {
    server.handler = () => new ApiError(400, { detail: "Enter the readings to complete this task." });
    renderWith(<ReadingsBlock {...slot} task={task()} />);
    fireEvent.change(await field("Fridge 1 (vaccines)"), { target: { value: "5" } });
    await act(async () => fireEvent.click(saveButton()));
    expect((await screen.findByRole("alert")).textContent).toBe("Enter the readings to complete this task.");
  });

  it("lists what was taken on a finished run, rechecks included", async () => {
    const readings = [taken(), taken({ id: 2, value: "5.4", in_range: true, is_recheck: true, note: "", recorded_at: "2026-11-06T04:42:00Z" })];
    renderWith(<ReadingsBlock {...slot} task={task({ status: "done", actions: [], readings_taken: readings })} />);

    expect(await screen.findByText("8.6 °C")).toBeTruthy();
    expect(screen.getByText("5.4 °C")).toBeTruthy();
    expect(screen.getByText("Out of range")).toBeTruthy();
    expect(screen.getByText("Back in range")).toBeTruthy();
    expect(screen.getByText("Moved the vaccines to the spare fridge")).toBeTruthy();
    expect(screen.getByText("09:05 · Alisher Valiyev")).toBeTruthy();
    expect(screen.getByText("Recheck")).toBeTruthy();
    // Back in range: nothing to take again.
    expect(screen.queryByRole("button", { name: "Take it again" })).toBeNull();
  });

  it("offers the recheck only while it may come, for my own run, and sends it", async () => {
    const soon = new Date(Date.now() + 60 * 60_000).toISOString();
    const past = new Date(Date.now() - 60_000).toISOString();
    const finished = (overrides: Record<string, unknown>) => task({ status: "done", actions: [], readings_taken: [taken()], ...overrides });

    const expired = renderWith(<ReadingsBlock {...slot} task={finished({ recheck_until: past })} />);
    expect(await screen.findByText("8.6 °C")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Take it again" })).toBeNull();
    expired.unmount();

    const theirs = renderWith(<ReadingsBlock {...slot} task={finished({ recheck_until: soon, assignee: { id: 3, name: "Gulnora Ismoilova", position: null } })} />);
    expect(await screen.findByText("8.6 °C")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Take it again" })).toBeNull();
    theirs.unmount();

    renderWith(<ReadingsBlock {...slot} task={finished({ recheck_until: soon })} />);
    await act(async () => fireEvent.click(await screen.findByRole("button", { name: "Take it again" })));
    fireEvent.change(await field("Fridge 1 (vaccines)"), { target: { value: "5,1" } });
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Save the new reading" })));

    expect(server.calls).toEqual([
      { path: "/companies/1/tasks/12/recheck/", method: "POST", json: { readings: { t: "5,1" }, note: "" } },
    ]);
    await waitFor(() => expect(screen.getByText("Back in range")).toBeTruthy());
  });

  it("shows someone else's open run as what is measured, with nothing to type", async () => {
    renderWith(<ReadingsBlock {...slot} task={task({ actions: [], assignee: { id: 3, name: "Gulnora Ismoilova", position: null } })} />);
    expect(await screen.findByText("What is measured")).toBeTruthy();
    expect(screen.getByText("Allowed: 2–8 °C")).toBeTruthy();
    expect(screen.queryByRole("textbox")).toBeNull();
  });
});

describe("the feature", () => {
  it("plugs into the task screen first", () => {
    const { features, problems } = collectFeatures({ "./readings/index.ts": { default: feature } });
    expect(problems).toEqual([]);
    expect((features as Feature[])[0]!.taskActions?.map((slot) => [slot.id, slot.order])).toEqual([["readings", 5]]);
  });

  it("hides from people who aren't approved or are suspended", () => {
    const member = { ...membership(), timeZone: "Asia/Tashkent", companyId: 1 };
    expect(feature.visible?.(member, undefined)).toBe(true);
    expect(feature.visible?.({ ...member, status: "pending" }, undefined)).toBe(false);
    expect(feature.visible?.({ ...member, status: "suspended" as Membership["status"] }, undefined)).toBe(false);
  });

  it("has every message in English, Russian and Uzbek", () => {
    const keys = (dictionary: Record<string, string>) => Object.keys(dictionary).sort();
    expect(keys(messages.ru)).toEqual(keys(messages.en));
    expect(keys(messages.uz)).toEqual(keys(messages.en));
    for (const value of Object.values(messages.uz)) {
      expect(value).not.toMatch(/[`']/);
      expect(value).not.toMatch(/[oOgG][’ʻʼ]/);
    }
  });
});
