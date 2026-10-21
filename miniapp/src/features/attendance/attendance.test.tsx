/**
 * Attendance in the mini app: the check-in card with Telegram's LocationManager mocked and the
 * browser's geolocation as the fallback, the geofence answers (confirm when flagged, explain when
 * rejected), the selfie step, check-out, the feature's registration and the plain helpers.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Me, Membership } from "../../api/types";
import { I18nProvider, type Lang } from "../../i18n";
import { featureTranslator } from "../../i18n/feature";
import { NavigationProvider } from "../../state/navigation";
import { SessionProvider } from "../../state/session";
import { ToastProvider } from "../../state/toast";
import { featureVisible, routeTarget } from "../registry";
import attendance from ".";
import { CheckInCard } from "./CheckInCard";
import { HeroSlot } from "./slots";
import type { Summary } from "../../api/types";
import { fenceCheck, minutesBetween, monthWeeks, shiftMonth } from "./lib";
import { messages } from "./messages";
import { pageMessages } from "./pageMessages";
import { allMessages, monthTitle } from "./pageText";
import { duration } from "./text";
import type { MyDay } from "./types";

const client = vi.hoisted(() => ({ api: vi.fn(), apiForm: vi.fn() }));
vi.mock("../../api/client", async (importOriginal) => {
  const real = await importOriginal<typeof import("../../api/client")>();
  return { ...real, api: client.api, apiForm: client.apiForm };
});

const CHILONZOR = { id: 3, name: "Chilonzor", code: "CH", latitude: "41.2856000", longitude: "69.2034000", geofence_m: 150 };

function day(overrides: Partial<MyDay> = {}, settings: Partial<MyDay["settings"]> = {}): MyDay {
  return {
    now: "2026-10-21T08:55:00+05:00",
    date: "2026-10-21",
    state: "due",
    settings: { require_location: true, require_photo: false, outside_action: "flag", max_accuracy_m: 200, grace_minutes: 10, ...settings },
    shift: {
      id: 41,
      member_id: 7,
      date: "2026-10-21",
      starts_at: "2026-10-21T09:00:00+05:00",
      ends_at: "2026-10-21T18:00:00+05:00",
      start: "09:00",
      end: "18:00",
      break_minutes: 60,
      minutes: 480,
      branch: { id: 3, name: "Chilonzor", code: "CH" },
      position: null,
      status: "planned",
      source: "schedule",
      published: true,
      note: "",
      time_off_id: null,
      swap_pending: false,
      has_record: false,
    },
    branch: CHILONZOR,
    record: null,
    next_shift: null,
    open_shifts: 0,
    requests: 0,
    ...overrides,
  };
}

const RECORD = {
  id: 90,
  member_id: 7,
  shift_id: 41,
  date: "2026-10-21",
  status: "open",
  check_in_at: "2026-10-21T08:57:00+05:00",
  check_out_at: null,
  in_distance_m: 20,
  out_distance_m: null,
  branch: { id: 3, name: "Chilonzor", code: "CH" },
  late_minutes: 0,
  early_leave_minutes: 0,
  worked_minutes: 0,
  overtime_minutes: 0,
  overtime_status: "none",
  is_late: false,
  flags: [],
  note: "",
  has_photo: false,
};

function serve(today: MyDay, result: object = { record: RECORD, created: true, outside: false, distance_m: 20 }) {
  const respond = async (path: string) => {
    if (path.endsWith("/attendance/today/")) return today;
    if (path.includes("/check-")) return result;
    throw new Error(`unexpected ${path}`);
  };
  client.api.mockImplementation(respond);
  client.apiForm.mockImplementation(respond);
}

function membership(features: string[] = ["attendance"], status = "approved"): Membership {
  return {
    id: 7,
    company: { id: 1, name: "Demo Shop", timezone: "Asia/Tashkent", features, owner_sees_personal_tasks: false, base_currency: "UZS", team_directory_phones: false },
    status,
    first_name: "Alisher",
    last_name: "Valiyev",
    position: null,
    role: "Employee",
    permissions: [],
    is_onboarded: true,
    onboarded_at: null,
    decided_at: null,
    rejoin_available_at: null,
    home_branch: { id: 3, name: "Chilonzor" },
    branch_ids: [3],
    suspended_until: null,
  } as unknown as Membership;
}

function renderCard(node: ReactNode = <CheckInCard />, lang: Lang = "en", permissions: string[] = []) {
  const queries = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const me = {
    id: 1,
    telegram_id: 4242,
    telegram_username: "",
    first_name: "Alisher",
    last_name: "Valiyev",
    phone: "",
    memberships: [{ ...membership(), permissions }],
  } as unknown as Me;
  return render(
    <QueryClientProvider client={queries}>
      <I18nProvider lang={lang}>
        <ToastProvider>
          <SessionProvider me={me}>
            <NavigationProvider>{node}</NavigationProvider>
          </SessionProvider>
        </ToastProvider>
      </I18nProvider>
    </QueryClientProvider>,
  );
}

type Fix = { latitude: number; longitude: number; horizontal_accuracy: number };

/** Telegram 8.0 with a LocationManager that answers `fix` (null: the person said no). */
function telegramWith(fix: Fix | null, manager: Record<string, unknown> = {}) {
  const LocationManager = {
    isInited: true,
    isLocationAvailable: true,
    isAccessRequested: false,
    isAccessGranted: false,
    init: vi.fn((done?: () => void) => done?.()),
    getLocation: vi.fn((callback: (data: Fix | null) => void) => callback(fix)),
    openSettings: vi.fn(),
    ...manager,
  };
  (window as unknown as { Telegram?: unknown }).Telegram = { WebApp: { isVersionAtLeast: () => true, LocationManager } };
  return LocationManager;
}

