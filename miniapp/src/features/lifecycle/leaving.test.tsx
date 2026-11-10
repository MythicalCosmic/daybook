/**
 * "Ishdan ketish" and "Mening tarixim": what the leaving page shows in each state, the letter sent
 * after a confirm, "I'm staying", the agreed day with the handover and the questions before I go,
 * Home's card, Me's row, the bot's links, and the career timeline.
 */
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { featureTranslator } from "../../i18n/feature";
import { formatMoney } from "../../lib/money";
import { resolveScreen } from "../../state/deeplink";
import { membership, navigationState, person, renderApp, routeApi } from "../../test/harness";
import { features, findFeature } from "../registry";
import type { LeavingState, MyCareer, MyHandoverItem, MyJobChange, MyLeaving } from "./api";
import CareerPage from "./CareerPage";
import LeavingPage from "./LeavingPage";
import {
  closedNote,
  daysBetween,
  exitPayload,
  handoverProgress,
  leavePayload,
  leavingStage,
  partChanges,
  splitCareer,
  suggestedLastDay,
} from "./lib";
import { messages } from "./messages";
import { LeavingCard } from "./slots";
import { daysLeftText, handoverLabel, keepTogether } from "./text";

const client = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("../../api/client", async (importOriginal) => {
  const real = await importOriginal<typeof import("../../api/client")>();
  return { ...real, api: client.api };
});

const lifecycle = findFeature(features, "lifecycle")!;
const company = { id: 1, name: "Demo Dorixona", timezone: "Asia/Tashkent", features: ["hr", "payroll"], base_currency: "UZS" };
const me = person([membership({ company } as never)]);
const member = { ...me.memberships[0], timeZone: "Asia/Tashkent", companyId: 1 };
const en = featureTranslator(messages, "en");
/** Text with every run of spaces (no-break ones from money formatting included) as one space. */
const flat = (text: string) => text.replace(/\s+/g, " ");

const HANDOVER: MyHandoverItem[] = [
  { id: 5, kind: "equipment", title: "AV-0013 Kuryer skuteri Yadea", done: false, open_tasks: null },
  { id: 6, kind: "tasks", title: "", done: false, open_tasks: 3 },
  { id: 7, kind: "keys", title: "", done: true, open_tasks: null },
  { id: 8, kind: "documents", title: "", done: false, open_tasks: null },
];

function leaving(extra: Partial<MyLeaving> = {}): MyLeaving {
  return {
    id: 2,
    kind: "resignation",
    status: "agreed",
    mine: true,
    wished_last_day: "2026-11-20",
    last_day: "2026-11-20",
    left_on: null,
    reason: "Uyimga yaqinroq ish topdim.",
    requested_at: "2026-11-07T09:40:00+05:00",
    agreed_at: "2026-11-08T11:15:00+05:00",
    agreed_by: "Dilnoza Karimova",
    close_reason: "",
    closed_by_me: false,
    notice_days: 13,
    handover: HANDOVER,
    exit_interview: null,
    can_withdraw: true,
    can_answer: true,
    ...extra,
  };
}

function state(current: MyLeaving | null, extra: Partial<LeavingState> = {}): LeavingState {
  return { current, can_request: current === null || !["requested", "agreed"].includes(current.status), notice_days: 14, today: "2026-11-10", ...extra };
}

afterEach(() => {
  cleanup();
  client.api.mockReset();
  vi.restoreAllMocks();
});

