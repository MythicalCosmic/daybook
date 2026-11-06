/**
 * Small pieces the finance pages share: icons and tones per account kind, entry kind and debt
 * status, the account groups of the Accounts page, the aging buckets, and category options for
 * pickers. Pure functions and constants only (no API calls, no components).
 */
import {
  ArrowLeftRight,
  Banknote,
  CircleDollarSign,
  CreditCard,
  Crown,
  HandCoins,
  Landmark,
  Scale,
  Smartphone,
  TrendingDown,
  TrendingUp,
  Undo2,
  Vault,
  WalletCards,
  type LucideIcon,
} from "@lucide/vue";

import type { StatusTone } from "@/components/StatusPill.vue";
import type { SelectOption } from "@/components/options";
import { parseDay } from "@/lib/dates";
import { dec, toMoney } from "@/lib/decimal";

import type {
  AccountKind,
  AgingBucket,
  BudgetRow,
  BudgetStatus,
  CategoryKind,
  CategoryNode,
  ClaimStatus,
  CounterpartyKind,
  CurrencyTotal,
  Debt,
  DebtStatus,
  Forecast,
  PayableBucket,
  PayableDebt,
  Pnl,
  PnlNode,
  RecurringFrequency,
  RecurringRule,
  TaxTemplateSet,
  Transaction,
  TransactionKind,
  UpcomingItem,
} from "./types";

export const ACCOUNT_ICONS: Record<AccountKind, LucideIcon> = {
  cash: Banknote,
  safe: Vault,
  bank: Landmark,
  card: CreditCard,
  wallet: Smartphone,
  clearing: WalletCards,
  employee: HandCoins,
  owner: Crown,
};

export const ACCOUNT_KINDS: readonly AccountKind[] = ["cash", "safe", "bank", "card", "wallet", "clearing", "employee", "owner"];

/**
 * Accounts in the order pickers offer them: `prefer.id` first (the last one used), then the
 * branch's own accounts, then cash desks and safes before banks, wallets and people's purses.
 */
export function pickerOrder<T extends { id: number; kind: AccountKind; branch_id?: number | null }>(accounts: readonly T[], prefer: { id?: number | null; branch?: number | null } = {}): T[] {
  const rank = (a: T) => ACCOUNT_KINDS.indexOf(a.kind);
  const local = (a: T) => Number(prefer.branch != null && a.branch_id === prefer.branch);
  return [...accounts].sort((a, b) => Number(b.id === prefer.id) - Number(a.id === prefer.id) || local(b) - local(a) || rank(a) - rank(b));
}

/**
 * The accounts a short list shows (the finance overview's Accounts card): where the money is,
 * biggest first in the base currency (an overdrawn account counts by its size, so it shows), and
 * empty desks and safes last.
 */
export function topAccounts<T extends { id: number; balance: string; base?: string | null }>(accounts: readonly T[], limit: number): T[] {
  const size = (account: T) => dec(account.base ?? account.balance).abs();
  return [...accounts].sort((a, b) => size(b).comparedTo(size(a)) || a.id - b.id).slice(0, limit);
}

/**
 * What a group of accounts holds in the base currency: own-currency balances as they are, the
 * others at their valued amount. Null when a foreign balance has no value yet (no rate), so a
 * total that would be wrong is not shown.
 */
export function baseTotal(rows: ReadonlyArray<{ currency: string; balance: string; base?: string | null }>, base: string): string | null {
  const parts = rows.map((row) => (row.currency === base ? row.balance : row.base ?? null));
  return parts.some((part) => part === null) ? null : toMoney(parts.reduce((total, part) => total.plus(dec(part)), dec(0)));
}

/** How the Accounts page groups accounts, in order. */
export const ACCOUNT_GROUPS: ReadonlyArray<{ id: string; kinds: readonly AccountKind[] }> = [
  { id: "cash", kinds: ["cash", "safe"] },
  { id: "bank", kinds: ["bank", "card"] },
  { id: "digital", kinds: ["wallet", "clearing"] },
  { id: "people", kinds: ["employee", "owner"] },
];

export const KIND_ICONS: Partial<Record<TransactionKind, LucideIcon>> = {
  income: TrendingUp,
  expense: TrendingDown,
  transfer: ArrowLeftRight,
  debt_open: HandCoins,
  debt_payment: HandCoins,
  write_off: Undo2,
  fx: Scale,
  owner: Crown,
  opening: CircleDollarSign,
};