function browserWith(coords: { latitude: number; longitude: number; accuracy: number } | null) {
  const getCurrentPosition = vi.fn((success: PositionCallback, failure?: PositionErrorCallback | null) => {
    if (coords) success({ coords, timestamp: 1000 } as GeolocationPosition);
    else failure?.({ code: 1, message: "", PERMISSION_DENIED: 1, POSITION_UNAVAILABLE: 2, TIMEOUT: 3 } as GeolocationPositionError);
  });
  Object.defineProperty(navigator, "geolocation", { value: { getCurrentPosition }, configurable: true });
  return getCurrentPosition;
}

const slide = async (name: RegExp) => {
  const knob = await screen.findByRole("button", { name });
  await act(async () => {
    fireEvent.keyDown(knob, { key: "Enter" });
  });
};

const checkInCalls = () => client.api.mock.calls.filter(([path]) => String(path).includes("/check-in/"));

beforeEach(() => {
  client.api.mockReset();
  client.apiForm.mockReset();
});

afterEach(() => {
  cleanup();
  delete (window as unknown as { Telegram?: unknown }).Telegram;
  Object.defineProperty(navigator, "geolocation", { value: undefined, configurable: true });
});

describe("the check-in card", () => {
  it("checks in with Telegram's LocationManager and sends only the position of the tap", async () => {
    serve(day());
    const manager = telegramWith({ latitude: 41.2857, longitude: 69.2035, horizontal_accuracy: 12 });
    const browser = browserWith({ latitude: 1, longitude: 1, accuracy: 5 });
    renderCard();
    expect(await screen.findByText("Shift 09:00–18:00 · Chilonzor")).toBeTruthy();
    await slide(/Slide to check in/);
    await waitFor(() => expect(checkInCalls()).toHaveLength(1));
    expect(checkInCalls()[0]).toEqual(["/companies/1/attendance/check-in/", { method: "POST", json: { lat: "41.285700", lng: "69.203500", accuracy: 12 } }]);
    expect(manager.getLocation).toHaveBeenCalledOnce();
    expect(browser).not.toHaveBeenCalled();
    expect(await screen.findByText("Checked in at 08:57")).toBeTruthy();
  });

  it("falls back to the browser's geolocation where Telegram has no LocationManager", async () => {
    serve(day());
    const browser = browserWith({ latitude: 41.2855, longitude: 69.2033, accuracy: 30 });
    renderCard();
    await slide(/Slide to check in/);
    await waitFor(() => expect(checkInCalls()).toHaveLength(1));
    expect(browser).toHaveBeenCalledOnce();
    expect(checkInCalls()[0][1]).toEqual({ method: "POST", json: { lat: "41.285500", lng: "69.203300", accuracy: 30 } });
  });

  it("asks before checking in outside a geofence that only flags", async () => {
    serve(day(), { record: RECORD, created: true, outside: true, distance_m: 2000 });
    telegramWith({ latitude: 41.3036, longitude: 69.2034, horizontal_accuracy: 10 });
    renderCard();
    await slide(/Slide to check in/);
    expect(await screen.findByText("You’re 2 km from Chilonzor")).toBeTruthy();
    expect(checkInCalls()).toHaveLength(0);
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Check in here" }));
    });
    await waitFor(() => expect(checkInCalls()).toHaveLength(1));
    expect(await screen.findByText("Checked in at 08:57, outside the branch")).toBeTruthy();
  });

  it("explains and sends nothing outside a geofence that rejects", async () => {
    serve(day({}, { outside_action: "reject" }));
    telegramWith({ latitude: 41.3036, longitude: 69.2034, horizontal_accuracy: 10 });
    renderCard();
    await slide(/Slide to check in/);
    expect(await screen.findByText("Check in when you get there.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Check in here" })).toBeNull();
    expect(checkInCalls()).toHaveLength(0);
  });

  it("counts the reading's accuracy before calling a tap outside", async () => {
    serve(day());
    // 200 m away, but only accurate to 80 m: within 150 m + 80 m.
    telegramWith({ latitude: 41.2874, longitude: 69.2034, horizontal_accuracy: 80 });
    renderCard();
    await slide(/Slide to check in/);
    await waitFor(() => expect(checkInCalls()).toHaveLength(1));
  });

  it("offers Telegram's settings when location access was refused", async () => {
    serve(day());
    const manager = telegramWith(null, { isAccessRequested: true, isAccessGranted: false });
    renderCard();
    await slide(/Slide to check in/);
    expect(await screen.findByText("Allow location access so we can see you’re at work.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Open settings" }));
    expect(manager.openSettings).toHaveBeenCalledOnce();
    expect(checkInCalls()).toHaveLength(0);
  });

  it("checks in without a position when the company doesn't require one and none comes", async () => {
    serve(day({}, { require_location: false }));
    browserWith(null);
    renderCard();
    await slide(/Slide to check in/);
    await waitFor(() => expect(checkInCalls()).toHaveLength(1));
    expect(checkInCalls()[0][1]).toEqual({ method: "POST", json: {} });
  });

  it("takes a selfie first when the company asks for one", async () => {
    serve(day({}, { require_photo: true }));
    telegramWith({ latitude: 41.2856, longitude: 69.2034, horizontal_accuracy: 8 });
    const { container } = renderCard();
    await slide(/Slide to check in/);
    expect(await screen.findByText("Take a selfie to check in")).toBeTruthy();
    const send = screen.getByRole("button", { name: "Check in" }) as HTMLButtonElement;
    expect(send.disabled).toBe(true);
    const camera = container.querySelector('input[type="file"][capture="user"]') as HTMLInputElement;
    const selfie = new File(["x"], "me.jpg", { type: "image/jpeg" });
    await act(async () => {
      fireEvent.change(camera, { target: { files: [selfie] } });
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Check in" }));
    });
    await waitFor(() => expect(client.apiForm).toHaveBeenCalledOnce());
    expect(client.apiForm.mock.calls[0]).toEqual(["/companies/1/attendance/check-in/", { lat: "41.285600", lng: "69.203400", accuracy: 8, photo: selfie }]);
  });

  it("checks out while checked in, showing the time so far", async () => {
    const closed = { ...RECORD, status: "closed", check_out_at: "2026-10-21T18:04:00+05:00", worked_minutes: 487 };
    serve(day({ state: "in", record: RECORD as MyDay["record"] }), { record: closed, created: false, outside: false, distance_m: 15 });
    telegramWith({ latitude: 41.2856, longitude: 69.2034, horizontal_accuracy: 8 });
    renderCard();
    expect(await screen.findByText("Checked in at 08:57")).toBeTruthy();
    await slide(/Slide to check out/);
    await waitFor(() => expect(client.api.mock.calls.some(([path]) => String(path).includes("/check-out/"))).toBe(true));
    expect(await screen.findByText("Checked out at 18:04 · 8 h 7 min")).toBeTruthy();
  });

  it("shows the server's reason when it refuses", async () => {
    const { ApiError } = await import("../../api/client");
    serve(day());
    client.api.mockImplementation(async (path: string) => {
      if (path.endsWith("/today/")) return day();
      throw new ApiError(400, { detail: "You're already checked in since 08:57." });
    });
    telegramWith({ latitude: 41.2856, longitude: 69.2034, horizontal_accuracy: 8 });
    renderCard();
    await slide(/Slide to check in/);
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.getAllByText("You're already checked in since 08:57.").length).toBeGreaterThan(0);
  });

  it("speaks Uzbek", async () => {
    serve(day({ state: "off", shift: null }));
    renderCard(<CheckInCard />, "uz");
    expect(await screen.findByText("Hali smena rejalashtirilmagan")).toBeTruthy();
    expect(screen.getByText("Smenalarni rahbaringiz rejalashtiradi, ular shu yerda ko‘rinadi.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Smenasiz belgilash" })).toBeTruthy();
  });

  it("says a shift that began already started", async () => {
    serve(day({ state: "late", now: "2026-10-21T09:40:00+05:00" }));
    renderCard();
    expect(await screen.findByText("Your shift started at 09:00. Check in when you’re there")).toBeTruthy();
  });
});

