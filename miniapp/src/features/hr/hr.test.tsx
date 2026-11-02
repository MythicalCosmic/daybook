/**
 * "My documents": the details form (only what changed goes, and what is wrong is said), emergency
 * contacts, which document needs renewing, the upload's form, the contract's "I've read it",
 * Home's cards, Me's bubble and the bot's links.
 */
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../../api/client";
import { resolveScreen } from "../../state/deeplink";
import { membership, navigationState, person, renderApp, routeApi } from "../../test/harness";
import { features, featureVisible, findFeature } from "../registry";
import type { Contract, HrDocument, Profile } from "./api";
import ContractPage from "./ContractPage";
import DocumentsPage from "./DocumentsPage";
import HrPage from "./HrPage";
import { cardTyping, contactDraft, needingAttention, profileChanges, profileForm, uploadDraft } from "./lib";
import { ContactSheet, ProfileSheet, UploadSheet } from "./sheets";
import { ContractCard, DocumentCard } from "./slots";

const client = vi.hoisted(() => ({ api: vi.fn(), apiForm: vi.fn() }));
vi.mock("../../api/client", async (importOriginal) => {
  const real = await importOriginal<typeof import("../../api/client")>();
  return { ...real, api: client.api, apiForm: client.apiForm };
});
// Making a photo smaller needs a canvas the test browser doesn't have.
vi.mock("../../lib/image", () => ({ downscale: (file: File) => Promise.resolve(file) }));

const hr = findFeature(features, "hr")!;
const company = { id: 1, name: "Demo Dorixona", timezone: "Asia/Tashkent", features: ["hr", "payroll"], base_currency: "UZS" };
const me = person([membership({ company } as never)]);
const member = { ...me.memberships[0], timeZone: "Asia/Tashkent", companyId: 1 };

function profile(extra: Partial<Profile> = {}): Profile {
  return {
    first_name: "Alisher",
    last_name: "Valiyev",
    middle_name: "Karimovich",
    position: "Farmatsevt",
    department: "Chilonzor dorixonasi",
    birth_date: "1997-12-09",
    show_birthday: true,
    hire_date: "2025-10-18",
    employment_type: "full_time",
    personal_phone: "",
    email: "",
    address: "Toshkent, Mirzo Ulug‘bek tumani",
    city: "Toshkent",
    pinfl: "••••••••••4242",
    passport: "AD•••••42",
    payout_method: "card",
    payout_card: "••••••••••••4242",
    emergency_contacts: [{ id: 1, name: "Valiyeva Muhabbat", relation: "Ona", phone: "+998 90 111 22 33" }],
    ...extra,
  };
}

function document(extra: Partial<HrDocument> = {}): HrDocument {
  return {
    id: 12,
    kind: "medical_book",
    title: "",
    number: "TD-20185",
    issued_on: "2025-11-14",
    expires_on: "2026-11-14",
    level: "" as HrDocument["level"],
    file: null,
    verified: true,
    state: "expiring",
    days_left: 12,
    created_at: "2026-11-02T10:00:00+05:00",
    ...extra,
  };
}

function contract(extra: Partial<Contract> = {}): Contract {
  return {
    id: 5,
    number: "2025-003",
    kind: "indefinite",
    status: "active",
    position: "Farmatsevt",
    starts_on: "2025-10-18",
    ends_on: null,
    probation_until: "2026-01-16",
    probation_passed_at: "2026-01-16T10:00:00+05:00",
    weekly_hours: "40.0",
    file: "/api/v1/files/contract/",
    acknowledged_at: null,
    needs_acknowledgement: true,
    terminated_on: null,
    ...extra,
  };
}

const serve = (overrides: Record<string, unknown>) =>
  routeApi(client.api, { "/hr/profile/": profile(), "/hr/documents/": [document()], "/hr/contract/": contract(), ...overrides });

afterEach(() => {
  cleanup();
  client.api.mockReset();
  client.apiForm.mockReset();
  vi.restoreAllMocks();
});