// The Status column marks entries that aren't plain income or expense: money moving between
// balance-sheet items reads calm (a debt payment is routine, not a warning).
export const KIND_TONES: Record<TransactionKind, StatusTone> = {
  income: "success",
  expense: "danger",
  transfer: "info",
  debt_open: "info",
  debt_payment: "info",
  write_off: "neutral",
  fx: "neutral",
  owner: "primary",
  opening: "neutral",
};

export const STATUS_TONES: Record<Transaction["status"], StatusTone> = {
  posted: "success",
  pending: "warning",
  rejected: "danger",
  void: "neutral",
};

export const DEBT_TONES: Record<DebtStatus, StatusTone> = {
  open: "primary",
  paid: "success",
  written_off: "neutral",
  cancelled: "neutral",
};

export const AGING_BUCKETS: readonly AgingBucket[] = ["current", "d1_30", "d31_60", "d61_90", "d90"];

/** Bucket colors: calm for "not due", warmer and darker as debts age. Token colors only. */
export const AGING_COLORS: Record<AgingBucket, string> = {
  current: "var(--c-chart-2)",
  d1_30: "var(--c-chart-4)",
  d31_60: "var(--c-chart-1)",
  d61_90: "var(--c-chart-7)",
  d90: "var(--c-danger)",
};

/**
 * Colours a person may give an account or a category. They are stored values (the backend keeps
 * "#rrggbb"), chosen to equal the light chart palette (`--c-chart-1…8` in styles/tokens.css), so a
 * coloured account sits well next to the charts in both themes.
 */
export const ACCOUNT_SWATCHES = ["#c67139", "#7a8a5e", "#4a6a8a", "#d1a040", "#8a5a7a", "#3f8a83", "#a66a4f", "#8c857a"] as const;

/**
 * A stable chart color for something without one (categories, accounts). A stored swatch becomes
 * its palette token, so it follows the dark theme like every chart colour (the stored "#c67139"
 * is the light theme's chart-1 and looks dull on the dark surface).
 */
export function colorFor(id: number, color?: string | null): string {
  if (color) {
    const swatch = (ACCOUNT_SWATCHES as readonly string[]).indexOf(color.toLowerCase());
    return swatch >= 0 ? `var(--c-chart-${swatch + 1})` : color;
  }
  return `var(--c-chart-${(Math.abs(id) % 8) + 1})`;
}

/** The palette slot a stored swatch or a chart token stands for ("chart-3"), else the colour. */
function paletteKey(color: string): string {
  const swatch = (ACCOUNT_SWATCHES as readonly string[]).indexOf(color.toLowerCase());
  if (swatch >= 0) return `chart-${swatch + 1}`;
  const token = /^var\(--c-chart-(\d)\)$/.exec(color.trim());
  return token ? `chart-${token[1]}` : color.toLowerCase();
}

/** Free colours in the charts' colour-blind safe order, without the warm gray of "Other". */
const FREE_SLOTS = [1, 3, 4, 5, 6, 2, 7].map((n) => `var(--c-chart-${n})`);

/**
 * Colours for a ranked list a chart shows side by side (the month's expenses by category, biggest
 * first): each row keeps its own colour unless a bigger row already has it (with eight colours,
 * categories often share one) or it is the gray of the "Other" slice; then it takes the next free
 * palette colour, so no two slices of one donut look alike.
 */
export function distinctColors(rows: ReadonlyArray<{ id: number; color?: string | null }>): string[] {
  const used = new Set<string>(["chart-8"]);
  return rows.map((row) => {
    let color = colorFor(row.id, row.color);
    if (used.has(paletteKey(color))) color = FREE_SLOTS.find((slot) => !used.has(paletteKey(slot))) ?? color;
    used.add(paletteKey(color));
    return color;
  });
}

/**
 * What a profit or a net figure is compared with: `previous`, or undefined (no change shown) when
 * the figure crossed zero, where a percentage misleads (a profit of 41 M after a loss of 36 M is
 * not "+214 %", a net of −64 M after +411 M is not "−115 %"). Null (nothing to compare) stays.
 */
export function comparablePrevious(value: string | null | undefined, previous: string | null | undefined): string | null | undefined {
  if (value === null || value === undefined || previous === null || previous === undefined) return previous;
  const now = dec(value);
  const before = dec(previous);
  if (now.isZero() || before.isZero()) return previous;
  return now.isNegative() === before.isNegative() ? previous : undefined;
}