describe("the check-in card on Home", () => {
  const next = { ...day().shift!, id: 42, date: "2026-10-25", starts_at: "2026-10-25T09:00:00+05:00", ends_at: "2026-10-25T18:00:00+05:00" };
  const dayOff = day({ state: "off", shift: null, next_shift: null });
  const hero = (permissions: string[] = [], summary?: Partial<Summary>) => (
    <HeroSlot member={{ ...membership(), permissions, timeZone: "Asia/Tashkent", companyId: 1 } as never} summary={summary as Summary | undefined} />
  );

  it("is one calm row on a day off, opening the attendance page", async () => {
    serve({ ...dayOff, next_shift: next });
    renderCard(hero());
    const row = await screen.findByRole("button", { name: /No shift today/ });
    expect(row.textContent).toContain("Next shift: Sun, 25 Oct, 09:00–18:00 · Chilonzor");
    // Checking in without a shift stays on the attendance page.
    expect(screen.queryByRole("button", { name: /Check in without a shift/ })).toBeNull();
  });

  it("says once that nothing is planned yet, and who plans it, for someone new", async () => {
    serve(dayOff);
    renderCard(hero());
    const row = await screen.findByRole("button", { name: /No shifts planned yet/ });
    expect(row.textContent).toContain("Your manager plans them, and they show up here.");
    expect(row.textContent).not.toContain("No shift today");
  });

  it("stays away for an owner without shifts and on a day off the person asked for", async () => {
    serve(dayOff);
    const owner = renderCard(hero(["dashboard.access"]));
    await waitFor(() => expect(client.api).toHaveBeenCalled());
    await act(async () => undefined);
    await waitFor(() => expect(owner.container.innerHTML).toBe(""));
    cleanup();

    serve({ ...dayOff, next_shift: next });
    const resting = renderCard(hero([], { off_today: { kind: "time_off", name: "", until: "2026-10-22" } }));
    await act(async () => undefined);
    await waitFor(() => expect(resting.container.innerHTML).toBe(""));
  });

  it("is still the full card when there is something to slide", async () => {
    serve(day());
    renderCard(hero(["dashboard.access"]));
    expect(await screen.findByRole("button", { name: /Slide to check in/ })).toBeTruthy();
  });
});