describe("what my leaving page shows", () => {
  it("follows the request: the letter, waiting, the day agreed, or nothing to ask from here", () => {
    expect(leavingStage(state(null))).toBe("form");
    expect(leavingStage(state(leaving({ status: "requested" })))).toBe("requested");
    expect(leavingStage(state(leaving()))).toBe("agreed");
    expect(leavingStage(state(leaving({ status: "declined" })))).toBe("form");
    expect(leavingStage(state(null, { can_request: false }))).toBe("none");
  });

  it("says why a request closed lately: declined, withdrawn by me, called off by HR", () => {
    expect(closedNote(state(leaving({ status: "declined" })))).toBe("declined");
    expect(closedNote(state(leaving({ status: "withdrawn", closed_by_me: true })))).toBe("withdrawnByMe");
    expect(closedNote(state(leaving({ status: "withdrawn" })))).toBe("calledOff");
    expect(closedNote(state(leaving()))).toBeNull();
    expect(closedNote(state(null))).toBeNull();
  });

  it("counts calendar days and suggests the usual two weeks' notice", () => {
    expect(daysBetween("2026-11-10", "2026-11-20")).toBe(10);
    expect(daysBetween("2026-12-31", "2027-01-01")).toBe(1);
    expect(suggestedLastDay(state(null))).toBe("2026-11-24");
    expect(daysLeftText(en, 0)).toBe("Today");
    expect(daysLeftText(en, 1)).toBe("Tomorrow");
    expect(daysLeftText(en, 10)).toBe("10 days left");
    // An Uzbek date never wraps between "20-" and its month.
    expect(keepTogether("Juma, 20-noyabr")).toBe("Juma, 20‑noyabr");
    expect(keepTogether("Ish-vaqti")).toBe("Ish-vaqti");
  });

  it("sends a day from today on, with the reason trimmed and never too long", () => {
    expect(leavePayload("2026-11-24", "  Moving  ", "2026-11-10")).toEqual({ wished_last_day: "2026-11-24", reason: "Moving" });
    expect(leavePayload("2026-11-10", "", "2026-11-10")).toEqual({ wished_last_day: "2026-11-10", reason: "" });
    expect(leavePayload("2026-11-09", "", "2026-11-10")).toBeNull();
    expect(leavePayload("", "", "2026-11-10")).toBeNull();
    expect(leavePayload("2026-11-24", "x".repeat(2001), "2026-11-10")).toBeNull();
  });

  it("asks only the main reason before I go; the rest may stay empty", () => {
    expect(exitPayload(null, "", null)).toBeNull();
    expect(exitPayload("moving", "  Fewer nights  ", null)).toEqual({ reason: "moving", better: "Fewer nights", recommend: "" });
    expect(exitPayload("pay", "", "maybe")).toEqual({ reason: "pay", better: "", recommend: "maybe" });
    expect(exitPayload("pay", "x".repeat(1001), "yes")).toBeNull();
  });

  it("names the standard handover items and counts what is handed over", () => {
    expect(handoverLabel(en, HANDOVER[0])).toBe("AV-0013 Kuryer skuteri Yadea");
    expect(handoverLabel(en, HANDOVER[2])).toBe("Keys: the pharmacy, the safe, the cabinets");
    expect(handoverProgress(HANDOVER)).toEqual({ done: 1, total: 4 });
  });
});