/**
 * The tags a one-line cell shows: in order while they fit about `letters` letters (the first
 * always), and how many more there are, for a "+N".
 */
export function fitTags(tags: readonly string[], letters: number): { shown: string[]; more: number } {
  const shown: string[] = [];
  let used = 0;
  for (const tag of tags) {
    if (shown.length && used + tag.length > letters) break;
    shown.push(tag);
    used += tag.length;
  }
  return { shown, more: tags.length - shown.length };
}

/** Counterparty kinds as pills, the same on the list and on a counterparty's page. */
export const PARTY_TONES: Record<CounterpartyKind, StatusTone> = { customer: "success", supplier: "info", both: "primary", state: "warning", other: "neutral" };

/** Category options for a picker of one kind: parents first, their subcategories under them. */
export function categoryOptions(tree: CategoryNode[] | undefined, kind: CategoryKind | null, opts: { activeOnly?: boolean } = {}): SelectOption<number>[] {
  const out: SelectOption<number>[] = [];
  for (const node of tree ?? []) {
    if (kind && node.kind !== kind) continue;
    if (opts.activeOnly && !node.is_active) continue;
    out.push({ value: node.id, label: node.name, color: colorFor(node.id, node.color), keywords: node.children.map((c) => c.name) });
    for (const child of node.children) {
      if (opts.activeOnly && !child.is_active) continue;
      out.push({ value: child.id, label: child.name, description: node.name, color: colorFor(child.id, child.color || node.color), keywords: [node.name] });
    }
  }
  return out;
}

export function findCategory(tree: CategoryNode[] | undefined, id: number | null | undefined): CategoryNode | null {
  if (!id) return null;
  for (const node of tree ?? []) {
    if (node.id === id) return node;
    const child = node.children.find((c) => c.id === id);
    if (child) return child;
  }
  return null;
}

/** "Rent › Chilonzor" for a child category, the name alone for a top-level one. */
export function categoryLabel(category: { name: string; parent_name?: string | null } | null | undefined): string {
  if (!category) return "";
  return category.parent_name ? `${category.parent_name} › ${category.name}` : category.name;
}

/** Share of `part` in `whole` as 0–100 (display only). */
export function share(part: string | number, whole: string | number): number {
  const total = dec(whole);
  if (total.isZero()) return 0;
  return Math.max(0, Math.min(100, dec(part).div(total).times(100).toNumber()));
}

export function isNegative(value: string | null | undefined): boolean {
  return value !== null && value !== undefined && dec(value).isNegative() && !dec(value).isZero();
}

export function isZeroMoney(value: string | null | undefined): boolean {
  return value === null || value === undefined || dec(value).isZero();
}

/** The positive size of a signed amount, as the API's decimal string. */
export function absolute(value: string): string {
  return dec(value).abs().toFixed(2);
}

/** "9 Sept" this year, "23 Aug 2027" otherwise: due dates of long loans must not read as past days. */
/**
 * The line under a cash total in the company's currency: the foreign money counted in it, and the
 * money left out because its currency has no rate yet (the server's `complete: false`). It used to
 * say "included" for both, so a missing USD rate dropped the dollar accounts from "Cash now" unseen.
 */
export function foreignCashLine(
  byCurrency: readonly CurrencyTotal[],
  baseCurrency: string,
  money: (amount: string, currency: CurrencyTotal["currency"]) => string,
  t: (key: string, params?: Record<string, unknown>) => string,
): string | null {
  const foreign = byCurrency.filter((row) => row.currency !== baseCurrency && !dec(row.amount).isZero());
  const counted = foreign.filter((row) => row.base !== null);
  const left = foreign.filter((row) => row.base === null);
  const list = (rows: readonly CurrencyTotal[]) => rows.map((row) => money(row.amount, row.currency)).join(" · ");
  const parts = [counted.length ? `${list(counted)} ${t("finance.overview.included")}` : "", left.length ? t("finance.overview.notCounted", { amounts: list(left) }) : ""];
  return parts.filter(Boolean).join(" · ") || null;
}

export interface DebtEdit {
  due_on: string | null;
  responsible: number | null;
  description: string;
}

