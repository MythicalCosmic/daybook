/**
 * Expenses: who sees them, the new expense form (its checks, company cash I hold, receipts, the
 * body it sends and what became of it), my list with each claim's status and Cancel, one claim's
 * sheet, the Me row and the bot's deep links.
 */
import { act, cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../../api/client";
import { addDays, dayKey } from "../../lib/time";
import { resolveScreen } from "../../state/deeplink";
import { membership, navigationState, person, renderApp, routeApi } from "../../test/harness";
import { features, featureVisible, findFeature, meItemsByGroup, plusActions } from "../registry";
import type { Claim, ClaimWallet, ExpenseCategory } from "./api";
import { addReceipts, canCancel, claimDraft, groupCategories, MAX_RECEIPTS, needsReceipt, serverProblems, underThreshold, usualCategories, type ClaimForm } from "./lib";
import ListPage from "./ListPage";
import { ClaimSheet, NewClaimSheet } from "./sheets";

const client = vi.hoisted(() => ({ api: vi.fn(), apiForm: vi.fn() }));
vi.mock("../../api/client", async (importOriginal) => {
  const real = await importOriginal<typeof import("../../api/client")>();
  return { ...real, api: client.api, apiForm: client.apiForm };
});
// Making a photo smaller needs a canvas the test browser doesn't have.
vi.mock("../../lib/image", () => ({ downscale: (file: File) => Promise.resolve(file) }));

const expenses = findFeature(features, "expenses")!;
const company = { id: 1, name: "Demo Dorixona", timezone: "Asia/Tashkent", features: ["finance", "payroll"], base_currency: "UZS" };
const jasur = membership({ company, first_name: "Jasur", last_name: "Rahimov", permissions: ["finance.claim", "tasks.view"] } as never);
const me = person([jasur]);
const member = { ...jasur, timeZone: "Asia/Tashkent", companyId: 1 };
const today = dayKey(new Date(), "Asia/Tashkent");
/** Amounts as the screens print them, with the non-breaking space before the currency made plain. */
const plain = (text: string | null | undefined) => (text ?? "").replace(/ /g, " ");

const category = (id: number, name: string, parent_id: number | null = null): ExpenseCategory => ({ id, name, parent_id, icon: "", color: "" });
const CATEGORIES = [category(1, "Medicines and goods"), category(2, "Transport"), category(3, "Fuel", 2), category(4, "Taxi", 2), category(5, "Repairs")];
const ref = (id: number, name: string, parent_id: number | null = null) => ({ id, name, kind: "expense" as const, color: "", parent_id });

function claim(extra: Partial<Claim> = {}): Claim {
  return {
    id: 12,
    member: { id: 7, name: "Jasur Rahimov", photo_url: null },
    amount: "85000.00",
    currency: "UZS",
    category: ref(4, "Taxi", 2),
    spent_on: "2026-11-05",
    description: "Taxi to the distributor",
    paid_from: "own_money",
    status: "submitted",
    status_label: "Submitted",
    branch: { id: 1, name: "Chilonzor" },
    receipts: [],
    created_at: "2026-11-05T14:32:00+05:00",
    decided_by: null,
    decided_at: null,
    reject_reason: "",
    reimburse_via: "payroll",
    transaction_id: null,
    debt_id: null,
    can_decide: false,
    can_pay: false,
    can_cancel: true,
    ...extra,
  };
}

const wallet = (extra: Partial<ClaimWallet> = {}): ClaimWallet => ({
  currency: "UZS",
  held: [],
  held_total: "0.00",
  owed_to_me: "0.00",
  approval_threshold: "100000.00",
  receipt_required_over: "500000.00",
  ...extra,
});
const holding = (total: string) => wallet({ held: [{ account_id: 9, name: "Jasur, cash on hand", balance: total, currency: "UZS" }], held_total: total });

/** The endpoints as an ordinary day answers them; a test overrides what it is about. */
const DEFAULTS = (): Record<string, unknown> => ({ "/finance/categories/": CATEGORIES, "/finance/claims/": [], "/finance/wallet/": wallet() });
const serve = (overrides: Record<string, unknown> = {}) => routeApi(client.api, { ...DEFAULTS(), ...overrides });

const photo = (name: string) => new File(["jpeg"], name, { type: "image/jpeg" });
const pdf = (name = "invoice.pdf") => new File(["%PDF"], name, { type: "application/pdf" });

beforeEach(() => {
  // Previews of picked photos need object URLs, which the test browser lacks.
  Object.defineProperty(URL, "createObjectURL", { configurable: true, value: (file: File) => `blob:${file.name}` });
  Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: () => undefined });
});