describe("my details", () => {
  const base = profile();

  it("send only what changed, the card's digits only when a new one is typed", () => {
    const form = { ...profileForm(base), phone: " +998 90 123 45 67 ", showBirthday: false, card: "8600 1234 5678 9012" };
    expect(profileChanges(form, base)).toEqual({
      changes: { personal_phone: "+998 90 123 45 67", show_birthday: false, payout_card: "8600123456789012" },
      problems: [],
    });
    expect(profileChanges(profileForm(base), base)).toEqual({ changes: {}, problems: [] });
  });

  it("say which fields are wrong: a phone, an email, a card that isn't 16 to 19 digits", () => {
    const form = { ...profileForm(base), phone: "12", email: "alisher@", card: "8600 1234" };
    expect(profileChanges(form, base).problems).toEqual(["phone", "email", "card"]);
  });

  it("group a card's digits by four as it is typed", () => {
    expect(cardTyping("8600123456789012")).toBe("8600 1234 5678 9012");
    expect(cardTyping("8600-12a")).toBe("8600 12");
  });

  it("save from the sheet, and keep a wrong email from going", async () => {
    const bodies: unknown[] = [];
    serve({ "PATCH /hr/profile/": (body: unknown) => (bodies.push(body), profile({ email: "a@b.uz" })) });
    const closed = vi.fn();
    renderApp(<ProfileSheet params={{}} close={closed} />, { me });
    fireEvent.change(await screen.findByLabelText("Email"), { target: { value: "alisher@" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Check the email address")).toBeTruthy();
    expect(bodies).toEqual([]);
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "a@b.uz" } });
    fireEvent.click(screen.getByRole("radio", { name: "Hidden" }));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(closed).toHaveBeenCalled());
    expect(bodies).toEqual([{ email: "a@b.uz", show_birthday: false }]);
  });

  it("show on the page with the masked card and IDs, and HR's part said", async () => {
    serve({});
    renderApp(<HrPage />, { me });
    expect(await screen.findByText("Alisher Valiyev")).toBeTruthy();
    expect(screen.getByText("Farmatsevt · Chilonzor dorixonasi")).toBeTruthy();
    expect(screen.getAllByText("•••• 4242")).toHaveLength(2);
    expect(screen.getByText("AD•••••42")).toBeTruthy();
    expect(screen.getByText("HR keeps your name, position and ID numbers.")).toBeTruthy();
    // The contract waits to be read, a document needs renewing: the rows say so.
    expect(screen.getByText("Read it")).toBeTruthy();
    expect(screen.getByText("Medical book: 12 days left")).toBeTruthy();
  });
});

describe("emergency contacts", () => {
  it("need a name and a phone; the relation may stay empty", () => {
    expect(contactDraft({ name: "  Valiyeva   Muhabbat ", relation: "", phone: "+998 90 111 22 33" })).toEqual({
      draft: { name: "Valiyeva Muhabbat", relation: "", phone: "+998 90 111 22 33" },
    });
    expect(contactDraft({ name: "", relation: "Ona", phone: "abc" })).toEqual({ problems: ["name", "phone"] });
  });

  it("are added from the sheet, and removed after asking", async () => {
    const posted: unknown[] = [];
    let removed = 0;
    serve({
      "POST /hr/profile/emergency-contacts/": (body: unknown) => (posted.push(body), { id: 2, ...(body as object) }),
      "DELETE /hr/profile/emergency-contacts/1/": () => ((removed += 1), undefined),
    });
    const closed = vi.fn();
    renderApp(<ContactSheet params={{}} close={closed} />, { me });
    fireEvent.change(await screen.findByLabelText("Name"), { target: { value: "Valiyev Karim" } });
    fireEvent.change(screen.getByLabelText("Phone"), { target: { value: "+998 90 222 33 44" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(closed).toHaveBeenCalled());
    expect(posted).toEqual([{ name: "Valiyev Karim", relation: "", phone: "+998 90 222 33 44" }]);

    cleanup();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const done = vi.fn();
    renderApp(<ContactSheet params={{ id: 1 }} close={done} />, { me });
    fireEvent.click(await screen.findByRole("button", { name: "Remove" }));
    await waitFor(() => expect(done).toHaveBeenCalled());
    expect(removed).toBe(1);
  });

  it("stop at three: no Add with three on file", async () => {
    const three = [1, 2, 3].map((id) => ({ id, name: `Contact ${id}`, relation: "", phone: "+998 90 111 22 3" + id }));
    serve({ "/hr/profile/": profile({ emergency_contacts: three }) });
    renderApp(<HrPage />, { me });
    expect(await screen.findByText("Contact 3")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Add a contact" })).toBeNull();
  });
});

describe("documents", () => {
  it("that need the person: expired first, then the soonest to run out", () => {
    const rows = [
      document({ id: 1, state: "valid", days_left: 400 }),
      document({ id: 2, state: "expiring", days_left: 20 }),
      document({ id: 3, state: "expired", days_left: -9 }),
      document({ id: 4, state: "expiring", days_left: 5 }),
      document({ id: 5, state: "no_expiry", days_left: null }),
    ];
    expect(needingAttention(rows).map((row) => row.id)).toEqual([3, 4, 2]);
  });

  it("are uploaded with the kind, the file and what was typed, nothing empty", () => {
    const file = new File(["x"], "book.jpg", { type: "image/jpeg" });
    expect(uploadDraft({ kind: "medical_book", file: null, number: "", expires: null })).toBeNull();
    expect(uploadDraft({ kind: "medical_book", file, number: " TD-1 ", expires: "2027-11-02" })).toEqual({ kind: "medical_book", file, number: "TD-1", expires_on: "2027-11-02" });
    expect(uploadDraft({ kind: "diploma", file, number: "", expires: null })).toEqual({ kind: "diploma", file });
  });

  it("show where each stands, the expired one asked about first", async () => {
    serve({ "/hr/documents/": [document({ id: 1, kind: "pharmacist_certificate", state: "valid", days_left: 845, expires_on: "2029-02-24" }), document({ id: 2, state: "expired", days_left: -9, expires_on: "2026-10-24", verified: false })] });
    renderApp(<DocumentsPage />, { me });
    expect(await screen.findByText("Medical book: expired")).toBeTruthy();
    expect(screen.getByText("Valid")).toBeTruthy();
    expect(screen.getByText("HR is checking it")).toBeTruthy();
    expect(screen.getByText("Until 24 February 2029")).toBeTruthy();
  });

  it("upload from the sheet as a form, with the end date a year ahead for a medical book", async () => {
    serve({});
    client.apiForm.mockResolvedValue(document({ id: 30 }));
    const closed = vi.fn();
    const { container } = renderApp(<UploadSheet params={{ kind: "medical_book" }} close={closed} />, { me });
    const upload = (await screen.findByRole("button", { name: "Upload" })) as HTMLButtonElement;
    expect(upload.disabled).toBe(true);
    const file = new File(["%PDF"], "book.pdf", { type: "application/pdf" });
    const input = container.querySelector<HTMLInputElement>('input[type="file"]:not([capture])')!;
    fireEvent.change(input, { target: { files: [file] } });
    expect(await screen.findByText("PDF file")).toBeTruthy();
    fireEvent.change(screen.getByLabelText(/Number/), { target: { value: "TD-30" } });
    fireEvent.click(upload);
    await waitFor(() => expect(closed).toHaveBeenCalled());
    const [path, fields] = client.apiForm.mock.calls[0];
    expect(path).toBe("/companies/1/hr/documents/");
    const year = new Date().getFullYear() + 1;
    expect(fields).toEqual({ kind: "medical_book", number: "TD-30", expires_on: expect.stringMatching(new RegExp(`^${year}-`)), file });
  });
});

describe("the contract", () => {
  it("is read and confirmed with I've read it", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    let acknowledged = 0;
    serve({ "POST /hr/contract/5/acknowledge/": () => ((acknowledged += 1), contract({ acknowledged_at: "2026-11-02T19:00:00+05:00", needs_acknowledgement: false })) });
    renderApp(<ContractPage />, { me });
    expect(await screen.findByText("Please read your contract")).toBeTruthy();
    expect(screen.getByText("Open the contract")).toBeTruthy();
    expect(screen.getByText("40 h a week")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "I’ve read it" }));
    expect(await screen.findByText("You read it: 2 November 2026")).toBeTruthy();
    expect(acknowledged).toBe(1);
    expect(screen.queryByRole("button", { name: "I’ve read it" })).toBeNull();
  });

  it("says kindly that there is none yet (the server's 404)", async () => {
    serve({ "/hr/contract/": new ApiError(404, { detail: "You have no contract on file yet." }) });
    renderApp(<ContractPage />, { me });
    expect(await screen.findByText("No contract yet")).toBeTruthy();
  });

  it("says when its file isn't uploaded yet", async () => {
    serve({ "/hr/contract/": contract({ file: null, needs_acknowledgement: false, acknowledged_at: "2026-06-15T12:00:00+05:00" }) });
    renderApp(<ContractPage />, { me });
    expect(await screen.findByText("The contract’s file isn’t uploaded yet. Ask HR for a copy.")).toBeTruthy();
  });
});