/**
 * What an edit of a debt changes, and only that. A salary or advance debt reads with an empty
 * description for people who may not see payroll: sending it back erased the real one.
 */
export function debtChanges(debt: Pick<Debt, "due_on" | "responsible" | "description" | "masked">, draft: DebtEdit): Partial<DebtEdit> {
  const changes: Partial<DebtEdit> = {};
  if (draft.due_on !== debt.due_on) changes.due_on = draft.due_on;
  if (draft.responsible !== (debt.responsible?.id ?? null)) changes.responsible = draft.responsible;
  if (!debt.masked && draft.description !== debt.description) changes.description = draft.description;
  return changes;
}

export function dayStyle(day: string, now: Date = new Date()): "short" | "medium" {
  return day.slice(0, 4) === String(now.getFullYear()) ? "short" : "medium";
}

/**
 * A P&L without the empty months before the books started (a shop that began in August shows
 * August to October for "this year", not seven columns of zeros). Totals are unchanged: the
 * dropped columns are all zero. At least one period is always kept.
 */
/**
 * The P&L without its comparison when the compared period has nothing booked at all (a business
 * whose books began this year compared with last year): a "Previous 0" column and "—" deltas on
 * every row would only be noise.
 */
export function dropEmptyCompare(data: Pnl): Pnl {
  if (!data.compare) return data;
  const empty = (value: string | null) => value === null || isZeroMoney(value);
  if (!empty(data.income.previous) || !empty(data.expense.previous)) return data;
  const node = (n: PnlNode): PnlNode => ({ ...n, previous: null, children: n.children.map(node) });
  const section = (part: Pnl["income"]): Pnl["income"] => ({ ...part, previous: null, nodes: part.nodes.map(node) });
  return {
    ...data,
    compare: null,
    income: section(data.income),
    expense: section(data.expense),
    profit: { ...data.profit, previous: null },
    margin: { ...data.margin, previous: null },
  };
}

/**
 * A series without the empty buckets before the first money moved (a young ledger shown over 90
 * days or 12 months would otherwise start with an empty stretch). At least `keep` points stay.
 */
export function trimLeadingEmpty<T extends { income: string; expense: string }>(series: T[], keep = 7): T[] {
  let skip = 0;
  while (skip < series.length - keep && isZeroMoney(series[skip]!.income) && isZeroMoney(series[skip]!.expense)) skip += 1;
  return skip ? series.slice(skip) : series;
}

export function trimLeadingPeriods(data: Pnl): Pnl {
  const last = data.periods.length - 1;
  let skip = 0;
  while (skip < last && isZeroMoney(data.income.amounts[skip] ?? "0") && isZeroMoney(data.expense.amounts[skip] ?? "0")) skip += 1;
  if (!skip) return data;
  const node = (n: PnlNode): PnlNode => ({ ...n, amounts: n.amounts.slice(skip), own: n.own.slice(skip), children: n.children.map(node) });
  const section = (part: Pnl["income"]): Pnl["income"] => ({ ...part, amounts: part.amounts.slice(skip), nodes: part.nodes.map(node) });
  return {
    ...data,
    periods: data.periods.slice(skip),
    income: section(data.income),
    expense: section(data.expense),
    profit: { ...data.profit, amounts: data.profit.amounts.slice(skip) },
    margin: { ...data.margin, amounts: data.margin.amounts.slice(skip) },
  };
}

/** A quarter key from the API ("2026-Q3") in the language's words: "Q3 2026", "2026, 3-chorak", "3 кв. 2026"; null for a month. */
export function quarterLabel(key: string, t: (key: string, params: Record<string, unknown>) => string): string | null {
  const match = /^(\d{4})-Q([1-4])$/.exec(key);
  return match ? t("finance.reports.quarter", { year: match[1], q: match[2] }) : null;
}

// ─── Money planning (package I) ─────────────────────────────────────────────────────────────

type Translate = (key: string, params?: Record<string, unknown>) => string;

/** A month as the API writes it: "2026-11". */
export function isMonth(value: string): boolean {
  return /^\d{4}-(0[1-9]|1[0-2])$/.test(value);
}

/** The month `amount` months from `month`: shiftMonth("2026-01", -1) is "2025-12". */
export function shiftMonth(month: string, amount: number): string {
  const [year, number] = month.split("-").map(Number) as [number, number];
  const index = year * 12 + (number - 1) + amount;
  const nextYear = Math.floor(index / 12);
  return `${nextYear}-${String(index - nextYear * 12 + 1).padStart(2, "0")}`;
}

