<script setup lang="ts">
/**
 * The profit and loss statement as a tree table (plan §6.2 "P&L by month/category/branch with
 * drill-down"): income and expense categories down the side, one column per month or quarter, a
 * total and (with a comparison) the previous period and the change. Parents open to their
 * subcategories; an amount opens the entries behind it.
 */
import { ChevronRight } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink } from "vue-router";

import DeltaBadge from "@/components/DeltaBadge.vue";
import { changePercent } from "@/lib/decimal";
import { currencyLabel } from "@/lib/money";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { colorFor, comparablePrevious, isNegative, isZeroMoney } from "../../lib";
import type { Pnl, PnlNode } from "../../types";

const props = defineProps<{ data: Pnl }>();

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const open = ref<Set<number>>(new Set());
const compare = computed(() => props.data.compare !== null);
// A P&L reads as a grid of numbers: the currency is said once, in the header, not in every cell.
const unit = computed(() => currencyLabel(props.data.currency, fmt.lang.value));
function num(value: string | null): string {
  return value === null ? "—" : fmt.money(value, props.data.currency, { decimals: "never", currencyDisplay: "none" });
}

function toggle(id: number): void {
  const next = new Set(open.value);
  if (next.has(id)) next.delete(id);
  else next.add(id);
  open.value = next;
}

function expandAll(value: boolean): void {
  open.value = value ? new Set([...props.data.income.nodes, ...props.data.expense.nodes].filter((n) => n.children.length).map((n) => n.id)) : new Set();
}
defineExpose({ expandAll });

function periodLabel(key: string): string {
  if (key.includes("Q")) return key.replace("-", " ");
  // A column heading starts with a capital in every language ("Октябрь 2026 г.", "Oktabr 2026").
  const label = fmt.day(`${key}-01`, "monthYear");
  return label.charAt(0).toLocaleUpperCase() + label.slice(1);
}

/** Entries behind one cell: the category (with its subcategories) in that period. */
function drill(node: PnlNode | null, index: number | "total"): Record<string, unknown> {
  const range = index === "total" ? props.data.range : props.data.periods[index]!;
  return {
    path: `/c/${company.currentId}/finance/transactions`,
    query: { from: range.from, to: range.to, ...(node ? { category: String(node.id) } : {}) },
  };
}

function delta(current: string, previous: string | null): number | null {
  // A change across zero (a loss that became a profit) has no meaningful percentage: "—".
  const before = comparablePrevious(current, previous);
  return before === null || before === undefined ? null : changePercent(current, before);
}

interface Row {
  key: string;
  node: PnlNode;
  depth: number;
  section: "income" | "expense";
  own?: boolean;
}

function rows(section: "income" | "expense"): Row[] {
  const out: Row[] = [];
  for (const node of props.data[section].nodes) {
    out.push({ key: `${section}-${node.id}`, node, depth: 0, section });
    if (node.children.length && open.value.has(node.id)) {
      for (const child of node.children) out.push({ key: `${section}-${child.id}`, node: child, depth: 1, section });
      if (!isZeroMoney(node.own_total)) {
        out.push({ key: `${section}-${node.id}-own`, node: { ...node, amounts: node.own, total: node.own_total, previous: null, children: [] }, depth: 1, section, own: true });
      }
    }
  }
  return out;
}

const incomeRows = computed(() => rows("income"));
const expenseRows = computed(() => rows("expense"));
const columnCount = computed(() => props.data.periods.length + 2 + (compare.value ? 2 : 0));
</script>

