<script setup lang="ts">
/**
 * The Money tab: budget against actual (with where spending should be by now), spent, income,
 * money owed to us, labour cost (payroll.view) and margin, spending by month and by category, and
 * every ledger row linked to the project. "Add expense" books one through the finance ledger.
 */
import { Plus, ReceiptText, Wallet } from "@lucide/vue";
import { computed, defineAsyncComponent, ref } from "vue";
import { useI18n } from "vue-i18n";

import BulletBar from "@/components/BulletBar.vue";
import ChartCard from "@/components/ChartCard.vue";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import KpiStrip from "@/components/KpiStrip.vue";
import MoneyText from "@/components/MoneyText.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import UiButton from "@/components/UiButton.vue";
import { isNegative, isZero, subtract } from "@/lib/decimal";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { todayIn } from "@/lib/dates";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { useFinancials } from "../api";
import { daysBetween } from "../lib";
import type { ProjectDetail } from "../types";
import ExpenseDialog from "./ExpenseDialog.vue";

const BarChart = defineAsyncComponent(() => import("@/components/BarChart.vue"));
const DonutChart = defineAsyncComponent(() => import("@/components/DonutChart.vue"));

const props = defineProps<{ project: ProjectDetail }>();

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const query = useFinancials(() => props.project.id);
const skeleton = useDelayedPending(computed(() => query.isPending.value));
const adding = ref(false);
const money = computed(() => query.data.value);

/** Share of the project's time gone, for the "where it should be" mark on the budget bar. */
const expected = computed(() => {
  const { start_on: start, due_on: due } = props.project;
  if (!start || !due) return null;
  const total = daysBetween(start, due);
  if (total <= 0) return null;
  const gone = daysBetween(start, todayIn(company.timezone));
  return Math.max(0, Math.min(1, gone / total));
});

const kpis = computed(() => {
  const m = money.value;
  if (!m) return [];
  const items: Array<Record<string, unknown> & { id: string; label: string }> = [
    { id: "budget", label: t("projects.money.budget"), value: m.budget, format: "money", currency: m.currency, compact: true, hint: m.budget_currency !== m.currency && m.budget_original ? fmt.money(m.budget_original, m.budget_currency) : undefined },
    { id: "spent", label: t("projects.money.spent"), value: m.spent, format: "money", currency: m.currency, compact: true, hint: m.burn !== null ? t("projects.money.burn", { n: m.burn }) : undefined },
    { id: "income", label: t("projects.money.income"), value: m.income, format: "money", currency: m.currency, compact: true, hint: !isZero(m.receivable) ? t("projects.money.owed", { amount: fmt.money(m.receivable, m.currency, { compact: true }) }) : undefined },
  ];
  if ("labour_cost" in m) {
    items.push({ id: "labour", label: t("projects.money.labour"), value: m.labour_cost ?? null, format: "money", currency: m.currency, compact: true, hint: m.labour_cost === null ? t("projects.money.labourUnknown") : t("projects.money.labourHint") });
  }
  if (!isZero(m.income) || props.project.client) {
    items.push({ id: "margin", label: t("projects.money.margin"), value: m.margin, format: "money", currency: m.currency, compact: true, hint: m.margin_includes_labour ? t("projects.money.marginWithLabour") : t("projects.money.marginWithoutLabour") });
  } else if (m.remaining !== null) {
    items.push({ id: "remaining", label: t("projects.money.remaining"), value: m.remaining, format: "money", currency: m.currency, compact: true, hint: t("projects.money.remainingHint") });
  }
  return items;
});

const months = computed(() => (money.value?.by_month ?? []).map((row) => row.month));
const monthSeries = computed(() => [
  { name: t("projects.money.spent"), data: (money.value?.by_month ?? []).map((row) => row.spent) },
  { name: t("projects.money.income"), data: (money.value?.by_month ?? []).map((row) => row.income) },
]);
const slices = computed(() => (money.value?.by_category ?? []).map((row) => ({ name: row.name || t("projects.money.uncategorized"), value: row.amount })));
</script>

