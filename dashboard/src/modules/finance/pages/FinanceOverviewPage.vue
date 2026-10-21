<script setup lang="ts">
/**
 * The finance front page (plan §6.2 "Finance › Overview"): cash now (in so‘m, dollars shown
 * apart), profit, income and expenses this month against the same days of last month, what is
 * owed both ways with the overdue part, the cash flow of the last weeks, the biggest expenses, what
 * falls due within 7 days, the accounts and the alerts that need someone (stale rate, money below
 * zero, entries waiting).
 */
import { AlarmClock, ArrowLeftRight, ArrowRight, ChartColumn, CircleAlert, HandCoins, Landmark, Plus, Scale, Wallet } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink } from "vue-router";

import BarChart from "@/components/BarChart.vue";
import ChartCard from "@/components/ChartCard.vue";
import DonutChart from "@/components/DonutChart.vue";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import KpiStrip from "@/components/KpiStrip.vue";
import MoneyText from "@/components/MoneyText.vue";
import PageHeader from "@/components/PageHeader.vue";
import ProgressBar from "@/components/ProgressBar.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import UiBadge from "@/components/UiBadge.vue";
import UiButton from "@/components/UiButton.vue";
import { addDays } from "@/lib/dates";
import { dec } from "@/lib/decimal";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { useCashFlow, useOverview } from "../api";
import { useCssColor } from "../colors";
import { ACCOUNT_ICONS, comparablePrevious, distinctColors, isNegative, isZeroMoney, share, topAccounts, trimLeadingEmpty } from "../lib";
import { openQuickAdd } from "../quickAdd";

const { t } = useI18n();
const css = useCssColor();
const fmt = useFormat();
const company = useCompanyStore();
const overview = useOverview();
const data = computed(() => overview.data.value);
const skeleton = useDelayedPending(computed(() => overview.isPending.value));
const base = computed(() => `/c/${company.currentId}/finance`);
const canRecord = computed(() => company.can("finance.record"));

// KPIs ------------------------------------------------------------------------------------

const foreign = computed(() => (data.value?.cash.by_currency ?? []).filter((row) => row.currency !== company.currency && !isZeroMoney(row.amount)));
const kpis = computed(() => {
  const d = data.value;
  const vs = t("finance.overview.vsLastMonth");
  // Nothing booked on the same days last month (a new company's first weeks): no comparison at
  // all, as the P&L drops an empty one, instead of three "—" badges.
  const lastMonth = d && !(isZeroMoney(d.month.previous.income) && isZeroMoney(d.month.previous.expense)) ? d.month.previous : null;
  // A profit that crossed zero against last month gets last month's figure, not a percentage.
  const profitBefore = lastMonth ? comparablePrevious(d?.month.profit, lastMonth.profit) : undefined;
  return [
    {
      id: "cash",
      label: t("finance.overview.cashNow"),
      value: d?.cash.total ?? null,
      format: "money" as const,
      compact: true,
      icon: Wallet,
      hint: foreign.value.length ? foreign.value.map((row) => fmt.money(row.amount, row.currency)).join(" · ") + ` ${t("finance.overview.included")}` : t("finance.overview.allAccounts"),
      to: `${base.value}/accounts`,
    },
    {
      id: "profit",
      label: t("finance.overview.profit"),
      value: d?.month.profit ?? null,
      previous: profitBefore,
      hint: lastMonth && profitBefore === undefined ? t("finance.overview.previousAmount", { amount: fmt.money(lastMonth.profit, undefined, { compact: true, sign: "always" }) }) : undefined,
      format: "money" as const,
      compact: true,
      icon: Scale,
      deltaLabel: vs,
      to: `${base.value}/reports/pnl`,
    },
    {
      id: "income",
      label: t("finance.overview.income"),
      value: d?.month.income ?? null,
      previous: lastMonth?.income,
      format: "money" as const,
      compact: true,
      icon: ChartColumn,
      deltaLabel: vs,
      // The P&L line, not "kind = income": refunds count against income here, so the list adds up
      // to this tile.
      to: { path: `${base.value}/transactions`, query: { pnl: "income", from: d?.month.from, to: d?.month.to } },
    },
    {
      id: "expense",
      // "… this month" like the profit and income tiles beside it (and the Overview widget).
      label: t("finance.overview.expensesMonth"),
      value: d?.month.expense ?? null,
      previous: lastMonth?.expense,
      format: "money" as const,
      compact: true,
      inverse: true,
      icon: Landmark,
      deltaLabel: vs,
      // Write-offs and exchange losses are expenses on the P&L too (see the income tile).
      to: { path: `${base.value}/transactions`, query: { pnl: "expense", from: d?.month.from, to: d?.month.to } },
    },
  ];
});