/** The first day of a month, to format it ("November 2026"). */
export function monthStart(month: string): string {
  return `${month}-01`;
}

const hasBudget = (budget: string | null | undefined): budget is string => budget !== null && budget !== undefined && budget !== "" && dec(budget).gt(0);

/** How much of a budget is spent, as a fraction (0.82; above 1 when over), or null without a budget. */
export function budgetShare(budget: string | null | undefined, actual: string): number | null {
  return hasBudget(budget) ? dec(actual).div(dec(budget)).toNumber() : null;
}

/**
 * The server's status rule for a budget being typed, so the bar answers before it is saved: a
 * warning from 80 % of the budget, over from 100 %, compared in decimals (exactly 80 % warns).
 */
export function budgetStatus(budget: string | null | undefined, actual: string): BudgetStatus {
  if (!hasBudget(budget)) return "none";
  const spent = dec(actual);
  if (spent.gte(dec(budget))) return "over";
  return spent.times(5).gte(dec(budget).times(4)) ? "warning" : "ok";
}

/** Bar and pill tones per budget status. */
export const BUDGET_TONES: Record<BudgetStatus, StatusTone> = { none: "neutral", ok: "success", warning: "warning", over: "danger" };

export interface BudgetLine<T> {
  row: T;
  depth: 0 | 1;
  /** A top-level category with subcategories listed under it. */
  parent: boolean;
}

/**
 * Budget rows in the table's order: each top-level category followed by its subcategories (the
 * API sends both levels and says which is which with `parent_id`). A row whose parent is missing
 * stands at the top level; anything deeper than two levels is listed last, never dropped.
 */
export function budgetLines<T extends { category: { id: number; parent_id: number | null } }>(rows: readonly T[]): BudgetLine<T>[] {
  const ids = new Set(rows.map((row) => row.category.id));
  const children = new Map<number, T[]>();
  const tops: T[] = [];
  for (const row of rows) {
    const parent = row.category.parent_id;
    if (parent !== null && parent !== row.category.id && ids.has(parent)) children.set(parent, [...(children.get(parent) ?? []), row]);
    else tops.push(row);
  }
  const lines: BudgetLine<T>[] = [];
  const shown = new Set<number>();
  for (const top of tops) {
    const kids = children.get(top.category.id) ?? [];
    lines.push({ row: top, depth: 0, parent: kids.length > 0 });
    shown.add(top.category.id);
    for (const kid of kids) {
      lines.push({ row: kid, depth: 1, parent: false });
      shown.add(kid.category.id);
    }
  }
  for (const row of rows) if (!shown.has(row.category.id)) lines.push({ row, depth: 1, parent: false });
  return lines;
}

/** How much of the month has gone, in percent: the even pace a budget is measured against (20 with 24 of 30 days left). */
export function monthPace(daysLeft: number, daysInMonth: number): number {
  if (daysInMonth <= 0) return 0;
  return Math.min(100, Math.max(0, ((daysInMonth - daysLeft) / daysInMonth) * 100));
}

const sameMoney = (a: string | null, b: string | null): boolean => (a === null || b === null ? a === b : dec(a).eq(dec(b)));

/**
 * The typed budgets that differ from the saved ones, as `PUT budgets/` takes them (null removes one).
 * `in`, not hasOwnProperty: on a reactive draft only `in` is tracked, so a first typed budget counts.
 */
export function budgetChanges(rows: readonly BudgetRow[], drafts: Readonly<Record<number, string | null>>): Array<{ category: number; amount: string | null }> {
  const changes: Array<{ category: number; amount: string | null }> = [];
  for (const row of rows) {
    if (!(row.category.id in drafts)) continue;
    const typed = drafts[row.category.id];
    const next = typed === undefined || typed === null || typed === "" ? null : typed;
    if (!sameMoney(next, row.budget)) changes.push({ category: row.category.id, amount: next });
  }
  return changes;
}

/**
 * The month's budget total with the typed changes, added up as the server does (`budgets.month_view`):
 * every top-level budget, and a subcategory's only while its parent has none (a parent's actual
 * already holds its children's spending). Without changes it is the server's own total.
 */