describe("who's in (managers)", () => {
  const person = (id: number, name: string) => ({ id, name, photo_url: null, position: { id: 1, name: "Cashier" }, home_branch: { id: 3, name: "Chilonzor" }, status: "approved" });
  const board = {
    date: "2026-10-21",
    is_today: true,
    now: "2026-10-21T10:20:00+05:00",
    holiday: null,
    totals: { in: 1, late: 1, not_yet: 1, absent: 0, off: 1, rostered: 3, late_missing: 1 },
    branches: [],
    people: [
      { member: person(1, "Bekzod Mirzayev"), branch: null, state: "in", reason: null, shift: day().shift, record: { ...RECORD, in_distance_m: 39 } },
      { member: person(2, "Alisher Valiyev"), branch: null, state: "late", reason: null, shift: day().shift, record: { ...RECORD, id: 91, is_late: true, late_minutes: 25 } },
      { member: person(3, "Jasur Tursunov"), branch: null, state: "not_yet", reason: "late", shift: day().shift, record: null },
      { member: person(4, "Madina Saidova"), branch: null, state: "off", reason: "leave", shift: null, record: null },
    ],
  };

  it("lists today's people by state, the urgent ones first, with lateness and distance", async () => {
    client.api.mockImplementation(async (path: string) => {
      if (path.endsWith("/attendance/board/")) return board;
      throw new Error(`unexpected ${path}`);
    });
    const { default: BoardPage } = await import("./BoardPage");
    renderCard(<BoardPage />, "en", ["attendance.view"]);
    expect(await screen.findByText("Bekzod Mirzayev")).toBeTruthy();
    const sections = screen.getAllByRole("region").map((section) => section.getAttribute("aria-label"));
    expect(sections).toEqual(["Came late", "Not here yet", "In", "Off today"]);
    expect(screen.getByText("2 of 3 on shift are here")).toBeTruthy();
    expect(screen.getByText("+25 min")).toBeTruthy();
    expect(screen.getByText("+1 h 20 min")).toBeTruthy();
    expect(screen.getByText("40 m")).toBeTruthy();
    expect(screen.getByText(/Shift started 09:00/)).toBeTruthy();
    expect(screen.getByText(/Time off/)).toBeTruthy();
  });

  it("says it's for managers, without asking the server, when a link opens it for someone else", async () => {
    const { default: BoardPage } = await import("./BoardPage");
    renderCard(<BoardPage />);
    expect(await screen.findByText("For managers only")).toBeTruthy();
    expect(client.api).not.toHaveBeenCalled();
  });

  it("is in Me only for people who may see everyone's attendance", () => {
    const item = attendance.meItems!.find((entry) => entry.id === "board")!;
    const context = { member: { ...membership(), timeZone: "Asia/Tashkent", companyId: 1 }, summary: undefined };
    expect(item.visible!(context.member as never, undefined)).toBe(false);
    expect(item.visible!({ ...context.member, permissions: ["attendance.view"] } as never, undefined)).toBe(true);
  });
});