describe("Home, Me and links", () => {
  it("Home asks to read the contract and to renew a document, each opening its page", async () => {
    serve({});
    renderApp(
      <>
        <ContractCard member={member} summary={undefined} />
        <DocumentCard member={member} summary={undefined} />
      </>,
      { me },
    );
    fireEvent.click(await screen.findByText("Please read your contract"));
    expect(navigationState().stack).toEqual([{ feature: "hr", page: "contract" }]);
    fireEvent.click(screen.getByText("Medical book: 12 days left"));
    expect(navigationState().stack.at(-1)).toEqual({ feature: "hr", page: "documents" });
  });

  it("Me's bubble counts the contract to read and the documents to renew", async () => {
    serve({ "/hr/documents/": [document(), document({ id: 2, state: "expired", days_left: -1 }), document({ id: 3, state: "valid", days_left: 300 })] });
    function Row() {
      const status = hr.meItems![0].useStatus!({ member, summary: undefined });
      return <div data-testid="status">{String(status.badge)}</div>;
    }
    renderApp(<Row />, { me });
    await waitFor(() => expect(screen.getByTestId("status").textContent).toBe("3"));
  });

  it("is on with HR, for approved and suspended people", () => {
    const visible = (fields: object) => featureVisible(hr, { member: { ...member, ...fields } as never, summary: undefined });
    expect(visible({})).toBe(true);
    expect(visible({ status: "suspended" })).toBe(true);
    expect(visible({ company: { ...company, features: ["payroll"] } })).toBe(false);
  });

  it("opens the contract and the documents from the bot's links, over Me", () => {
    expect(resolveScreen({ name: "hr.contract", arg: null }, features)).toEqual({ tab: "profile", stack: [{ feature: "hr", page: "contract", params: {} }] });
    expect(resolveScreen({ name: "hr.documents", arg: null }, features)).toEqual({ tab: "profile", stack: [{ feature: "hr", page: "documents", params: {} }] });
    expect(resolveScreen({ name: "hr", arg: null }, features)).toEqual({ tab: "profile", stack: [{ feature: "hr", page: "home", params: {} }] });
  });
});