export function draftBudgetTotal(total: string, rows: readonly BudgetRow[], changes: ReadonlyArray<{ category: number; amount: string | null }>): string {
  if (!changes.length) return total;
  const typed = new Map(changes.map((change) => [change.category, change.amount]));
  const byId = new Map(rows.map((row) => [row.category.id, row]));
  const budgetOf = (row: BudgetRow) => (typed.has(row.category.id) ? (typed.get(row.category.id) ?? null) : row.budget);
  const set = (value: string | null) => value !== null && value !== "";
  let sum = dec(0);
  for (const row of rows) {
    const budget = budgetOf(row);
    if (!set(budget)) continue;
    const parent = row.category.parent_id !== null ? byId.get(row.category.parent_id) : undefined;
    if (!parent || !set(budgetOf(parent))) sum = sum.plus(dec(budget));
  }
  return toMoney(sum);
}

// Recurring rules ------------------------------------------------------------------------------

export type RuleGroup = "bill" | "auto" | "tax";

/** Which list a rule belongs to: taxes apart from the other bills, auto-posted ones apart from both. */
export function ruleGroup(rule: Pick<RecurringRule, "mode" | "is_tax">): RuleGroup {
  return rule.is_tax ? "tax" : rule.mode;
}

/** The day a rule falls on, from a date: weekly 1–7 (Monday first), otherwise the day of the month. */
export function ruleDayFrom(day: string, frequency: RecurringFrequency): number {
  const date = parseDay(day);
  return frequency === "weekly" ? ((date.getUTCDay() + 6) % 7) + 1 : date.getUTCDate();
}

/**
 * A rule's schedule in words: "Monthly, day 25", "Every 2 weeks: Monday", "Yearly, 25 Mar" (the
 * month of a yearly rule is its start's month; day 31 means the month's last day).
 */
export function scheduleText(rule: Pick<RecurringRule, "frequency" | "interval" | "day" | "starts_on">, t: Translate, formatDay: (day: string) => string): string {
  const n = Math.max(1, rule.interval || 1);
  const many = n > 1 ? "N" : "";
  if (rule.frequency === "weekly") {
    const weekday = t(`common.weekday.long.${Math.min(7, Math.max(1, rule.day)) - 1}`);
    return t(`finance.recurring.freq.weekly${many}`, { n, when: weekday });
  }
  if (rule.frequency === "yearly") {
    const month = rule.starts_on.slice(0, 7);
    const first = parseDay(`${month}-01`);
    const length = new Date(Date.UTC(first.getUTCFullYear(), first.getUTCMonth() + 1, 0)).getUTCDate();
    const date = `${month}-${String(Math.min(rule.day, length)).padStart(2, "0")}`;
    return t(`finance.recurring.freq.yearly${many}`, { n, when: formatDay(date) });
  }
  const when = rule.day >= 31 ? t("finance.recurring.lastDay") : t("finance.recurring.dayN", { day: rule.day });
  return t(`finance.recurring.freq.${rule.frequency}${many}`, { n, when });
}

/** The tax calendar's template sets with the company's own regime first. */
export function taxSetsInOrder(sets: readonly TaxTemplateSet[]): TaxTemplateSet[] {
  return [...sets].sort((a, b) => Number(b.current) - Number(a.current));
}

// Upcoming payments and the forecast --------------------------------------------------------------

export interface UpcomingGroup {
  /** "overdue", or the day. */
  key: string;
  /** Null for the overdue group. */
  day: string | null;
  items: UpcomingItem[];
  /** What is known to come in and go out that day, in the base currency. */
  in: string;
  out: string;
}

/**
 * Upcoming items by day, everything overdue first in one group. A day's totals add the items with
 * an amount in the base currency; an unknown amount or a dollar debt shows on its own line only.
 */
export function groupUpcoming(items: readonly UpcomingItem[], base: string): UpcomingGroup[] {
  const sorted = [...items].sort((a, b) => Number(b.overdue) - Number(a.overdue) || a.date.localeCompare(b.date));
  const groups = new Map<string, UpcomingGroup>();
  for (const item of sorted) {
    const key = item.overdue ? "overdue" : item.date;
    let group = groups.get(key);
    if (!group) {
      group = { key, day: item.overdue ? null : item.date, items: [], in: "0.00", out: "0.00" };
      groups.set(key, group);
    }
    group.items.push(item);
    if (item.amount !== null && item.currency === base) {
      if (item.direction === "in") group.in = toMoney(dec(group.in).plus(dec(item.amount)));
      else group.out = toMoney(dec(group.out).plus(dec(item.amount)));
    }
  }
  return [...groups.values()];
}