describe("the attendance feature", () => {
  it("shows for approved people while the module is on", () => {
    const context = (member: Membership) => ({ member: { ...member, timeZone: "Asia/Tashkent", companyId: 1 }, summary: undefined });
    expect(featureVisible(attendance as never, context(membership()))).toBe(true);
    expect(featureVisible(attendance as never, context(membership([])))).toBe(false);
    expect(featureVisible(attendance as never, context(membership(["attendance"], "suspended")))).toBe(false);
  });

  it("answers the bot's and the notifications' deep links", () => {
    const list = [attendance as never];
    expect(routeTarget(list, "attendance", null)).toEqual({ tab: "home", stack: [{ feature: "attendance", page: "home", params: {} }] });
    expect(routeTarget(list, "attendance.swaps", null)).toEqual({ tab: "home", stack: [{ feature: "attendance", page: "swaps", params: {} }] });
    expect(routeTarget(list, "attendance.correct", "12")).toEqual({
      tab: "home",
      sheet: { kind: "feature", feature: "attendance", sheet: "correct", params: { record: 12 } },
    });
  });
});

describe("helpers", () => {
  it("judge the geofence like the server", () => {
    expect(fenceCheck(CHILONZOR, { latitude: 41.2856, longitude: 69.2034, accuracy: 5 })).toEqual({ distance: 0, outside: false });
    const far = fenceCheck(CHILONZOR, { latitude: 41.2874, longitude: 69.2034, accuracy: 10 })!;
    expect(Math.round(far.distance)).toBe(200);
    expect(far.outside).toBe(true);
    expect(fenceCheck(CHILONZOR, { latitude: 41.2874, longitude: 69.2034, accuracy: 80 })!.outside).toBe(false);
    // Accuracy never stretches the fence by more than the fence itself.
    expect(fenceCheck(CHILONZOR, { latitude: 41.2886, longitude: 69.2034, accuracy: 5000 })!.outside).toBe(true);
    expect(fenceCheck({ ...CHILONZOR, latitude: null }, { latitude: 41, longitude: 69, accuracy: 5 })).toBeNull();
    expect(fenceCheck(null, { latitude: 41, longitude: 69, accuracy: 5 })).toBeNull();
  });

  it("lay a month out Monday first", () => {
    const weeks = monthWeeks("2026-10");
    expect(weeks).toHaveLength(5);
    expect(weeks[0]).toEqual([null, null, null, "2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04"]);
    expect(weeks[4]).toEqual(["2026-10-26", "2026-10-27", "2026-10-28", "2026-10-29", "2026-10-30", "2026-10-31", null]);
    expect(shiftMonth("2026-01", -1)).toBe("2025-12");
    expect(shiftMonth("2026-12", 1)).toBe("2027-01");
  });

  it("count and word durations", () => {
    expect(minutesBetween("2026-10-21T08:57:00+05:00", "2026-10-21T18:04:00+05:00")).toBe(547);
    expect(minutesBetween("2026-10-21T18:00:00+05:00", "2026-10-21T08:00:00+05:00")).toBe(0);
    const en = featureTranslator(messages, "en");
    const uz = featureTranslator(messages, "uz");
    const ru = featureTranslator(messages, "ru");
    expect(duration(en, 487)).toBe("8 h 7 min");
    expect(duration(en, 45)).toBe("45 min");
    expect(duration(uz, 120)).toBe("2 soat");
    expect(duration(ru, 61)).toBe("1 ч 1 мин");
    expect(ru("home.requests", { count: 5 })).toBe("5 запросов на обмен ждут вас");
    expect(monthTitle(featureTranslator(allMessages, "uz"), "2026-10")).toBe("2026-yil oktabr");
    expect(monthTitle(featureTranslator(allMessages, "en"), "2026-10")).toBe("October 2026");
  });
});

