/**
 * "My record": where a record stands, "I've read it", the explanation written once, the calm
 * empty page, Home's card, Me's bubble and the bot's link.
 */
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { resolveScreen } from "../../state/deeplink";
import { membership, navigationState, person, renderApp, routeApi } from "../../test/harness";
import { features, findFeature } from "../registry";
import { recordKeys, type DisciplinaryRecord } from "./api";
import ExplainSheet from "./ExplainSheet";
import { canExplain, explainPayload, recordStage, splitRecords, toAcknowledge } from "./lib";
import RecordPage from "./RecordPage";
import RecordsPage from "./RecordsPage";
import { RecordCard } from "./slots";

const client = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("../../api/client", async (importOriginal) => {
  const real = await importOriginal<typeof import("../../api/client")>();
  return { ...real, api: client.api };
});

const lifecycle = findFeature(features, "lifecycle")!;
const company = { id: 1, name: "Demo Dorixona", timezone: "Asia/Tashkent", features: ["hr", "payroll"], base_currency: "UZS" };
const me = person([membership({ company } as never)]);
const member = { ...me.memberships[0], timeZone: "Asia/Tashkent", companyId: 1 };

function record(extra: Partial<DisciplinaryRecord> = {}): DisciplinaryRecord {
  return {
    id: 3,
    kind: "written_warning",
    category: "storage_breach",
    incident_on: "2026-10-30",
    issued_on: "2026-10-31",
    issued_by: "Bekzod Mirzayev",
    description: "The fridge reached +9 °C and the insulin wasn't moved.",
    expires_on: "2027-04-30",
    active: true,
    status: "issued",
    read_at: null,
    acknowledged_at: null,
    employee_response: "",
    responded_at: null,
    has_fine: false,
    withdraw_reason: "",
    ...extra,
  };
}

afterEach(() => {
  cleanup();
  client.api.mockReset();
});

describe("where a record stands", () => {
  it("waits for I've read it, then counts until its end, unless it was withdrawn", () => {
    expect(recordStage(record())).toBe("toRead");
    expect(recordStage(record({ status: "acknowledged" }))).toBe("done");
    expect(recordStage(record({ status: "acknowledged", active: false }))).toBe("past");
    expect(recordStage(record({ status: "withdrawn", active: false }))).toBe("withdrawn");
    expect(toAcknowledge([record(), record({ id: 4, status: "acknowledged" })]).map((row) => row.id)).toEqual([3]);
  });

  it("puts the ones still counting first", () => {
    const rows = [record({ id: 1 }), record({ id: 2, status: "withdrawn", active: false }), record({ id: 3, status: "acknowledged", active: false })];
    const { current, earlier } = splitRecords(rows);
    expect(current.map((row) => row.id)).toEqual([1]);
    expect(earlier.map((row) => row.id)).toEqual([2, 3]);
  });

  it("takes one explanation, trimmed, on a record that stands", () => {
    expect(canExplain(record())).toBe(true);
    expect(canExplain(record({ employee_response: "Done" }))).toBe(false);
    expect(canExplain(record({ status: "withdrawn" }))).toBe(false);
    expect(explainPayload("  The power went off  ")).toEqual({ text: "The power went off" });
    expect(explainPayload(" ")).toBeNull();
    expect(explainPayload("x".repeat(2001))).toBeNull();
  });
});