afterEach(() => {
  cleanup();
  client.api.mockReset();
  client.apiForm.mockReset();
  vi.restoreAllMocks();
  delete (URL as unknown as Record<string, unknown>).createObjectURL;
  delete (URL as unknown as Record<string, unknown>).revokeObjectURL;
});

describe("who sees expenses", () => {
  it("is on with the company's finance, for approved people who may claim", () => {
    const visible = (fields: object) => featureVisible(expenses, { member: { ...member, ...fields } as never, summary: undefined });
    expect(visible({})).toBe(true);
    expect(visible({ permissions: ["tasks.view"] })).toBe(false);
    expect(visible({ company: { ...company, features: ["payroll"] } })).toBe(false);
    expect(visible({ company: { ...company, features: undefined } })).toBe(false);
    expect(visible({ status: "pending" })).toBe(false);
    expect(visible({ status: "suspended" })).toBe(false);
  });

  it("puts Expense in the (+) sheet and My expenses in Me's money group, only for them", () => {
    const ours = <T extends { feature: { id: string } }>(list: T[]) => list.filter((placed) => placed.feature.id === "expenses");
    const context = { member: member as never, summary: undefined };
    expect(ours(plusActions(features, context)).map(({ item }) => [item.id, item.open])).toEqual([["expense", { sheet: "new" }]]);
    expect(ours(meItemsByGroup(features, context).money).map(({ item }) => [item.id, item.open])).toEqual([["expenses", { page: "list" }]]);
    const without = { member: { ...member, permissions: [] } as never, summary: undefined };
    expect(ours(plusActions(features, without))).toEqual([]);
    expect(ours(meItemsByGroup(features, without).money)).toEqual([]);
  });

  it("answers the bot's links: the list, a new expense, and one claim over the list", () => {
    const list = { feature: "expenses", page: "list", params: {} };
    expect(resolveScreen({ name: "expenses", arg: null }, features)).toEqual({ tab: "profile", stack: [list] });
    expect(resolveScreen({ name: "expense", arg: null }, features)).toEqual({ tab: "home", sheet: { kind: "feature", feature: "expenses", sheet: "new", params: {} } });
    expect(resolveScreen({ name: "claim", arg: "12" }, features)).toEqual({
      tab: "profile",
      stack: [list],
      sheet: { kind: "feature", feature: "expenses", sheet: "claim", params: { id: 12 } },
    });
    expect(resolveScreen({ name: "claim", arg: "abc" }, features)).toEqual({ tab: "profile", stack: [list] });
  });
});

describe("categories", () => {
  it("group children under their parent in the company's order; a deeper level joins its top, an orphan stands alone", () => {
    const groups = groupCategories([...CATEGORIES, category(6, "Diesel", 3), category(7, "Courier bags", 99)]);
    expect(groups.map(({ parent, children }) => [parent.name, children.map((row) => row.name)])).toEqual([
      ["Medicines and goods", []],
      ["Transport", ["Fuel", "Taxi", "Diesel"]],
      ["Repairs", []],
      ["Courier bags", []],
    ]);
  });

  it("put the ones I claim most first, the latest on a tie, leaving out cancelled claims and inactive categories", () => {
    const claims = [
      claim({ id: 6, category: ref(4, "Taxi", 2) }),
      claim({ id: 5, category: ref(5, "Repairs"), status: "approved" }),
      claim({ id: 4, category: ref(4, "Taxi", 2), status: "cancelled" }),
      claim({ id: 3, category: ref(3, "Fuel", 2), status: "paid" }),
      claim({ id: 2, category: ref(5, "Repairs"), status: "rejected" }),
      claim({ id: 1, category: ref(99, "Old category") }),
    ];
    expect(usualCategories(claims, CATEGORIES).map((row) => row.name)).toEqual(["Repairs", "Taxi", "Fuel"]);
    expect(usualCategories(claims, CATEGORIES, 2).map((row) => row.name)).toEqual(["Repairs", "Taxi"]);
    expect(usualCategories([], CATEGORIES)).toEqual([]);
  });
});

