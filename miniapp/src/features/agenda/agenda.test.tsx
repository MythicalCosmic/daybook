/** The calendar feature: days, colours, and answering an invitation. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Me, Membership } from "../../api/types";
import { I18nProvider } from "../../i18n";
import { NavigationProvider } from "../../state/navigation";
import { SessionProvider } from "../../state/session";
import { ToastProvider } from "../../state/toast";
import { agendaKeys, eventIdOf, type AgendaEvent, type CalendarEntry } from "./api";
import { CalendarHome } from "./CalendarHome";
import { EventPage } from "./EventPage";
import { byDay, colorClass, mondayOf, weekDays } from "./lib";

const api = vi.hoisted(() => vi.fn());
vi.mock("../../api/client", () => ({ api }));

const entry = (overrides: Partial<CalendarEntry> = {}): CalendarEntry => ({
  id: "agenda.events:12",
  source: "agenda.events",
  kind: "agenda.event",
  title: "Kassa trening",
  start: "2026-10-22T15:00:00+05:00",
  end: "2026-10-22T17:00:00+05:00",
  all_day: false,
  color: "chart-6",
  url: "",
  ...overrides,
});

const event = (overrides: Partial<AgendaEvent> = {}): AgendaEvent => ({
  id: 12,
  title: "Kassa trening",
  description: "Yangi kassa dasturi",
  kind: "training",
  color: "chart-6",
  start: "2026-10-22T15:00:00+05:00",
  end: "2026-10-22T17:00:00+05:00",
  all_day: false,
  place: "Chilonzor",
  branch: null,
  repeat: "none",
  repeat_until: null,
  remind_before: 60,
  created_by: null,
  attendees: [{ member: { id: 7, name: "Madina Saidova", position: "Cashier" }, response: "pending" }],
  responses: { pending: 1, going: 0, declined: 0 },
  my_response: "pending",
  cancelled: false,
  cancel_reason: "",
  ...overrides,
});

function renderWith(node: ReactNode, client: QueryClient) {
  const membership = {
    id: 7,
    company: { id: 1, name: "Demo Shop", timezone: "Asia/Tashkent", features: [], owner_sees_personal_tasks: false, base_currency: "UZS", team_directory_phones: false },
    status: "approved",
    first_name: "Madina",
    last_name: "Saidova",
    permissions: [],
    is_onboarded: true,
    branch_ids: [],
  } as unknown as Membership;
  const me = { id: 1, telegram_id: 1004, telegram_username: "", first_name: "Madina", last_name: "Saidova", phone: "", memberships: [membership] } as Me;
  return render(
    <QueryClientProvider client={client}>
      <I18nProvider lang="en">
        <ToastProvider>
          <SessionProvider me={me}>
            <NavigationProvider>{node}</NavigationProvider>
          </SessionProvider>
        </ToastProvider>
      </I18nProvider>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  api.mockReset();
  vi.useRealTimers();
});

describe("lib", () => {
  it("starts weeks on Monday and spreads items over their days", () => {
    expect(mondayOf("2026-10-21")).toBe("2026-10-19");
    const days = weekDays("2026-10-19");
    expect(days).toHaveLength(7);
    const map = byDay([entry(), entry({ id: "x:1", kind: "timeoff.holiday", all_day: true, start: "2026-10-24", end: "2026-10-25", title: "Holiday" })], days, "Asia/Tashkent");
    expect(map.get("2026-10-22")!.map((item) => item.title)).toEqual(["Kassa trening"]);
    expect(map.get("2026-10-25")!.map((item) => item.title)).toEqual(["Holiday"]);
  });

  it("maps colours and finds events", () => {
    expect(colorClass("chart-6")).toBe("agm-c-chart-6");
    expect(colorClass("accent")).toBe("agm-c-accent");
    expect(colorClass("#123456")).toBe("agm-c-chart-1");
    expect(eventIdOf(entry({ id: "agenda.events:12-20261026" }))).toBe(12);
    expect(eventIdOf(entry({ kind: "hr.birthday" }))).toBeNull();
  });
});

describe("EventPage", () => {
  it("answers an invitation at once", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
    client.setQueryData(agendaKeys.event(1, 12), event());
    api.mockImplementation((_path: string, options?: { method?: string }) =>
      Promise.resolve(options?.method === "POST" ? { response: "going" } : event({ my_response: "going" })),
    );
    renderWith(<EventPage params={{ id: 12 }} />, client);

    expect(screen.getAllByText(/Kassa trening/).length).toBeGreaterThan(0);
    expect(screen.getByText("Chilonzor")).toBeTruthy();
    expect(screen.getByText("Reminder 1 hour before")).toBeTruthy();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /I’ll come/ }));
    });
    expect(api).toHaveBeenCalledWith("/companies/1/calendar/events/12/respond/", { method: "POST", json: { response: "going" } });
    // Answered: the choice is now a switch to change it.
    expect(screen.getByRole("radiogroup", { name: "Are you coming?" })).toBeTruthy();
  });

  it("says when an event was cancelled and asks nothing", () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
    client.setQueryData(agendaKeys.event(1, 12), event({ cancelled: true, cancel_reason: "Moved" }));
    renderWith(<EventPage params={{ id: 12 }} />, client);

    expect(screen.getByText("This event was cancelled")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /I’ll come/ })).toBeNull();
  });
});

describe("CalendarHome", () => {
  it("marks only the invitations still waiting for an answer", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-10-21T09:00:00+05:00"));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const planning = entry({ id: "agenda.events:14", title: "Weekly planning", start: "2026-10-22T09:00:00+05:00", end: "2026-10-22T09:30:00+05:00" });
    api.mockResolvedValue({
      range: { from: "2026-10-19", to: "2026-11-03" },
      sources: [{ key: "agenda.events", label: "Company events", color: "chart-3" }],
      items: [entry(), planning],
      mine: ["agenda.events:12", "agenda.events:14"],
      answers: { "agenda.events:12": "pending", "agenda.events:14": "going" },
    });
    renderWith(<CalendarHome />, client);

    await waitFor(() => expect(screen.getAllByText("Weekly planning").length).toBeGreaterThan(0));
    expect(screen.getAllByText("Answer?").length).toBeGreaterThan(0);
    expect(screen.queryByText("You’re invited")).toBeNull();
  });
});
