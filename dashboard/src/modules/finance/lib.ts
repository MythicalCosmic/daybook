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
import { dec, toMoney } from "@/lib/decimal";

import type { AccountKind, AgingBucket, CategoryKind, CategoryNode, CounterpartyKind, DebtStatus, Pnl, PnlNode, Transaction, TransactionKind } from "./types";

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

export const KIND_TONES: Record<TransactionKind, StatusTone> = {
  income: "success",
  expense: "danger",
  transfer: "info",
  debt_open: "warning",
  debt_payment: "warning",
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