export type UpcomingTarget = { type: "pay"; ruleId: number } | { type: "link"; to: string } | { type: "none" };

/**
 * Where an upcoming item is dealt with: a bill or a tax is paid right there (or opened on the
 * recurring page for someone who can't record payments), an auto-posted rule on the recurring
 * page, a payable on the Payables page with it ticked, a receivable in its debt's drawer, and
 * anything else (payroll) where the server points.
 */
export function upcomingTarget(item: UpcomingItem, base: string, canPay: boolean): UpcomingTarget {
  if ((item.kind === "bill" || item.kind === "tax") && item.rule_id !== null) {
    return canPay ? { type: "pay", ruleId: item.rule_id } : { type: "link", to: `${base}/recurring?rule=${item.rule_id}` };
  }
  if (item.kind === "auto" && item.rule_id !== null) return { type: "link", to: `${base}/recurring?rule=${item.rule_id}` };
  if (item.kind === "payable" && item.debt_id !== null) return { type: "link", to: `${base}/payables?select=${item.debt_id}` };
  if (item.kind === "receivable" && item.debt_id !== null) return { type: "link", to: `${base}/debts?direction=receivable&debt=${item.debt_id}` };
  return item.url ? { type: "link", to: item.url } : { type: "none" };
}

export type ForecastHeadline = { kind: "below"; date: string; balance: string } | { kind: "low"; date: string; balance: string };

/** The forecast in one line: the first day cash goes below zero, else its lowest point. */
export function forecastHeadline(forecast: Pick<Forecast, "below_zero_on" | "low" | "points">): ForecastHeadline {
  if (forecast.below_zero_on) {
    const point = forecast.points.find((row) => row.date === forecast.below_zero_on);
    return { kind: "below", date: forecast.below_zero_on, balance: point?.balance ?? forecast.low.balance };
  }
  return { kind: "low", date: forecast.low.date, balance: forecast.low.balance };
}

// Payables -------------------------------------------------------------------------------------------

export const PAYABLE_BUCKETS: readonly PayableBucket[] = ["overdue", "week", "later"];
export const BUCKET_TONES: Record<PayableBucket, StatusTone> = { overdue: "danger", week: "warning", later: "neutral" };

/** Accounts that hold cash or a person's money: a goods-receipt payable shouldn't be paid from them. */
export const CASH_ACCOUNT_KINDS: readonly AccountKind[] = ["cash", "safe", "employee", "owner"];

/**
 * Wholesale of marked medicines is paid by bank transfer (plan §14.4 row 25): paying a
 * goods-receipt payable from a cash desk, a safe or someone's own money gets a warning first.
 */
export function bankTransferWarning(debts: ReadonlyArray<{ bank_only: boolean }>, account: { kind: AccountKind } | null | undefined): boolean {
  return !!account && CASH_ACCOUNT_KINDS.includes(account.kind) && debts.some((debt) => debt.bank_only);
}

/** What payables owe per bucket and in all, in the base currency. */
export function bucketTotals(debts: ReadonlyArray<Pick<PayableDebt, "bucket" | "base_outstanding">>): Record<PayableBucket | "all", string> {
  const totals: Record<PayableBucket | "all", ReturnType<typeof dec>> = { overdue: dec(0), week: dec(0), later: dec(0), all: dec(0) };
  for (const debt of debts) {
    totals[debt.bucket] = totals[debt.bucket].plus(dec(debt.base_outstanding));
    totals.all = totals.all.plus(dec(debt.base_outstanding));
  }
  return { overdue: toMoney(totals.overdue), week: toMoney(totals.week), later: toMoney(totals.later), all: toMoney(totals.all) };
}

/** An amount someone may pay on a debt: more than zero and no more than what is left. */
export function validPayment(amount: string | null | undefined, outstanding: string): boolean {
  return !!amount && dec(amount).gt(0) && dec(amount).lte(dec(outstanding));
}

// Claims ---------------------------------------------------------------------------------------------

export const CLAIM_TONES: Record<ClaimStatus, StatusTone> = { submitted: "warning", approved: "info", paid: "success", rejected: "danger", cancelled: "neutral" };
