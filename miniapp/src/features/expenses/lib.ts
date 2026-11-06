/**
 * The expenses feature's rules, kept apart from the screens so tests read them plainly: who may
 * claim, how categories group, which receipts may be added, what a new claim needs before it
 * goes, and how the server's refusals map onto the form's fields.
 */
import { ApiError } from "../../api/client";
import { hasModule } from "../../api/membership";
import { can } from "../../api/permissions";
import type { Membership } from "../../api/types";
import { amountFromTyping, compareMoney, isDecimal, isZero, normalizeAmount } from "../../lib/money";
import type { DayKey } from "../../lib/time";
import type { Claim, ClaimInput, ClaimWallet, ExpenseCategory, PaidFrom } from "./api";

export const MAX_RECEIPTS = 5;
export const DESCRIPTION_MAX = 300;
/** What the receipt picker offers: photos and PDF files (a scanned invoice, a bank slip). */
export const RECEIPT_ACCEPT = "image/*,application/pdf";

type Claimer = Pick<Membership, "status" | "permissions" | "company">;

/** Expenses show while the company has finance on, to people who may claim and work here now. */
export function canClaim(member: Claimer): boolean {
  return member.status === "approved" && hasModule(member, "finance") && can(member, "finance.claim");
}

/** An amount from the server, or null when it is missing or not a decimal string. */
function decimal(amount: string | null | undefined): string | null {
  return amount && isDecimal(amount) ? amount : null;
}

/** An amount above zero, else null (for "show this only when there is some"). */
export function positive(amount: string | null | undefined): string | null {
  const value = decimal(amount);
  return value && compareMoney(value, "0") > 0 ? value : null;
}

/** Company cash I hold, when there is some: only then can a claim be paid from it. */
export const heldCash = (wallet: ClaimWallet | undefined): string | null => positive(wallet?.held_total);

// — categories —

export type CategoryGroup = { parent: ExpenseCategory; children: ExpenseCategory[] };

/**
 * Top-level categories in the company's order, each with every category under it (a deeper
 * level joins its top-level ancestor). A child whose parent isn't active stands on its own.
 */
export function groupCategories(categories: readonly ExpenseCategory[]): CategoryGroup[] {
  const byId = new Map(categories.map((category) => [category.id, category]));
  const rootOf = (category: ExpenseCategory): ExpenseCategory => {
    let node = category;
    const seen = new Set<number>();
    while (node.parent_id !== null && byId.has(node.parent_id) && !seen.has(node.id)) {
      seen.add(node.id);
      node = byId.get(node.parent_id)!;
    }
    return node;
  };
  const groups = new Map<number, CategoryGroup>();
  for (const category of categories) {
    const root = rootOf(category);
    const group = groups.get(root.id) ?? { parent: root, children: [] };
    groups.set(root.id, group);
    if (root.id !== category.id) group.children.push(category);
  }
  // A root comes where it stands in the list, not where its first child does.
  return categories.filter((category) => groups.has(category.id)).map((category) => groups.get(category.id)!);
}

/**
 * The categories I claim most, most used first (a tie: the one used last first), among those
 * still active; cancelled claims don't count. For one-tap chips over the full list.
 */
export function usualCategories(claims: readonly Claim[] | undefined, categories: readonly ExpenseCategory[], limit = 4): ExpenseCategory[] {
  if (!claims?.length) return [];
  const active = new Map(categories.map((category) => [category.id, category]));
  const used = new Map<number, { count: number; latest: number }>();
  claims.forEach((claim, index) => {
    if (claim.status === "cancelled" || !active.has(claim.category.id)) return;
    const entry = used.get(claim.category.id);
    if (entry) entry.count += 1;
    else used.set(claim.category.id, { count: 1, latest: index });
  });
  return [...used.entries()]
    .sort(([, a], [, b]) => b.count - a.count || a.latest - b.latest)
    .slice(0, limit)
    .map(([id]) => active.get(id)!);
}

// — receipts —

export const isPdf = (file: Pick<File, "type" | "name">): boolean => file.type === "application/pdf" || /\.pdf$/i.test(file.name);
export const isImage = (file: Pick<File, "type">): boolean => file.type.startsWith("image/");
export const isReceiptFile = (file: Pick<File, "type" | "name">): boolean => isImage(file) || isPdf(file);

/**
 * Picked files added to those already there: photos and PDF files only, at most MAX_RECEIPTS.
 * `dropped` says why some were left out (too many outranks the wrong kind).
 */
export function addReceipts(current: readonly File[], picked: readonly File[]): { files: File[]; dropped: "limit" | "type" | null } {
  const usable = picked.filter(isReceiptFile);
  const room = Math.max(0, MAX_RECEIPTS - current.length);
  const files = [...current, ...usable.slice(0, room)];
  const dropped = usable.length > room ? "limit" : usable.length < picked.length ? "type" : null;
  return { files, dropped };
}

// — a new claim —