// Cash flow -------------------------------------------------------------------------------

const span = ref<"30" | "90" | "365">("90");
const flowParams = computed(() => {
  const today = data.value?.today;
  if (!today) return { preset: "last_30" };
  const days = Number(span.value);
  return { from: addDays(today, -(days - 1)), to: today, group: days <= 31 ? "day" : days <= 120 ? "week" : "month" };
});
const flow = useCashFlow(flowParams, computed(() => !!data.value));
// A ledger younger than the span starts where the money started, not with weeks of nothing.
const points = computed(() => trimLeadingEmpty(flow.data.value?.series ?? []));
const categories = computed(() => points.value.map((point) => point.date));
const flowSeries = computed(() => [
  { name: t("finance.overview.moneyIn"), data: points.value.map((p) => p.income), color: css("var(--c-success)") },
  { name: t("finance.overview.moneyOut"), data: points.value.map((p) => p.expense), color: css("var(--c-chart-1)") },
]);
const flowEmpty = computed(() => !!flow.data.value && flow.data.value.series.every((p) => isZeroMoney(p.income) && isZeroMoney(p.expense)));
const flowCsv = computed(() => ({
  filename: "cash-flow",
  columns: [
    { key: "date", label: t("finance.field.date") },
    { key: "income", label: t("finance.overview.moneyIn") },
    { key: "expense", label: t("finance.overview.moneyOut") },
    { key: "net", label: t("finance.tx.net") },
  ],
  rows: flow.data.value?.series ?? [],
}));

// Debts, top expenses, alerts -----------------------------------------------------------------

// Every expense group of the month: the donut folds the small ones into "Other", and its middle
// shows the month's expenses, the same figure as the Expenses tile above.
// Categories share eight palette colours, so slices get distinct ones (the biggest keep theirs).
const slices = computed(() => {
  const rows = data.value?.top_expenses ?? [];
  const colors = distinctColors(rows);
  return rows.map((row, index) => ({ name: row.name, value: row.amount, color: css(colors[index]!) }));
});
const slicesTotal = computed(() => {
  const total = data.value?.month.expense ?? slices.value.reduce((sum, slice) => sum.plus(slice.value), dec(0)).toString();
  return fmt.money(total, undefined, { compact: true, currencyDisplay: "none" });
});
const alerts = computed(() => {
  const d = data.value;
  if (!d) return [];
  const list: Array<{ id: string; tone: "warning" | "danger" | "info"; title: string; body: string; to?: string; action?: string }> = [];
  if (d.rate.stale) {
    list.push({
      id: "rate",
      tone: "warning",
      title: t("finance.overview.alertRate"),
      body: d.rate.rate ? t("finance.overview.alertRateBody", { rate: fmt.number(d.rate.rate, 2), date: d.rate.date ? fmt.day(d.rate.date, "short") : "—" }) : t("finance.overview.alertNoRate"),
      to: `${base.value}/settings/rates`,
      action: t("finance.overview.alertRateAction"),
    });
  }
  for (const account of d.negative_accounts) {
    list.push({ id: `neg-${account.id}`, tone: "danger", title: t("finance.overview.alertNegative", { account: account.name }), body: t("finance.overview.alertNegativeBody", { amount: fmt.money(account.balance, account.currency) }), to: `${base.value}/accounts/${account.id}` });
  }
  if (d.pending.count) {
    list.push({ id: "pending", tone: "info", title: t("finance.overview.alertPending", { n: d.pending.count }, d.pending.count), body: t("finance.overview.alertPendingBody", { amount: fmt.money(d.pending.total) }), to: `${base.value}/transactions?status=pending&view=pending`, action: t("finance.overview.review") });
  }
  if (d.payable.overdue_count) {
    list.push({ id: "payable", tone: "danger", title: t("finance.overview.alertPayable", { n: d.payable.overdue_count }, d.payable.overdue_count), body: t("finance.overview.alertPayableBody", { amount: fmt.money(d.payable.overdue) }), to: `${base.value}/debts?direction=payable&overdue=true` });
  }
  return list;
});
const firstRun = computed(() => !!data.value && !data.value.has_ledger);
</script>