<template>
  <div class="flex flex-col gap-4">
    <div class="flex flex-wrap items-center gap-2">
      <p class="flex-1 text-sm text-muted">{{ t("projects.money.intro") }}</p>
      <UiButton v-if="project.capabilities.add_expense" variant="primary" :icon="Plus" @click="adding = true">{{ t("projects.money.add") }}</UiButton>
    </div>

    <div v-if="skeleton" class="flex flex-col gap-3">
      <SkeletonBlock height="96px" radius="12px" />
      <div class="grid gap-3 lg:grid-cols-2"><SkeletonBlock height="280px" radius="12px" /><SkeletonBlock height="280px" radius="12px" /></div>
    </div>
    <ErrorState v-else-if="query.isError.value" :error="query.error.value" :retry="() => query.refetch()" />
    <template v-else-if="money">
      <KpiStrip :items="kpis as never" phone="grid" />

      <section v-if="money.budget" class="ui-card flex flex-col gap-3 p-4 md:p-5">
        <div class="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <h3 class="text-sm font-semibold text-fg">{{ t("projects.money.budgetVsActual") }}</h3>
          <span class="flex-1" />
          <span v-if="money.remaining !== null" class="text-sm font-semibold" :class="isNegative(money.remaining) ? 'text-danger' : 'text-success'">
            {{ isNegative(money.remaining) ? t("projects.money.over", { amount: fmt.money(subtract("0", money.remaining), money.currency) }) : t("projects.money.left", { amount: fmt.money(money.remaining, money.currency) }) }}
          </span>
        </div>
        <BulletBar :value="money.spent" :target="money.budget" :expected="expected" value-format="money" :currency="money.currency" />
        <p v-if="expected !== null" class="text-xs text-muted">{{ t("projects.money.expectedHint", { n: Math.round(expected * 100) }) }}</p>
      </section>

      <!-- Charts once there is something to chart; before that the ledger's empty state invites the first expense. -->
      <div v-if="money.transactions.length" class="grid gap-3 lg:grid-cols-[3fr_2fr]">
        <ChartCard :title="t('projects.money.byMonth')" :empty="!months.length" :empty-text="t('projects.money.noRows')" height="260px">
          <BarChart :categories="months" :series="monthSeries" value-format="money" :currency="money.currency" x-format="month" height="260px" legend />
        </ChartCard>
        <ChartCard :title="t('projects.money.byCategory')" :empty="!slices.length" :empty-text="t('projects.money.noRows')" height="260px">
          <DonutChart :slices="slices" value-format="money" :currency="money.currency" height="260px" :center-label="t('projects.money.spent')" legend="bottom" />
        </ChartCard>
      </div>

      <section class="ui-card overflow-hidden">
        <header class="flex items-center gap-2 border-b border-line px-4 py-3">
          <ReceiptText :size="16" class="text-muted" />
          <h3 class="flex-1 text-sm font-semibold text-fg">{{ t("projects.money.transactions") }}</h3>
          <span class="text-xs text-muted">{{ t("projects.money.transactionsHint") }}</span>
        </header>
        <EmptyState v-if="!money.transactions.length" size="sm" :icon="Wallet" tone="neutral" :title="t('projects.money.noRowsTitle')" :description="t('projects.money.noRows')">
          <UiButton v-if="project.capabilities.add_expense" :icon="Plus" @click="adding = true">{{ t("projects.money.add") }}</UiButton>
        </EmptyState>
        <ul v-else class="divide-y divide-line">
          <li v-for="row in money.transactions" :key="row.id" class="flex items-center gap-3 px-4 py-3 text-sm" :class="row.status === 'void' && 'opacity-50'">
            <span class="w-20 shrink-0 tabular-nums text-muted">{{ fmt.day(row.occurred_on, "short") }}</span>
            <div class="min-w-0 flex-1">
              <p class="truncate font-medium text-fg" :class="row.status === 'void' && 'line-through'">{{ row.hidden ? t("projects.money.hidden") : row.description || row.category }}</p>
              <p class="truncate text-xs text-muted">{{ [row.category, row.account, row.counterparty].filter(Boolean).join(" · ") }}</p>
            </div>
            <span v-if="row.status === 'pending'" class="rounded-full bg-warning-soft px-2 py-0.5 text-[11px] font-semibold text-warning">{{ t("projects.money.pending") }}</span>
            <MoneyText :value="row.amount" :currency="row.currency" colored sign="always" class="font-semibold" />
          </li>
        </ul>
      </section>
    </template>
    <ExpenseDialog v-model:open="adding" :project="project" />
  </div>
</template>