export type ClaimForm = {
  /** The money field's typing state ("450000"). */
  typing: string;
  category: number | null;
  spentOn: DayKey;
  description: string;
  paidFrom: PaidFrom;
  receipts: readonly File[];
};

export type ClaimRules = {
  /** The company's today: a claim is never for a day after it. */
  today: DayKey;
  /** Company cash I hold (`heldCash`); without it a claim can't be paid from held cash. */
  held: string | null;
  receiptRequiredOver: string | null | undefined;
};

export type ClaimProblem = "amount" | "category" | "date" | "description" | "heldCash" | "heldOver" | "receipt" | "receipts";

/** Whether the amount is over the company's receipt limit, so a receipt is needed. */
export function needsReceipt(typing: string, receiptRequiredOver: string | null | undefined): boolean {
  const value = amountFromTyping(typing);
  const limit = decimal(receiptRequiredOver);
  return Boolean(value && limit && compareMoney(value, limit) > 0);
}

/** Whether a claim of this amount is recorded without approval (under the company's threshold). */
export function underThreshold(typing: string, approvalThreshold: string | null | undefined): boolean {
  const value = amountFromTyping(typing);
  const limit = decimal(approvalThreshold);
  return Boolean(value && limit && !isZero(value) && compareMoney(value, limit) < 0);
}

/**
 * What the form still needs, and the body to send once it needs nothing. The checks are the
 * server's own (`claims.submit_claim`: a day no later than today, at most five receipts, a
 * receipt over the company's limit, no more than the company cash I hold), made here so the
 * person hears at once; the server checks it all again.
 */
export function claimDraft(form: ClaimForm, rules: ClaimRules): { payload: ClaimInput | null; problems: ClaimProblem[] } {
  const problems: ClaimProblem[] = [];
  const value = amountFromTyping(form.typing);
  if (!value || isZero(value)) problems.push("amount");
  if (form.category === null) problems.push("category");
  if (!/^\d{4}-\d{2}-\d{2}$/.test(form.spentOn) || form.spentOn > rules.today) problems.push("date");
  // A few words help whoever approves it, but the server takes a claim without them (the bot's
  // photo flow sends none), so only their length is checked.
  const description = form.description.trim();
  if (description.length > DESCRIPTION_MAX) problems.push("description");
  if (form.paidFrom === "held_cash") {
    if (!rules.held) problems.push("heldCash");
    else if (value && compareMoney(value, rules.held) > 0) problems.push("heldOver");
  }
  if (needsReceipt(form.typing, rules.receiptRequiredOver) && form.receipts.length === 0) problems.push("receipt");
  if (form.receipts.length > MAX_RECEIPTS) problems.push("receipts");
  if (problems.length || !value || form.category === null) return { payload: null, problems };
  return {
    payload: {
      amount: normalizeAmount(value),
      category: form.category,
      spent_on: form.spentOn,
      description,
      paid_from: form.paidFrom,
      receipts: [...form.receipts],
    },
    problems,
  };
}

// — the server's refusals —

export const CLAIM_FIELDS = ["amount", "category", "spent_on", "description", "paid_from", "receipts"] as const;
export type ClaimField = (typeof CLAIM_FIELDS)[number];

/** The first message anywhere in a DRF error value: "x", ["x"], {"0": ["x"]} (a list field's item). */
function firstMessage(value: unknown): string | null {
  if (typeof value === "string") return value.trim() ? value : null;
  if (Array.isArray(value)) {
    for (const item of value) {
      const found = firstMessage(item);
      if (found) return found;
    }
    return null;
  }
  if (value && typeof value === "object") return firstMessage(Object.values(value));
  return null;
}

/**
 * A 400 from `POST claims/` as the form shows it: each known field's message under that field,
 * and one line for the button's banner (the server's `detail`, else the first message it sent).
 * Null for anything that isn't a 400 with a body.
 */
export function serverProblems(error: unknown): { fields: Partial<Record<ClaimField, string>>; message: string | null } | null {
  if (!(error instanceof ApiError) || error.status !== 400 || !error.body || typeof error.body !== "object") return null;
  const body = error.body as Record<string, unknown>;
  const fields: Partial<Record<ClaimField, string>> = {};
  for (const name of CLAIM_FIELDS) {
    const message = firstMessage(body[name]);
    if (message) fields[name] = message;
  }
  const message = firstMessage(body.detail) ?? firstMessage(body.non_field_errors) ?? firstMessage(body);
  return { fields, message };
}

// — a claim on screen —

/** A claim can be taken back while it waits for a decision (and the server says it may). */
export const canCancel = (claim: Pick<Claim, "status" | "can_cancel">): boolean => claim.status === "submitted" && claim.can_cancel !== false;

/** Whether the money for this claim is still to come back to me (approved, from my own pocket). */
export const comesBack = (claim: Pick<Claim, "status" | "paid_from" | "reimburse_via">): "payroll" | "cash" | null =>
  claim.status === "approved" && claim.paid_from === "own_money" ? claim.reimburse_via : null;