<template>
  <div>
    <PageHeader :title="t('finance.title')" :description="data ? t('finance.overview.description', { date: fmt.day(data.today, 'weekday') }) : t('finance.overview.descriptionShort')">
      <template #actions>
        <UiButton :to="`${base}/reports/pnl`" variant="ghost" :icon="ChartColumn">{{ t("finance.nav.reports") }}</UiButton>
        <UiButton v-if="canRecord" variant="secondary" :icon="ArrowLeftRight" @click="openQuickAdd('transfer')">{{ t("finance.cmd.transferShort") }}</UiButton>
        <UiButton v-if="canRecord" variant="primary" :icon="Plus" kbd="N" @click="openQuickAdd('expense')">{{ t("finance.cmd.record") }}</UiButton>
      </template>
    </PageHeader>

    <ErrorState v-if="overview.isError.value" :error="overview.error.value" :retry="() => overview.refetch()" />

    <div v-else class="flex flex-col gap-4">
      <div v-if="firstRun" class="ui-card">
        <EmptyState :icon="Landmark" size="lg" :title="t('finance.overview.firstTitle')" :description="t('finance.overview.firstBody')">
          <div class="flex flex-wrap justify-center gap-2">
            <UiButton variant="primary" :to="`${base}/accounts?setup=opening`">{{ t("finance.overview.firstAction") }}</UiButton>
            <UiButton v-if="canRecord" variant="secondary" @click="openQuickAdd('expense')">{{ t("finance.cmd.record") }}</UiButton>
          </div>
        </EmptyState>
      </div>

      <template v-if="!firstRun">
        <!-- Two to a row; an odd last one takes the whole row instead of leaving half of it empty. -->
        <div v-if="alerts.length" class="grid grid-cols-1 gap-2 lg:grid-cols-2">
          <InlineAlert v-for="(alert, index) in alerts" :key="alert.id" :class="index === alerts.length - 1 && alerts.length % 2 === 1 && 'lg:col-span-2'" :tone="alert.tone" size="sm" :title="alert.title" :description="alert.body">
            <template v-if="alert.to" #actions>
              <UiButton :to="alert.to" size="sm" variant="ghost" :icon-right="ArrowRight">{{ alert.action ?? t("finance.overview.open") }}</UiButton>
            </template>
          </InlineAlert>
        </div>

        <KpiStrip :items="kpis" :loading="overview.isPending.value" :columns="4" />

        <div class="grid grid-cols-1 gap-4 xl:grid-cols-3">
          <ChartCard
            class="xl:col-span-2"
            :title="t('finance.overview.cashFlow')"
            :subtitle="flow.data.value ? t('finance.overview.cashFlowNet', { net: fmt.money(flow.data.value.totals.net, undefined, { sign: 'always', compact: true }) }) : undefined"
            :loading="flow.isPending.value"
            :error="flow.error.value"
            :retry="() => flow.refetch()"
            :empty="flowEmpty"
            :empty-text="t('finance.overview.cashFlowEmpty')"
            :csv="flowCsv as never"
            height="260px"
          >
            <template #actions>
              <SegmentedControl
                v-model="span"
                size="sm"
                :options="[
                  { value: '30', label: t('finance.overview.days', { n: 30 }) },
                  { value: '90', label: t('finance.overview.days', { n: 90 }) },
                  { value: '365', label: t('finance.overview.year') },
                ]"
              />
            </template>
            <BarChart :categories="categories" :series="flowSeries" value-format="money" :x-format="span === '365' ? 'month' : 'day'" height="260px" legend />
          </ChartCard>

          <section class="ui-card flex flex-col p-4" :aria-label="t('finance.overview.owed')">
            <header class="mb-3 flex items-center gap-2">
              <HandCoins :size="16" class="text-subtle" />
              <h3 class="flex-1 text-sm font-semibold text-fg">{{ t("finance.overview.owed") }}</h3>
              <RouterLink :to="`${base}/debts`" class="inline-flex items-center gap-1 rounded-[6px] px-1.5 py-0.5 text-sm font-semibold text-muted hover:bg-highlight hover:text-fg">
                {{ t("common.viewAll") }}<ArrowRight :size="14" />
              </RouterLink>
            </header>
            <template v-if="skeleton">
              <SkeletonBlock v-for="n in 2" :key="n" height="64px" class="mb-3" />
            </template>
            <template v-else-if="data">
              <RouterLink
                v-for="side in (['receivable', 'payable'] as const)"
                :key="side"
                :to="{ path: `${base}/debts`, query: { direction: side } }"
                class="group mb-2 rounded-[10px] border border-line p-3 transition-colors hover:border-line-strong hover:bg-surface-2/50"
              >
                <div class="flex items-baseline justify-between gap-2">
                  <span class="text-sm font-medium text-muted">{{ t(`finance.debts.side.${side}`) }}</span>
                  <span class="text-xs text-subtle">{{ t("finance.overview.debtCount", { n: data[side].count }, data[side].count) }}</span>
                </div>
                <p class="mt-0.5 text-xl font-semibold tabular-nums text-fg"><MoneyText :value="data[side].total" compact /></p>
                <ProgressBar class="mt-2" size="sm" :value="share(data[side].overdue, data[side].total)" :max="100" :tone="side === 'payable' ? 'danger' : 'warning'" />
                <p class="mt-1.5 text-xs" :class="isZeroMoney(data[side].overdue) ? 'text-subtle' : side === 'payable' ? 'text-danger' : 'text-warning'">
                  <template v-if="isZeroMoney(data[side].overdue)">{{ t("finance.overview.nothingOverdue") }}</template>
                  <template v-else>{{ t("finance.overview.overdue", { amount: fmt.money(data[side].overdue, undefined, { compact: true }) }) }}</template>
                </p>
              </RouterLink>
            </template>
          </section>
        </div>

        <div class="grid grid-cols-1 gap-4 lg:grid-cols-2 xl:grid-cols-3">
          <ChartCard :title="t('finance.overview.topExpenses')" :subtitle="t('finance.overview.thisMonth')" :loading="overview.isPending.value" :empty="!slices.length" :empty-text="t('finance.overview.noExpenses')" height="220px">
            <DonutChart :slices="slices" :value-format="(value: number) => fmt.money(value, undefined, { compact: true })" :center-label="t('finance.overview.expenses')" :center-value="slicesTotal" height="180px" legend="bottom" :max-slices="5" />
          </ChartCard>

          <section class="ui-card flex flex-col p-4" :aria-label="t('finance.overview.dueSoon')">
            <header class="mb-2 flex items-center gap-2">
              <AlarmClock :size="16" class="text-subtle" />
              <h3 class="flex-1 text-sm font-semibold text-fg">{{ t("finance.overview.dueSoon") }}</h3>
              <UiBadge v-if="data?.due_soon.length" :count="data.due_soon.length" tone="primary" />
            </header>
            <div v-if="skeleton" class="flex flex-col gap-2"><SkeletonBlock v-for="n in 4" :key="n" height="40px" /></div>
            <EmptyState v-else-if="data && !data.due_soon.length" size="sm" tone="success" :title="t('finance.overview.nothingDue')" :description="t('finance.overview.nothingDueBody')" />
            <ul v-else-if="data" class="-mx-2 flex flex-col">
              <li v-for="debt in data.due_soon" :key="debt.id">
                <RouterLink :to="{ path: `${base}/debts`, query: { direction: debt.direction, debt: String(debt.id) } }" class="flex items-center gap-3 rounded-[10px] px-2 py-2 hover:bg-highlight">
                  <span :class="['grid size-8 shrink-0 place-items-center rounded-[9px] text-xs font-bold', debt.direction === 'receivable' ? 'bg-success-soft text-success' : 'bg-danger-soft text-danger']" aria-hidden="true">
                    {{ debt.direction === "receivable" ? "+" : "−" }}
                  </span>
                  <div class="min-w-0 flex-1">
                    <p class="truncate text-sm font-semibold text-fg" :title="debt.party?.name">{{ debt.party?.name ?? t("finance.debts.hidden") }}</p>
                    <p class="truncate text-xs text-muted">{{ debt.due_on ? fmt.day(debt.due_on, "weekdayShort") : "" }} · {{ t(`finance.debtKind.${debt.kind}`) }}</p>
                  </div>
                  <span class="shrink-0 text-sm font-semibold tabular-nums text-fg"><MoneyText :value="debt.outstanding" :currency="debt.currency" compact /></span>
                </RouterLink>
              </li>
            </ul>
          </section>

          <section class="ui-card flex flex-col p-4 lg:col-span-2 xl:col-span-1" :aria-label="t('finance.nav.accounts')">
            <header class="mb-2 flex items-center gap-2">
              <Wallet :size="16" class="text-subtle" />
              <h3 class="flex-1 text-sm font-semibold text-fg">{{ t("finance.nav.accounts") }}</h3>
              <RouterLink :to="`${base}/accounts`" class="inline-flex items-center gap-1 rounded-[6px] px-1.5 py-0.5 text-sm font-semibold text-muted hover:bg-highlight hover:text-fg">
                {{ t("common.viewAll") }}<ArrowRight :size="14" />
              </RouterLink>
            </header>
            <div v-if="skeleton" class="flex flex-col gap-2"><SkeletonBlock v-for="n in 5" :key="n" height="32px" /></div>
            <ul v-else-if="data" class="-mx-2 flex flex-col">
              <li v-for="account in topAccounts(data.cash.accounts, 7)" :key="account.id">
                <RouterLink :to="`${base}/accounts/${account.id}`" class="flex items-center gap-3 rounded-[10px] px-2 py-1.5 hover:bg-highlight">
                  <component :is="ACCOUNT_ICONS[account.kind]" :size="16" class="shrink-0 text-subtle" aria-hidden="true" />
                  <span class="min-w-0 flex-1 truncate text-sm text-fg" :title="account.name">{{ account.name }}</span>
                  <span :class="['shrink-0 text-sm font-semibold tabular-nums', isNegative(account.balance) ? 'text-danger' : 'text-fg']">
                    <MoneyText :value="account.balance" :currency="account.currency" :compact="account.currency === company.currency" />
                  </span>
                </RouterLink>
              </li>
            </ul>
            <p v-if="data && data.cash.rate.rate" class="mt-auto flex items-center gap-1.5 border-t border-line pt-2.5 text-xs text-muted">
              <CircleAlert v-if="data.cash.rate.stale" :size="13" class="text-warning" />
              {{ t("finance.overview.rateLine", { rate: fmt.number(data.cash.rate.rate, 2) }) }}
              <span v-if="data.cash.rate.stale" class="text-warning">· {{ t("finance.rates.staleShort") }}</span>
            </p>
          </section>
        </div>
      </template>
    </div>
  </div>
</template>