describe("the pages' strings", () => {
  // The app's parity test checks the registered (Home) messages; these load with the pages.
  const placeholders = (text: string) => [...text.matchAll(/\{(\w+)\}/g)].map((match) => match[1]).sort();

  it("have the same keys and placeholders in every language, and Uzbek marks", () => {
    const english = Object.keys(pageMessages.en).sort();
    for (const lang of ["ru", "uz"] as const) {
      const dictionary = pageMessages[lang] as Record<string, string>;
      expect(Object.keys(dictionary).sort()).toEqual(english);
      for (const key of english) {
        expect(dictionary[key].trim(), `${lang} ${key}`).not.toBe("");
        expect(placeholders(dictionary[key]), `${lang} ${key}`).toEqual(placeholders((pageMessages.en as Record<string, string>)[key]));
      }
    }
    for (const [key, value] of Object.entries(pageMessages.uz)) {
      expect(/[`']/.test(value), `uz ${key} uses an ASCII quote`).toBe(false);
      expect(/[oOgG][’ʻʼ]/.test(value), `uz ${key} spells o‘/g‘ with the wrong mark`).toBe(false);
    }
    // No key is defined twice (the page set overrides nothing of the card's).
    expect(Object.keys(pageMessages.en).filter((key) => key in messages.en)).toEqual([]);
  });
});