describe("a record", () => {
  it("is read, and I've read it marks it so here and in the list", async () => {
    let acknowledged = 0;
    routeApi(client.api, {
      "/lifecycle/records/3/": record({ read_at: "2026-11-02T19:00:00+05:00" }),
      "POST /lifecycle/records/3/acknowledge/": () => ((acknowledged += 1), record({ status: "acknowledged", acknowledged_at: "2026-11-02T19:01:00+05:00", read_at: "2026-11-02T19:00:00+05:00" })),
    });
    const { client: cache } = renderApp(<RecordPage params={{ id: 3 }} />, {
      me,
      seed: (queries) => queries.setQueryData(recordKeys.list(1), [record()]),
    });
    expect(await screen.findByText("The fridge reached +9 °C and the insulin wasn't moved.")).toBeTruthy();
    expect(screen.getByText("Please confirm you have read it")).toBeTruthy();
    expect(screen.getByText("Counts until: 30 April 2027")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "I’ve read it" }));
    expect(await screen.findByText("You read it: 2 November")).toBeTruthy();
    expect(acknowledged).toBe(1);
    expect(cache.getQueryData<DisciplinaryRecord[]>(recordKeys.list(1))?.[0].status).toBe("acknowledged");
    // Reading it isn't the end: the person can still write their side.
    expect(screen.getByRole("button", { name: "Write an explanation" })).toBeTruthy();
  });

  it("shows my explanation instead of the button once it is written, and a withdrawn one says so", async () => {
    routeApi(client.api, {
      "/lifecycle/records/3/": record({ status: "acknowledged", employee_response: "The power went off at night.", responded_at: "2026-11-01T09:00:00+05:00" }),
    });
    renderApp(<RecordPage params={{ id: 3 }} />, { me });
    expect(await screen.findByText("The power went off at night.")).toBeTruthy();
    expect(screen.getByText("Your explanation, 1 November")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Write an explanation" })).toBeNull();
    cleanup();
    routeApi(client.api, { "/lifecycle/records/3/": record({ status: "withdrawn", active: false, withdraw_reason: "The fridge was faulty." }) });
    renderApp(<RecordPage params={{ id: 3 }} />, { me });
    expect(await screen.findByText("This record was withdrawn")).toBeTruthy();
    expect(screen.getByText("Reason: The fridge was faulty.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "I’ve read it" })).toBeNull();
  });

  it("points to My pay when a fine came with it", async () => {
    routeApi(client.api, { "/lifecycle/records/3/": record({ status: "acknowledged", has_fine: true }) });
    renderApp(<RecordPage params={{ id: 3 }} />, { me });
    fireEvent.click(await screen.findByText("A fine was proposed with it"));
    expect(navigationState().stack).toEqual([{ feature: "wallet", page: "adjustments" }]);
  });

  it("takes the explanation from its sheet, once, trimmed", async () => {
    const bodies: unknown[] = [];
    routeApi(client.api, {
      "/lifecycle/records/": [record()],
      "POST /lifecycle/records/3/explain/": (body: unknown) => (bodies.push(body), record({ employee_response: "The power went off.", responded_at: "2026-11-02T19:00:00+05:00" })),
    });
    const closed = vi.fn();
    renderApp(<ExplainSheet params={{ id: 3 }} close={closed} />, { me });
    const send = (await screen.findByRole("button", { name: "Send" })) as HTMLButtonElement;
    expect(send.disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("What happened, in your words"), { target: { value: "  The power went off.  " } });
    fireEvent.click(send);
    await waitFor(() => expect(closed).toHaveBeenCalled());
    expect(bodies).toEqual([{ text: "The power went off." }]);
  });
});

describe("my record", () => {
  it("says calmly that there is nothing", async () => {
    routeApi(client.api, { "/lifecycle/records/": [] });
    renderApp(<RecordsPage />, { me });
    expect(await screen.findByText("You have no warnings or reprimands.")).toBeTruthy();
  });

  it("lists what still counts and what came before", async () => {
    routeApi(client.api, { "/lifecycle/records/": [record(), record({ id: 1, kind: "verbal_warning", category: "lateness", status: "acknowledged", active: false, employee_response: "Bus was late." })] });
    renderApp(<RecordsPage />, { me });
    expect(await screen.findByText("Still counting")).toBeTruthy();
    expect(screen.getByText("Earlier")).toBeTruthy();
    expect(screen.getByText("Your explanation is in")).toBeTruthy();
    expect(screen.getByText("No longer counts")).toBeTruthy();
  });

  it("puts a calm card on Home for a record to read, and a bubble on Me", async () => {
    routeApi(client.api, { "/lifecycle/records/": [record(), record({ id: 1, status: "acknowledged" })] });
    function Row() {
      const status = lifecycle.meItems![0].useStatus!({ member, summary: undefined });
      return <div data-testid="status">{String(status.badge)}</div>;
    }
    renderApp(
      <>
        <RecordCard member={member} summary={undefined} />
        <Row />
      </>,
      { me },
    );
    fireEvent.click(await screen.findByText("A new disciplinary record"));
    expect(navigationState().stack).toEqual([{ feature: "lifecycle", page: "record", params: { id: 3 } }]);
    expect(screen.getByTestId("status").textContent).toBe("1");
  });

  it("opens from the bot's link over Me", () => {
    const record3 = { tab: "profile", stack: [{ feature: "lifecycle", page: "record", params: { id: 3 } }] };
    expect(resolveScreen({ name: "lifecycle.record", arg: "3" }, features)).toEqual(record3);
    expect(resolveScreen({ name: "record", arg: "3" }, features)).toEqual(record3);
  });
});