<template>
  <div class="pnl ui-card overflow-hidden">
    <div class="overflow-x-auto">
      <table class="w-full min-w-[640px] border-separate border-spacing-0 text-base">
        <thead>
          <tr class="bg-surface-2 text-xs font-semibold text-muted">
            <th scope="col" class="sticky left-0 z-[1] min-w-[220px] bg-surface-2 px-4 py-2.5 text-left">{{ t("finance.reports.category") }} <span class="font-normal text-subtle" data-testid="pnl-unit">({{ unit }})</span></th>
            <th v-for="period in data.periods" :key="period.key" scope="col" class="whitespace-nowrap px-3 py-2.5 text-right">{{ periodLabel(period.key) }}</th>
            <th scope="col" class="whitespace-nowrap px-3 py-2.5 text-right text-fg">{{ t("finance.reports.total") }}</th>
            <template v-if="compare">
              <th scope="col" class="whitespace-nowrap px-3 py-2.5 text-right">{{ t("finance.reports.previous") }}</th>
              <th scope="col" class="whitespace-nowrap px-3 py-2.5 text-right">{{ t("finance.reports.change") }}</th>
            </template>
          </tr>
        </thead>
        <tbody>
          <template v-for="section in (['income', 'expense'] as const)" :key="section">
            <tr class="section">
              <th scope="rowgroup" class="sticky left-0 z-[1] bg-surface px-4 pb-1.5 pt-4 text-left text-sm font-semibold text-fg" :colspan="1">
                {{ section === "income" ? t("finance.reports.income") : t("finance.reports.expenses") }}
              </th>
              <td :colspan="columnCount - 1" class="bg-surface" />
            </tr>
            <tr
              v-for="row in section === 'income' ? incomeRows : expenseRows"
              :key="row.key"
              :class="['group', row.depth ? 'child' : 'parent']"
            >
              <th scope="row" class="sticky left-0 z-[1] bg-surface px-4 py-2 text-left font-normal group-hover:bg-surface-2/60">
                <button
                  v-if="row.node.children.length"
                  type="button"
                  class="flex w-full min-w-0 items-center gap-2 text-left"
                  :aria-expanded="open.has(row.node.id)"
                  @click="toggle(row.node.id)"
                >
                  <ChevronRight :size="14" :class="['shrink-0 text-subtle transition-transform duration-180', open.has(row.node.id) && 'rotate-90']" />
                  <span class="size-2 shrink-0 rounded-full" :style="{ background: colorFor(row.node.id, row.node.color) }" aria-hidden="true" />
                  <span class="truncate font-medium text-fg">{{ row.node.name }}</span>
                </button>
                <span v-else :class="['flex min-w-0 items-center gap-2', row.depth && 'pl-[22px]']">
                  <span v-if="!row.depth" class="w-[14px] shrink-0" aria-hidden="true" />
                  <span class="size-2 shrink-0 rounded-full" :style="{ background: colorFor(row.node.id, row.node.color) }" aria-hidden="true" />
                  <span :class="['truncate', row.depth ? 'text-muted' : 'font-medium text-fg']">{{ row.own ? t("finance.reports.direct", { name: row.node.name }) : row.node.name }}</span>
                </span>
              </th>
              <td v-for="(amount, index) in row.node.amounts" :key="index" class="px-3 py-2 text-right tabular-nums group-hover:bg-surface-2/60">
                <RouterLink v-if="!isZeroMoney(amount)" :to="drill(row.own ? null : row.node, index)" class="rounded-[4px] text-fg hover:text-accent-fg hover:underline">
                  <span class="whitespace-nowrap">{{ num(amount) }}</span>
                </RouterLink>
                <span v-else class="text-subtle">—</span>
              </td>
              <td class="px-3 py-2 text-right font-semibold tabular-nums text-fg group-hover:bg-surface-2/60">
                <RouterLink :to="drill(row.own ? null : row.node, 'total')" class="hover:text-accent-fg hover:underline"><span class="whitespace-nowrap">{{ num(row.node.total) }}</span></RouterLink>
              </td>
              <template v-if="compare">
                <td class="px-3 py-2 text-right tabular-nums text-muted group-hover:bg-surface-2/60"><span class="whitespace-nowrap">{{ num(row.node.previous) }}</span></td>
                <td class="px-3 py-2 text-right group-hover:bg-surface-2/60">
                  <DeltaBadge v-if="row.node.previous !== null" :value="delta(row.node.total, row.node.previous)" :inverse="section === 'expense'" size="sm" />
                </td>
              </template>
            </tr>
            <tr class="subtotal">
              <th scope="row" class="sticky left-0 z-[1] border-t border-line bg-surface px-4 py-2.5 text-left text-sm font-semibold text-fg">
                {{ section === "income" ? t("finance.reports.totalIncome") : t("finance.reports.totalExpenses") }}
              </th>
              <td v-for="(amount, index) in data[section].amounts" :key="index" class="border-t border-line px-3 py-2.5 text-right font-semibold tabular-nums text-fg">
                <span class="whitespace-nowrap">{{ num(amount) }}</span>
              </td>
              <td class="border-t border-line px-3 py-2.5 text-right font-semibold tabular-nums text-fg"><span class="whitespace-nowrap">{{ num(data[section].total) }}</span></td>
              <template v-if="compare">
                <td class="border-t border-line px-3 py-2.5 text-right tabular-nums text-muted"><span class="whitespace-nowrap">{{ num(data[section].previous) }}</span></td>
                <td class="border-t border-line px-3 py-2.5 text-right"><DeltaBadge :value="delta(data[section].total, data[section].previous)" :inverse="section === 'expense'" size="sm" /></td>
              </template>
            </tr>
          </template>
          <tr class="profit">
            <th scope="row" class="sticky left-0 z-[1] bg-surface-2 px-4 py-3 text-left text-md font-semibold text-fg">{{ t("finance.reports.profit") }}</th>
            <td v-for="(amount, index) in data.profit.amounts" :key="index" :class="['bg-surface-2 px-3 py-3 text-right text-md font-semibold tabular-nums', isNegative(amount) ? 'text-danger' : 'text-success']">
              <span class="whitespace-nowrap">{{ num(amount) }}</span>
            </td>
            <td :class="['bg-surface-2 px-3 py-3 text-right text-md font-semibold tabular-nums', isNegative(data.profit.total) ? 'text-danger' : 'text-success']"><span class="whitespace-nowrap">{{ num(data.profit.total) }}</span></td>
            <template v-if="compare">
              <td class="bg-surface-2 px-3 py-3 text-right tabular-nums text-muted"><span class="whitespace-nowrap">{{ num(data.profit.previous) }}</span></td>
              <td class="bg-surface-2 px-3 py-3 text-right"><DeltaBadge :value="delta(data.profit.total, data.profit.previous)" size="sm" /></td>
            </template>
          </tr>
          <tr class="margin">
            <th scope="row" class="sticky left-0 z-[1] bg-surface px-4 py-2.5 text-left text-sm text-muted">{{ t("finance.reports.margin") }}</th>
            <td v-for="(value, index) in data.margin.amounts" :key="index" class="px-3 py-2.5 text-right text-sm tabular-nums text-muted">{{ value === null ? "—" : fmt.percent(Number(value), 1) }}</td>
            <td class="px-3 py-2.5 text-right text-sm font-semibold tabular-nums text-fg">{{ data.margin.total === null ? "—" : fmt.percent(Number(data.margin.total), 1) }}</td>
            <template v-if="compare">
              <td class="px-3 py-2.5 text-right text-sm tabular-nums text-muted">{{ data.margin.previous === null ? "—" : fmt.percent(Number(data.margin.previous), 1) }}</td>
              <td />
            </template>
          </tr>
        </tbody>
      </table>
    </div>
    <p v-if="!data.income.nodes.length && !data.expense.nodes.length" class="px-4 py-10 text-center text-base text-muted">{{ t("finance.reports.pnlEmpty") }}</p>
  </div>
</template>

<style scoped>
.pnl tbody tr.parent > *,
.pnl tbody tr.child > * {
  border-top: 1px solid var(--c-border);
}
.pnl tbody tr.child > * {
  font-size: var(--text-sm);
}
</style>
