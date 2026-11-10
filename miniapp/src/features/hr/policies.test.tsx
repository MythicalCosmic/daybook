/**
 * The rules to read and sign: the list (what to sign first), one rule with its text, file and
 * "I have read it and agree" (asked first, signed once), what a signed one says, Home's card and
 * Me's bubble, and the bot's links.
 */
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { resolveScreen } from "../../state/deeplink";
import { membership, navigationState, person, renderApp, routeApi } from "../../test/harness";
import { features, findFeature } from "../registry";
import HrPage from "./HrPage";
import PoliciesPage from "./PoliciesPage";
import type { MyPolicy, MyPolicyDetail } from "./policies";
import PolicyPage from "./PolicyPage";
import { PoliciesCard } from "./slots";

const client = vi.hoisted(() => ({ api: vi.fn(), apiForm: vi.fn() }));
vi.mock("../../api/client", async (importOriginal) => {
  const real = await importOriginal<typeof import("../../api/client")>();
  return { ...real, api: client.api, apiForm: client.apiForm };
});

const hr = findFeature(features, "hr")!;
const company = { id: 1, name: "Demo Dorixona", timezone: "Asia/Tashkent", features: ["hr"], base_currency: "UZS" };
const me = person([membership({ company } as never)]);
const member = { ...me.memberships[0], timeZone: "Asia/Tashkent", companyId: 1 };

function rule(extra: Partial<MyPolicy> = {}): MyPolicy {
  return {
    id: 4,
    title: "Saqlash va harorat rejimi",
    category: "storage",
    number: 2,
    published_at: "2026-11-01T09:15:00+05:00",
    state: "waiting",
    due_on: "2026-11-08",
    signed_at: null,
    signed_number: null,
    has_file: false,
    ...extra,
  };
}

function detail(extra: Partial<MyPolicyDetail> = {}): MyPolicyDetail {
  return {
    ...rule(),
    version_id: 31,
    body: "<h2>1. Harorat</h2><p>Muzlatgich: +2 dan +8 gacha.</p><script>alert(1)</script>",
    change_note: "Jurnal vaqtlari aniqlashtirildi",
    asks_again: true,
    file_type: null,
    ...extra,
  };
}

afterEach(() => {
  cleanup();
  client.api.mockReset();
  vi.restoreAllMocks();
});

describe("the list", () => {
  it("puts what to sign first (late on top), then the signed ones and those only to read", async () => {
    routeApi(client.api, {
      "/hr/policies/": [
        rule({ id: 7, title: "Dori berish qoidalari", category: "dispensing", state: "late", due_on: "2026-11-03" }),
        rule(),
        rule({ id: 9, title: "Kassa intizomi", category: "conduct", state: "signed", signed_at: "2026-11-02T14:20:00+05:00", signed_number: 2 }),
        rule({ id: 11, title: "Ichki tartib", category: "other", state: "to_read", due_on: null }),
      ],
    });
    renderApp(<PoliciesPage />, { me });
    expect(await screen.findByText("Dori berish qoidalari")).toBeTruthy();
    const text = document.body.textContent ?? "";
    expect(text.indexOf("To sign")).toBeLessThan(text.indexOf("Dori berish qoidalari"));
    expect(text.indexOf("Dori berish qoidalari")).toBeLessThan(text.indexOf("Saqlash va harorat rejimi"));
    expect(text.indexOf("Saqlash va harorat rejimi")).toBeLessThan(text.indexOf("Kassa intizomi"));
    expect(text.indexOf("Kassa intizomi")).toBeLessThan(text.indexOf("Ichki tartib"));
    expect(screen.getByText("The deadline was 3 November 2026")).toBeTruthy();
    expect(screen.getByText("Sign by 8 November 2026")).toBeTruthy();
    expect(screen.getByText("Signed 2 November 2026")).toBeTruthy();
    fireEvent.click(screen.getByText("Saqlash va harorat rejimi"));
    expect(navigationState().stack.at(-1)).toEqual({ feature: "hr", page: "policy", params: { id: 4 } });
  });

  it("says kindly when nothing applies to the person yet", async () => {
    routeApi(client.api, { "/hr/policies/": [] });
    renderApp(<PoliciesPage />, { me });
    expect(await screen.findByText("No rules for you yet")).toBeTruthy();
  });
});