describe("the leaving page", () => {
  it("sends the letter with the day two weeks ahead, after a confirm, and then waits", async () => {
    const bodies: unknown[] = [];
    routeApi(client.api, {
      "/lifecycle/leaving/": state(null),
      "POST /lifecycle/leaving/": (body: unknown) => (bodies.push(body), state(leaving({ status: "requested", last_day: null, agreed_at: null, agreed_by: null, wished_last_day: "2026-11-24", notice_days: 14, handover: [] }))),
    });
    const asked = vi.spyOn(window, "confirm").mockReturnValue(true);
    renderApp(<LeavingPage />, { me });
    expect(await screen.findByText("Resignation letter")).toBeTruthy();
    expect(screen.getByText("Notice: 14 days")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Reason (if you want to say)"), { target: { value: "  We are moving to Samarkand  " } });
    fireEvent.click(screen.getByRole("button", { name: "Send the request" }));
    await waitFor(() => expect(bodies).toEqual([{ wished_last_day: "2026-11-24", reason: "We are moving to Samarkand" }]));
    expect(asked).toHaveBeenCalledWith("Send your request to leave? Last working day: Tuesday, 24 November.");
    expect(await screen.findByText("Waiting for your manager")).toBeTruthy();
    expect(screen.getByText("Notice")).toBeTruthy();
    expect(screen.getByText("14 days")).toBeTruthy();
  });

  it("sends nothing when the confirm is turned down", async () => {
    routeApi(client.api, { "/lifecycle/leaving/": state(null) });
    vi.spyOn(window, "confirm").mockReturnValue(false);
    renderApp(<LeavingPage />, { me });
    fireEvent.click(await screen.findByRole("button", { name: "Send the request" }));
    await waitFor(() => expect(window.confirm).toHaveBeenCalled());
    expect(client.api.mock.calls.filter(([, options]) => options?.json)).toEqual([]);
  });

  it("says a declined request's reason above a new letter", async () => {
    routeApi(client.api, { "/lifecycle/leaving/": state(leaving({ status: "declined", close_reason: "We talked: you stay with us", last_day: null })) });
    renderApp(<LeavingPage />, { me });
    expect(await screen.findByText("Your request to leave was declined")).toBeTruthy();
    expect(screen.getByText("Reason: We talked: you stay with us You can ask again below.")).toBeTruthy();
    expect(screen.getByText("Resignation letter")).toBeTruthy();
  });

  it("lets me stay while the request waits", async () => {
    let withdrawn = 0;
    routeApi(client.api, {
      "/lifecycle/leaving/": state(leaving({ status: "requested", last_day: null, agreed_by: null })),
      "POST /lifecycle/leaving/2/withdraw/": () => ((withdrawn += 1), state(leaving({ status: "withdrawn", closed_by_me: true, last_day: null }))),
    });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    renderApp(<LeavingPage />, { me });
    expect(await screen.findByText("Waiting for your manager")).toBeTruthy();
    expect(screen.getByText("Uyimga yaqinroq ish topdim.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "I’m staying: withdraw the request" }));
    expect(await screen.findByText("You withdrew your request and are staying")).toBeTruthy();
    expect(withdrawn).toBe(1);
  });

  it("shows the agreed day, the handover list and the questions before I go", async () => {
    const bodies: unknown[] = [];
    routeApi(client.api, {
      "/lifecycle/leaving/": state(leaving()),
      "POST /lifecycle/leaving/2/exit/": (body: unknown) => (bodies.push(body), state(leaving({ exit_interview: { reason: "moving", better: "", recommend: "yes", answered_at: "2026-11-10T12:00:00+05:00" } }))),
    });
    renderApp(<LeavingPage />, { me });
    const day = await screen.findByTestId("last-day");
    expect(within(day).getByText("Friday, 20 November")).toBeTruthy();
    expect(within(day).getByText("10 days left")).toBeTruthy();
    expect(within(day).getByText("Agreed with Dilnoza Karimova")).toBeTruthy();
    const items = screen.getAllByTestId("handover-item").map((item) => item.textContent);
    expect(items).toEqual([
      "AV-0013 Kuryer skuteri YadeaNot handed over yet",
      "Your open tasks3 open tasks: finish them or hand them over",
      "Keys: the pharmacy, the safe, the cabinetsHanded over",
      "Company documents and stampsNot handed over yet",
    ]);
    expect(screen.getByText("Handed over: 1. Still to go: 3.")).toBeTruthy();

    const form = screen.getByTestId("exit-form");
    const send = within(form).getByRole("button", { name: "Send the answers" }) as HTMLButtonElement;
    expect(send.disabled).toBe(true);
    fireEvent.click(within(form).getByRole("button", { name: "Moving" }));
    fireEvent.click(within(form).getByRole("button", { name: "Yes" }));
    fireEvent.click(send);
    await waitFor(() => expect(bodies).toEqual([{ reason: "moving", better: "", recommend: "yes" }]));
    const answers = await screen.findByTestId("exit-answers");
    expect(within(answers).getByText("Main reason: Moving")).toBeTruthy();
    expect(within(answers).getByText("Would recommend: Yes")).toBeTruthy();
    fireEvent.click(within(answers).getByRole("button", { name: "Change the answers" }));
    expect(screen.getByTestId("exit-form")).toBeTruthy();
  });

  it("thanks me on my last day, with no way back from here", async () => {
    routeApi(client.api, { "/lifecycle/leaving/": state(leaving({ can_withdraw: false }), { today: "2026-11-20" }) });
    renderApp(<LeavingPage />, { me });
    expect(await screen.findByText("Today is your last working day. Thank you for your work!")).toBeTruthy();
    expect(within(screen.getByTestId("last-day")).getByText("Today")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "I’m staying: withdraw the request" })).toBeNull();
  });

  it("has no letter for someone who can't ask from here", async () => {
    routeApi(client.api, { "/lifecycle/leaving/": state(null, { can_request: false }) });
    renderApp(<LeavingPage />, { me });
    expect(await screen.findByText("Nothing here now")).toBeTruthy();
    expect(screen.queryByText("Resignation letter")).toBeNull();
  });
});

describe("Home, Me and the bot's links", () => {
  it("puts the agreed day on Home and on Me's row, and Waiting while the manager hasn't answered", async () => {
    routeApi(client.api, { "/lifecycle/leaving/": state(leaving()) });
    const row = lifecycle.meItems!.find((item) => item.id === "leaving")!;
    function Status() {
      const status = row.useStatus!({ member, summary: undefined });
      return <div data-testid="status">{String(status.value ?? "")}</div>;
    }
    renderApp(
      <>
        <LeavingCard member={member} summary={undefined} />
        <Status />
      </>,
      { me },
    );
    fireEvent.click(await screen.findByText("Your last working day: Friday, 20 November"));
    expect(navigationState().stack).toEqual([{ feature: "lifecycle", page: "leaving" }]);
    expect(screen.getByTestId("status").textContent).toBe("20 Nov");
    cleanup();
    routeApi(client.api, { "/lifecycle/leaving/": state(leaving({ status: "requested", last_day: null })) });
    renderApp(
      <>
        <LeavingCard member={member} summary={undefined} />
        <Status />
      </>,
      { me },
    );
    await waitFor(() => expect(screen.getByTestId("status").textContent).toBe("Waiting"));
    expect(screen.queryByText(/Your last working day/)).toBeNull();
  });

  it("opens from the bot's links over Me", () => {
    expect(resolveScreen({ name: "lifecycle.leaving", arg: null }, features)).toEqual({ tab: "profile", stack: [{ feature: "lifecycle", page: "leaving", params: {} }] });
    expect(resolveScreen({ name: "leaving", arg: null }, features)).toEqual({ tab: "profile", stack: [{ feature: "lifecycle", page: "leaving", params: {} }] });
    expect(resolveScreen({ name: "lifecycle.career", arg: null }, features)).toEqual({ tab: "profile", stack: [{ feature: "lifecycle", page: "career", params: {} }] });
  });
});

describe("my career", () => {
  const side = (position: string, pay: string) => ({
    position: { id: 1, name: position },
    branch: { id: 1, name: "Chilonzor" },
    branches: [{ id: 1, name: "Chilonzor" }],
    department: null,
    role: null,
    pay: { amount: pay, currency: "UZS", pay_type: "monthly" as const },
  });
  const promotion: MyJobChange = {
    id: 1,
    effective_on: "2026-11-01",
    status: "applied",
    parts: ["position"],
    before: side("Pharmacist", "5200000.00"),
    after: side("Senior pharmacist", "5200000.00"),
    applied_at: "2026-11-01T00:05:00+05:00",
  };
  const raise: MyJobChange = {
    id: 2,
    effective_on: "2026-12-01",
    status: "approved",
    parts: ["pay"],
    before: side("Senior pharmacist", "5200000.00"),
    after: side("Senior pharmacist", "6500000.00"),
    applied_at: null,
  };

  it("puts what is to come first, then what took effect, one line per part", () => {
    const { coming, applied } = splitCareer([promotion, raise]);
    expect(coming.map((change) => change.id)).toEqual([2]);
    expect(applied.map((change) => change.id)).toEqual([1]);
    expect(partChanges(promotion, () => "pay")).toEqual([{ part: "position", was: "Pharmacist", now: "Senior pharmacist" }]);
    expect(partChanges(raise, (pay) => pay.amount)).toEqual([{ part: "pay", was: "5200000.00", now: "6500000.00" }]);
  });

  it("shows my job now, the raise to come and the promotion, and the day I joined", async () => {
    const career: MyCareer = { hired_on: "2025-02-17", position: "Senior pharmacist", branch: "Chilonzor", department: "Chilonzor dorixonasi", changes: [promotion, raise] };
    routeApi(client.api, { "/lifecycle/career/": career });
    renderApp(<CareerPage />, { me });
    const now = await screen.findByTestId("career-now");
    expect(within(now).getByText("Senior pharmacist")).toBeTruthy();
    expect(within(now).getByText("Chilonzor · Chilonzor dorixonasi")).toBeTruthy();
    const [coming, done] = screen.getAllByTestId("career-change");
    expect(within(coming).getByText("From 1 December 2026")).toBeTruthy();
    expect(within(coming).getByText("Approved")).toBeTruthy();
    expect(flat(coming.textContent ?? "")).toContain(flat(`${formatMoney("6500000.00", "UZS", "en")} a month`));
    expect(within(done).getByText("1 November 2026")).toBeTruthy();
    expect(within(done).getByText("Pharmacist")).toBeTruthy();
    expect(screen.getByTestId("career-joined").textContent).toBe("Joined: 17 February 2025");
  });

  it("says calmly that nothing changed yet", async () => {
    routeApi(client.api, { "/lifecycle/career/": { hired_on: null, position: null, branch: null, department: null, changes: [] } });
    renderApp(<CareerPage />, { me });
    expect(await screen.findByText("No job changes yet")).toBeTruthy();
    expect(screen.getByText("No position yet")).toBeTruthy();
  });
});