describe("the form's checks", () => {
  const form = (extra: Partial<ClaimForm> = {}): ClaimForm => ({
    typing: "450000",
    category: 4,
    spentOn: today,
    description: "  Taxi to the distributor ",
    paidFrom: "own_money",
    receipts: [],
    ...extra,
  });
  const rules = { today, held: null, receiptRequiredOver: "500000.00" };

  it("name everything still missing, and send nothing meanwhile", () => {
    expect(claimDraft(form({ typing: "", category: null }), rules)).toEqual({ payload: null, problems: ["amount", "category"] });
    expect(claimDraft(form({ typing: "0" }), rules).problems).toEqual(["amount"]);
    expect(claimDraft(form({ description: "x".repeat(301) }), rules).problems).toEqual(["description"]);
  });

  it("send a claim without words, as the server takes it (the receipt or the category may say enough)", () => {
    expect(claimDraft(form({ description: "   " }), rules).payload?.description).toBe("");
  });

  it("send the amount, category, day, trimmed words and receipts in the server's form", () => {
    const receipt = pdf();
    expect(claimDraft(form({ receipts: [receipt] }), rules)).toEqual({
      payload: { amount: "450000.00", category: 4, spent_on: today, description: "Taxi to the distributor", paid_from: "own_money", receipts: [receipt] },
      problems: [],
    });
  });

  it("refuse a day after today", () => {
    expect(claimDraft(form({ spentOn: addDays(today, 1) }), rules).problems).toEqual(["date"]);
    expect(claimDraft(form({ spentOn: addDays(today, -30) }), rules).problems).toEqual([]);
    expect(claimDraft(form({ spentOn: "" }), rules).problems).toEqual(["date"]);
  });

  it("allow company cash only while I hold some, and never more than I hold", () => {
    expect(claimDraft(form({ paidFrom: "held_cash" }), rules).problems).toEqual(["heldCash"]);
    expect(claimDraft(form({ paidFrom: "held_cash", typing: "250000" }), { ...rules, held: "200000.00" }).problems).toEqual(["heldOver"]);
    expect(claimDraft(form({ paidFrom: "held_cash", typing: "200000" }), { ...rules, held: "200000.00" }).payload?.paid_from).toBe("held_cash");
  });

  it("need a receipt only over the company's limit", () => {
    expect(needsReceipt("500000", "500000.00")).toBe(false);
    expect(needsReceipt("500001", "500000.00")).toBe(true);
    expect(needsReceipt("9000000", null)).toBe(false);
    expect(claimDraft(form({ typing: "600000" }), rules).problems).toEqual(["receipt"]);
    expect(claimDraft(form({ typing: "600000", receipts: [photo("chek.jpg")] }), rules).problems).toEqual([]);
  });

  it("know when an amount is recorded without approval", () => {
    expect(underThreshold("99999", "100000.00")).toBe(true);
    expect(underThreshold("100000", "100000.00")).toBe(false);
    expect(underThreshold("5000", null)).toBe(false);
    expect(underThreshold("", "100000.00")).toBe(false);
  });

  it("take photos and PDF files only, five at most", () => {
    const names = (files: File[]) => files.map((file) => file.name);
    const word = new File(["x"], "notes.docx", { type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document" });
    const typeOnly = addReceipts([], [photo("a.jpg"), pdf(), word]);
    expect([names(typeOnly.files), typeOnly.dropped]).toEqual([["a.jpg", "invoice.pdf"], "type"]);
    const six = addReceipts([], ["1", "2", "3", "4", "5", "6"].map((n) => photo(`${n}.jpg`)));
    expect([six.files.length, six.dropped]).toEqual([MAX_RECEIPTS, "limit"]);
    const more = addReceipts(six.files.slice(0, 4), [photo("x.jpg"), photo("y.jpg")]);
    expect([names(more.files).at(-1), more.files.length, more.dropped]).toEqual(["x.jpg", 5, "limit"]);
    expect(addReceipts([], [new File(["%PDF"], "scan.PDF", { type: "" })]).dropped).toBeNull();
  });

  it("read the server's refusals field by field, with one line for the banner", () => {
    expect(serverProblems(new ApiError(400, { amount: ["Ensure this value is greater than 0."], receipts: { 1: ["Upload a valid image."] } }))).toEqual({
      fields: { amount: "Ensure this value is greater than 0.", receipts: "Upload a valid image." },
      message: "Ensure this value is greater than 0.",
    });
    expect(serverProblems(new ApiError(400, { detail: "November is closed for changes." }))).toEqual({ fields: {}, message: "November is closed for changes." });
    expect(serverProblems(new ApiError(403, { detail: "You do not have permission." }))).toBeNull();
    expect(serverProblems(new TypeError("Failed to fetch"))).toBeNull();
  });

  it("let a claim be cancelled only while it waits", () => {
    expect(canCancel(claim())).toBe(true);
    expect(canCancel(claim({ can_cancel: false }))).toBe(false);
    expect(canCancel(claim({ status: "approved", can_cancel: true }))).toBe(false);
  });
});

/** Fill the form's required fields the way a person does. */
function fill({ amount = "85000", categoryId = "4", description = " Taxi to the distributor " } = {}) {
  fireEvent.change(screen.getByLabelText("Amount"), { target: { value: amount } });
  fireEvent.change(screen.getByLabelText("Category"), { target: { value: categoryId } });
  fireEvent.change(screen.getByLabelText(/^What was it for\?/), { target: { value: description } });
}

const fileInput = (container: HTMLElement) => container.querySelector<HTMLInputElement>('input[type="file"][multiple]')!;

describe("a new expense", () => {
  it("checks what is missing when sent, then sends the expense with its receipt and says it went for approval", async () => {
    serve();
    client.apiForm.mockResolvedValue(claim());
    const closed = vi.fn();
    const { container } = renderApp(<NewClaimSheet params={{}} close={closed} />, { me });
    const send = await screen.findByRole("button", { name: "Send the expense" });
    expect(screen.queryAllByRole("alert")).toEqual([]);
    fireEvent.click(send);
    expect(screen.getAllByRole("alert").map((alert) => alert.textContent)).toEqual(["Type the amount", "Choose a category"]);
    expect(client.apiForm).not.toHaveBeenCalled();

    fill();
    const receipt = pdf();
    fireEvent.change(fileInput(container), { target: { files: [receipt] } });
    expect(await screen.findByText("PDF")).toBeTruthy();
    expect(screen.queryAllByRole("alert")).toEqual([]);
    fireEvent.click(send);
    expect(await screen.findByText("Sent for approval")).toBeTruthy();
    expect(client.apiForm).toHaveBeenCalledOnce();
    expect(client.apiForm.mock.calls[0]).toEqual([
      "/companies/1/finance/claims/",
      { amount: "85000.00", category: 4, spent_on: today, description: "Taxi to the distributor", paid_from: "own_money", receipts: [receipt] },
    ]);
    expect(screen.getByText("The decision shows in My expenses.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(closed).toHaveBeenCalled();
  });

  it("offers company cash I hold only when I hold some, with how much, and never more than that", async () => {
    serve();
    renderApp(<NewClaimSheet params={{}} close={() => undefined} />, { me });
    await screen.findByLabelText("Amount");
    await waitFor(() => expect(client.api.mock.calls.some(([path]) => String(path).endsWith("/finance/wallet/"))).toBe(true));
    await act(async () => undefined);
    expect(screen.queryByRole("radio", { name: "Company cash I hold" })).toBeNull();
    expect(screen.queryByText("Paid from")).toBeNull();
    cleanup();

    serve({ "/finance/wallet/": holding("1200000.00") });
    renderApp(<NewClaimSheet params={{}} close={() => undefined} />, { me });
    fireEvent.click(await screen.findByRole("radio", { name: "Company cash I hold" }));
    expect(plain(screen.getByText(/^You hold/).textContent)).toBe("You hold 1,200,000 UZS");
    fireEvent.change(screen.getByLabelText("Amount"), { target: { value: "1500000" } });
    expect(plain(screen.getByRole("alert").textContent)).toBe("More than you hold: 1,200,000 UZS");
    fireEvent.click(screen.getByRole("radio", { name: "My own money" }));
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("speaks Uzbek with so‘m: Qo‘limdagi kompaniya puli", async () => {
    serve({ "/finance/wallet/": holding("1200000.00") });
    renderApp(<NewClaimSheet params={{}} close={() => undefined} />, { me, lang: "uz" });
    expect(await screen.findByText("Yangi xarajat")).toBeTruthy();
    fireEvent.click(await screen.findByRole("radio", { name: "Qo‘limdagi kompaniya puli" }));
    expect(plain(screen.getByText(/^Qo‘lingizda/).textContent)).toBe("Qo‘lingizda: 1 200 000 so‘m");
  });

  it("says Recorded when the claim was under the approval threshold, and that the cash I hold paid it", async () => {
    serve({ "/finance/wallet/": holding("1200000.00") });
    client.apiForm.mockResolvedValue(claim({ status: "approved", paid_from: "held_cash", reimburse_via: null }));
    renderApp(<NewClaimSheet params={{}} close={() => undefined} />, { me });
    fireEvent.click(await screen.findByRole("radio", { name: "Company cash I hold" }));
    fill();
    expect(plain(screen.getByText(/^Recorded without approval/).textContent)).toBe("Recorded without approval (limit: 100,000 UZS)");
    fireEvent.click(screen.getByRole("button", { name: "Send the expense" }));
    expect(await screen.findByText("Recorded")).toBeTruthy();
    expect(screen.getByText("Taken from the company cash you hold.")).toBeTruthy();
    expect(client.apiForm.mock.calls[0][1]).toMatchObject({ paid_from: "held_cash", receipts: [] });
    fireEvent.click(screen.getByRole("button", { name: "My expenses" }));
    expect(navigationState().stack).toEqual([{ feature: "expenses", page: "list" }]);
  });

  it("tells me when my own money comes back with my pay", async () => {
    serve();
    client.apiForm.mockResolvedValue(claim({ status: "approved", reimburse_via: "payroll" }));
    renderApp(<NewClaimSheet params={{}} close={() => undefined} />, { me });
    await screen.findByLabelText("Amount");
    fill();
    fireEvent.click(screen.getByRole("button", { name: "Send the expense" }));
    expect(await screen.findByText("Recorded")).toBeTruthy();
    expect(screen.getByText("Comes back with your pay")).toBeTruthy();
  });

  it("asks for a receipt over the company's limit, and sends once there is one", async () => {
    serve();
    client.apiForm.mockResolvedValue(claim({ amount: "600000.00" }));
    const { container } = renderApp(<NewClaimSheet params={{}} close={() => undefined} />, { me });
    await screen.findByLabelText("Amount");
    const receiptLabel = () => [...container.querySelectorAll("label")].find((label) => label.textContent?.startsWith("Receipt"))?.textContent;
    expect(receiptLabel()).toBe("Receipt (optional)");
    expect(screen.getByText("Photos or PDF, up to 5 files")).toBeTruthy();
    fill({ amount: "600000" });
    expect(receiptLabel()).toBe("Receipt");
    expect(plain(screen.getByText(/^A receipt is needed/).textContent)).toBe("A receipt is needed: the amount is over 500,000 UZS");
    fireEvent.click(screen.getByRole("button", { name: "Send the expense" }));
    expect(plain(screen.getByRole("alert").textContent)).toBe("A receipt is needed: the amount is over 500,000 UZS");
    expect(client.apiForm).not.toHaveBeenCalled();
    fireEvent.change(fileInput(container), { target: { files: [photo("chek.jpg")] } });
    expect(await screen.findByAltText("Receipt 1")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Send the expense" }));
    await waitFor(() => expect(client.apiForm).toHaveBeenCalledOnce());
    expect(client.apiForm.mock.calls[0][1]).toMatchObject({ amount: "600000.00", receipts: [expect.objectContaining({ name: "chek.jpg" })] });
  });

  it("shows the server's reason when it refuses, under the field and by the button, and keeps what was typed", async () => {
    serve();
    client.apiForm.mockRejectedValueOnce(new ApiError(400, { spent_on: ["November is closed for changes."] }));
    renderApp(<NewClaimSheet params={{}} close={() => undefined} />, { me });
    await screen.findByLabelText("Amount");
    fill();
    fireEvent.click(screen.getByRole("button", { name: "Send the expense" }));
    await waitFor(() => expect(screen.getAllByText("November is closed for changes.")).toHaveLength(2));
    expect((screen.getByLabelText("Amount") as HTMLInputElement).value).toBe("85,000");
    expect(screen.queryByText("Sent for approval")).toBeNull();
    // Changing the field clears the server's words about it.
    fireEvent.change(screen.getByLabelText(/^What was it for\?/), { target: { value: "Taxi to the distributor, urgent order" } });
    expect(screen.queryByText("November is closed for changes.")).toBeNull();

    client.apiForm.mockRejectedValueOnce(new ApiError(400, { detail: "Expense claims are paused for this company." }));
    fireEvent.click(screen.getByRole("button", { name: "Send the expense" }));
    expect(await screen.findByText("Expense claims are paused for this company.")).toBeTruthy();
  });

  it("offers the categories I use most as chips over the full list, children under their parent", async () => {
    serve({ "/finance/claims/": [claim({ id: 3, category: ref(5, "Repairs") }), claim({ id: 2, category: ref(5, "Repairs") }), claim({ id: 1 })] });
    renderApp(<NewClaimSheet params={{}} close={() => undefined} />, { me });
    const select = (await screen.findByLabelText("Category")) as HTMLSelectElement;
    const group = select.querySelector("optgroup")!;
    expect(group.label).toBe("Transport");
    expect([...group.querySelectorAll("option")].map((option) => option.textContent)).toEqual(["Transport", "Fuel", "Taxi"]);
    fireEvent.click(await screen.findByRole("button", { name: "Repairs" }));
    expect(select.value).toBe("5");
    expect(screen.getByRole("button", { name: "Taxi" }).getAttribute("aria-pressed")).toBe("false");
    fireEvent.change(select, { target: { value: "4" } });
    expect(screen.getByRole("button", { name: "Taxi" }).getAttribute("aria-pressed")).toBe("true");
  });

  it("takes up to five receipts, says why it left some out, and lets one go", async () => {
    serve();
    const { container } = renderApp(<NewClaimSheet params={{}} close={() => undefined} />, { me });
    await screen.findByLabelText("Amount");
    const files = ["1", "2", "3", "4", "5", "6"].map((n) => photo(`receipt-${n}.jpg`));
    fireEvent.change(fileInput(container), { target: { files } });
    expect(await screen.findByText("Up to 5 files: the rest were left out")).toBeTruthy();
    expect(container.querySelectorAll(".exp-tile")).toHaveLength(5);
    expect(screen.queryByRole("button", { name: "Take a photo" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Remove: receipt-2.jpg" }));
    expect(container.querySelectorAll(".exp-tile")).toHaveLength(4);
    expect(screen.getByRole("button", { name: "Take a photo" })).toBeTruthy();
    fireEvent.change(fileInput(container), { target: { files: [new File(["x"], "notes.txt", { type: "text/plain" })] } });
    expect(await screen.findByText("Only photos and PDF files can be added")).toBeTruthy();
    expect(container.querySelectorAll(".exp-tile")).toHaveLength(4);
  });

  it("says so when there are no categories to claim against", async () => {
    serve({ "/finance/categories/": [] });
    renderApp(<NewClaimSheet params={{}} close={() => undefined} />, { me });
    expect(await screen.findByText("No expense categories yet")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Send the expense" })).toBeNull();
  });
});

describe("my expenses", () => {
  const LIST = [
    claim(),
    claim({ id: 11, amount: "320000.00", category: ref(5, "Repairs"), description: "Door lock", status: "approved", can_cancel: false, decided_by: { id: 3, name: "Dilnoza Karimova", photo_url: null }, decided_at: "2026-11-04T10:00:00+05:00" }),
    claim({ id: 10, amount: "150000.00", category: ref(3, "Fuel", 2), status: "paid", can_cancel: false, receipts: [{ id: 31, url: "https://cdn.example.uz/r/31.jpg?sig=a", thumb_url: null, content_type: "image/jpeg", is_image: true }] }),
    claim({ id: 9, amount: "40000.00", category: ref(1, "Medicines and goods"), status: "rejected", reject_reason: "No receipt", can_cancel: false }),
    claim({ id: 8, amount: "12000.00", status: "cancelled", can_cancel: false }),
  ];

  it("lists my claims with where each stands, and what is owed to me and held", async () => {
    serve({ "/finance/claims/": LIST, "/finance/wallet/": { ...holding("1200000.00"), owed_to_me: "450000.00" } });
    renderApp(<ListPage />, { me });
    expect(await screen.findByText("Waiting for approval")).toBeTruthy();
    for (const status of ["Approved", "Paid back", "Rejected", "Cancelled"]) expect(screen.getByText(status)).toBeTruthy();
    expect(screen.getByText("Reason: No receipt")).toBeTruthy();
    expect(screen.getByText("Comes back with your pay")).toBeTruthy();
    expect(screen.getByText("1 receipt")).toBeTruthy();
    expect(screen.getAllByRole("button", { name: "Cancel" })).toHaveLength(1);
    const summary = (label: string) => plain(screen.getByText(label).closest(".list-item")?.querySelector(".list-item-value")?.textContent);
    await screen.findByText("Owed to me");
    expect(summary("Owed to me")).toBe("450,000 UZS");
    expect(summary("Company cash I hold")).toBe("1,200,000 UZS");
  });

  it("takes a waiting claim back after asking", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    let cancelled = 0;
    let rows = [claim()];
    serve({
      "/finance/claims/": () => rows,
      "POST /finance/claims/12/cancel/": () => {
        cancelled += 1;
        rows = [claim({ status: "cancelled", can_cancel: false })];
        return rows[0];
      },
    });
    renderApp(<ListPage />, { me });
    fireEvent.click(await screen.findByRole("button", { name: "Cancel" }));
    expect(await screen.findByText("Cancelled")).toBeTruthy();
    expect(cancelled).toBe(1);
    expect(screen.queryByRole("button", { name: "Cancel" })).toBeNull();
    expect(screen.getByText("Expense cancelled")).toBeTruthy();
  });

  it("keeps the claim when I don't confirm", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(false);
    serve({ "/finance/claims/": [claim()] });
    renderApp(<ListPage />, { me });
    fireEvent.click(await screen.findByRole("button", { name: "Cancel" }));
    await act(async () => undefined);
    expect(client.api.mock.calls.some(([path]) => String(path).endsWith("/cancel/"))).toBe(false);
  });

  it("invites the first expense when there are none, without empty sums", async () => {
    serve();
    renderApp(<ListPage />, { me });
    expect(await screen.findByText("No expenses yet")).toBeTruthy();
    await waitFor(() => expect(client.api.mock.calls.some(([path]) => String(path).endsWith("/finance/wallet/"))).toBe(true));
    await act(async () => undefined);
    expect(screen.queryByText("Owed to me")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Add an expense" }));
    expect(navigationState().sheet).toEqual({ kind: "feature", feature: "expenses", sheet: "new" });
  });

  it("opens a claim's sheet from its row", async () => {
    serve({ "/finance/claims/": LIST });
    renderApp(<ListPage />, { me });
    fireEvent.click(await screen.findByText("Door lock"));
    expect(navigationState().sheet).toEqual({ kind: "feature", feature: "expenses", sheet: "claim", params: { id: 11 } });
  });

  it("says the list didn't open, with Try again", async () => {
    serve({ "/finance/claims/": new ApiError(500, null) });
    renderApp(<ListPage />, { me });
    expect(await screen.findByText("Try again")).toBeTruthy();
  });
});

describe("one claim", () => {
  it("shows a rejected claim's reason, who decided and its receipts, which open", async () => {
    const open = vi.spyOn(window, "open").mockReturnValue(null);
    const rejected = claim({
      status: "rejected",
      reject_reason: "No receipt",
      can_cancel: false,
      decided_by: { id: 3, name: "Dilnoza Karimova", photo_url: null },
      decided_at: "2026-11-06T10:00:00+05:00",
      receipts: [
        { id: 31, url: "https://cdn.example.uz/r/31.jpg?sig=a", thumb_url: "https://cdn.example.uz/r/31-thumb.jpg?sig=a", content_type: "image/jpeg", is_image: true },
        { id: 32, url: "https://cdn.example.uz/r/32.pdf?sig=b", thumb_url: null, content_type: "application/pdf", is_image: false },
      ],
    });
    serve({ "/finance/claims/": [rejected] });
    renderApp(<ClaimSheet params={{ id: 12 }} close={() => undefined} />, { me });
    expect(await screen.findByText("Reason: No receipt")).toBeTruthy();
    expect(screen.getByText("Rejected by Dilnoza Karimova, 6 November")).toBeTruthy();
    // The year shows only for another year than this one.
    expect(screen.getByText(/^Date: 5 November/)).toBeTruthy();
    expect(screen.getByText("Branch: Chilonzor")).toBeTruthy();
    expect(screen.getByText("PDF")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Cancel the expense" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Receipt 2" }));
    await waitFor(() => expect(open).toHaveBeenCalledWith("https://cdn.example.uz/r/32.pdf?sig=b", "_blank", "noopener"));
  });

  it("can be cancelled from its sheet while it waits", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    let cancelled = 0;
    serve({ "/finance/claims/": [claim()], "POST /finance/claims/12/cancel/": () => ((cancelled += 1), claim({ status: "cancelled", can_cancel: false })) });
    const closed = vi.fn();
    renderApp(<ClaimSheet params={{ id: 12 }} close={closed} />, { me });
    expect(await screen.findByText("No receipt attached")).toBeTruthy();
    expect(screen.getByText("Waiting for approval")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Cancel the expense" }));
    await waitFor(() => expect(closed).toHaveBeenCalled());
    expect(cancelled).toBe(1);
  });

  it("says when a claim was recorded without anyone's approval", async () => {
    serve({ "/finance/claims/": [claim({ status: "approved", can_cancel: false, decided_at: "2026-11-05T14:32:00+05:00", paid_from: "held_cash", reimburse_via: null })] });
    renderApp(<ClaimSheet params={{ id: 12 }} close={() => undefined} />, { me });
    expect(await screen.findByText("Recorded without approval")).toBeTruthy();
    expect(screen.getByText("Company cash I hold")).toBeTruthy();
  });

  it("says it isn't here for a claim that isn't mine", async () => {
    serve({ "/finance/claims/": [claim()] });
    renderApp(<ClaimSheet params={{ id: 99 }} close={() => undefined} />, { me });
    expect(await screen.findByText("This page isn't here")).toBeTruthy();
  });

  it("opens from the bot's link in the app's sheet layer, through the registry", async () => {
    serve({ "/finance/claims/": [claim()] });
    const init = resolveScreen({ name: "claim", arg: "12" }, features)!;
    // The harness's sheet layer shows the sheet the link opened; nothing else is rendered.
    renderApp(<div />, { me, init });
    expect(await screen.findByText("Taxi to the distributor")).toBeTruthy();
    expect(screen.getByText("Branch: Chilonzor")).toBeTruthy();
  });
});

describe("Me", () => {
  it("shows what is owed to me back, short, and nothing when nothing is", async () => {
    const item = expenses.meItems![0];
    function Row() {
      const status = item.useStatus!({ member: member as never, summary: undefined });
      return <div data-testid="status">{String(status.value)}</div>;
    }
    serve({ "/finance/wallet/": wallet({ owed_to_me: "450000.00" }) });
    renderApp(<Row />, { me });
    await waitFor(() => expect(plain(screen.getByTestId("status").textContent)).toBe("450K UZS owed"));
    cleanup();
    serve();
    renderApp(<Row />, { me });
    await waitFor(() => expect(client.api).toHaveBeenCalled());
    await act(async () => undefined);
    expect(screen.getByTestId("status").textContent).toBe("undefined");
  });
});