describe("a rule", () => {
  it("is read, then signed after asking: once, with the date it was signed", async () => {
    const confirmed = vi.spyOn(window, "confirm").mockReturnValue(true);
    let signed = 0;
    const done = () => detail({ state: "signed", signed_at: "2026-11-05T10:30:00+05:00", signed_number: 2 });
    routeApi(client.api, {
      "/hr/policies/4/": () => (signed ? done() : detail()),
      "POST /hr/policies/versions/31/acknowledge/": () => ((signed += 1), done()),
    });
    renderApp(<PolicyPage params={{ id: 4 }} />, { me });
    expect(await screen.findByText("Read to the end and sign")).toBeTruthy();
    expect(screen.getByText("Muzlatgich: +2 dan +8 gacha.")).toBeTruthy();
    expect(screen.getByText("Jurnal vaqtlari aniqlashtirildi")).toBeTruthy();
    expect(document.querySelector("article script")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "I have read it and agree" }));
    expect(await screen.findByText("You signed it on 5 November 2026")).toBeTruthy();
    expect(confirmed).toHaveBeenCalledWith("“Saqlash va harorat rejimi”: you have read it and agree to follow it?");
    expect(signed).toBe(1);
    expect(screen.queryByRole("button", { name: "I have read it and agree" })).toBeNull();
  });

  it("asks nothing when the person says no", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(false);
    let signed = 0;
    routeApi(client.api, { "/hr/policies/4/": detail(), "POST /hr/policies/versions/31/acknowledge/": () => ((signed += 1), detail()) });
    renderApp(<PolicyPage params={{ id: 4 }} />, { me });
    fireEvent.click(await screen.findByRole("button", { name: "I have read it and agree" }));
    await waitFor(() => expect(window.confirm).toHaveBeenCalled());
    expect(signed).toBe(0);
  });

  it("says when it was signed, that a small edit keeps the signature, and opens its document", async () => {
    routeApi(client.api, {
      "/hr/policies/4/": detail({ state: "signed", signed_at: "2026-10-20T11:00:00+05:00", signed_number: 1, asks_again: false, has_file: true, file_type: "pdf" }),
    });
    renderApp(<PolicyPage params={{ id: 4 }} />, { me });
    expect(await screen.findByText("You signed it on 20 October 2026")).toBeTruthy();
    expect(screen.getByText("You signed version 1; this one only fixes small things.")).toBeTruthy();
    expect(screen.getByText("Open the document")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "I have read it and agree" })).toBeNull();
  });

  it("is only to read when it asks no signature", async () => {
    routeApi(client.api, { "/hr/policies/4/": detail({ state: "to_read", due_on: null }) });
    renderApp(<PolicyPage params={{ id: 4 }} />, { me });
    expect(await screen.findByText("Only to read: no signature needed")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "I have read it and agree" })).toBeNull();
  });
});

describe("Home, Me and links", () => {
  it("Home asks to sign one rule (opening it), or several (opening the list)", async () => {
    routeApi(client.api, { "/hr/policies/": [rule()] });
    renderApp(<PoliciesCard member={member} summary={undefined} />, { me });
    fireEvent.click(await screen.findByText("Rules to sign: Saqlash va harorat rejimi"));
    expect(navigationState().stack.at(-1)).toEqual({ feature: "hr", page: "policy", params: { id: 4 } });

    cleanup();
    routeApi(client.api, { "/hr/policies/": [rule(), rule({ id: 7, state: "late", due_on: "2026-11-03" })] });
    renderApp(<PoliciesCard member={member} summary={undefined} />, { me });
    expect(await screen.findByText("2 rules to read and sign")).toBeTruthy();
    expect(screen.getByText("The deadline has passed: read and sign now")).toBeTruthy();
    fireEvent.click(screen.getByText("2 rules to read and sign"));
    expect(navigationState().stack.at(-1)).toEqual({ feature: "hr", page: "policies" });
  });

  it("Home shows nothing once everything is signed, and Me's bubble counts what is left", async () => {
    routeApi(client.api, { "/hr/policies/": [rule({ state: "signed", signed_at: "2026-11-02T10:00:00+05:00", signed_number: 2 })] });
    const { container } = renderApp(<PoliciesCard member={member} summary={undefined} />, { me });
    await waitFor(() => expect(client.api).toHaveBeenCalled());
    expect(container.querySelector("[class*='banner']")).toBeNull();

    cleanup();
    routeApi(client.api, { "/hr/policies/": [rule(), rule({ id: 7, state: "late" }), rule({ id: 9, state: "to_read" })] });
    const item = hr.meItems!.find((entry) => entry.id === "policies")!;
    function Row() {
      const status = item.useStatus!({ member, summary: undefined });
      return <div data-testid="status">{String(status.badge)}</div>;
    }
    renderApp(<Row />, { me });
    await waitFor(() => expect(screen.getByTestId("status").textContent).toBe("2"));
  });

  it("My documents has a Rules row: what to sign, or that everything is signed", async () => {
    const profile = {
      first_name: "Alisher",
      last_name: "Valiyev",
      middle_name: "",
      position: "Farmatsevt",
      department: null,
      birth_date: null,
      show_birthday: true,
      hire_date: "2025-10-18",
      employment_type: "full_time",
      personal_phone: "",
      email: "",
      address: "",
      city: "",
      pinfl: "",
      passport: "",
      payout_method: "cash",
      payout_card: "",
      emergency_contacts: [],
    };
    routeApi(client.api, { "/hr/profile/": profile, "/hr/documents/": [], "/hr/policies/": [rule(), rule({ id: 9, state: "signed" })] });
    renderApp(<HrPage />, { me });
    expect(await screen.findByText("Rules")).toBeTruthy();
    expect(screen.getByText("Saqlash va harorat rejimi")).toBeTruthy();
    expect(screen.getByText("Sign")).toBeTruthy();
    fireEvent.click(screen.getByText("Rules"));
    expect(navigationState().stack.at(-1)).toEqual({ feature: "hr", page: "policies" });

    cleanup();
    routeApi(client.api, { "/hr/profile/": profile, "/hr/documents/": [], "/hr/policies/": [rule({ state: "signed" })] });
    renderApp(<HrPage />, { me });
    expect(await screen.findByText("All signed")).toBeTruthy();
  });

  it("opens a rule and the list from the bot's links, over Me", () => {
    expect(resolveScreen({ name: "hr.policy", arg: "12" }, features)).toEqual({ tab: "profile", stack: [{ feature: "hr", page: "policy", params: { id: 12 } }] });
    expect(resolveScreen({ name: "hr.policies", arg: null }, features)).toEqual({ tab: "profile", stack: [{ feature: "hr", page: "policies", params: {} }] });
  });
});
