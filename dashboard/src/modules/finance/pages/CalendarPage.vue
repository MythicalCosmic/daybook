<script setup lang="ts">
/**
 * The payments calendar (plan §1.6 "upcoming payments calendar (bills, payables, receivables,
 * invoices, payroll)" and "forecast"; §6.2 "forecast chart with its low point"): the cash forecast
 * for 30, 60 or 90 days with its headline ("Cash drops below zero on 25 Nov", else its lowest
 * point), then everything due in the same days, overdue first and then day by day, money in and
 * out apart. Each item opens where it is dealt with: a bill or a tax is paid right here, a payable
 * on the Payables page, a receivable in its debt, payroll where the server points.
 */
import { ArrowRight, CalendarClock, ChartSpline, HandCoins, Landmark, ReceiptText, Repeat, TrendingDown, TrendingUp, Users, Wallet } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink, useRouter } from "vue-router";

import AreaChart from "@/components/AreaChart.vue";
import ChartCard from "@/components/ChartCard.vue";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import KpiStrip from "@/components/KpiStrip.vue";
import MoneyText from "@/components/MoneyText.vue";
import PageHeader from "@/components/PageHeader.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import { addDays, diffDays } from "@/lib/dates";
import { isNegative } from "@/lib/decimal";
import { useFormat } from "@/lib/useFormat";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useCompanyId, useCompanyStore } from "@/stores/company";

import { useForecast, useRecurring, useUpcoming } from "../api";
import { useCssColor } from "../colors";
import RulePayDialog from "../components/RulePayDialog.vue";
import { forecastHeadline, groupUpcoming, isZeroMoney, upcomingTarget, type UpcomingGroup } from "../lib";
import type { RecurringRule, UpcomingItem, UpcomingKind } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const css = useCssColor();
const router = useRouter();
const company = useCompanyStore();
const cid = useCompanyId();
const base = computed(() => `/c/${cid.value}/finance`);
const canPay = computed(() => company.can("finance.record"));

const span = useRouteState("days", rs.enum(["30", "60", "90"] as const, "30"));
const days = computed(() => Number(span.value));
const forecast = useForecast(days);
const upcoming = useUpcoming(days);
// The rules behind the bills, for paying one in place (only for someone who may pay).
const rules = useRecurring({ active: "true" }, canPay);

// Forecast ---------------------------------------------------------------------------------

const data = computed(() => forecast.data.value ?? null);
const headline = computed(() => (data.value ? forecastHeadline(data.value) : null));
const below = computed(() => headline.value?.kind === "below");
const categories = computed(() => (data.value?.points ?? []).map((point) => point.date));
const series = computed(() => [
  { name: t("finance.calendar.cash"), data: (data.value?.points ?? []).map((point) => point.balance), color: css(below.value ? "var(--c-danger)" : "var(--c-chart-2)") },
]);
const csv = computed(() => ({
  filename: "cash-forecast",
  columns: [
    { key: "date", label: t("finance.field.date") },
    { key: "balance", label: t("finance.calendar.cash") },
    { key: "in", label: t("finance.tx.moneyIn") },
    { key: "out", label: t("finance.tx.moneyOut") },
  ],
  rows: data.value?.points ?? [],
}));
const basisLine = computed(() => {
  const basis = data.value?.basis;
  if (!basis) return undefined;
  if (!basis.days_observed) return t("finance.calendar.basisNone");
  return t("finance.calendar.basis", {
    n: basis.days_observed,
    in: fmt.money(basis.daily_in, undefined, { compact: true }),
    out: fmt.money(basis.daily_out, undefined, { compact: true }),
  });
});
const kpis = computed(() => {
  const d = data.value;
  const totals = upcoming.data.value?.totals;
  return [
    { id: "now", label: t("finance.overview.cashNow"), value: d?.start ?? null, format: "money" as const, compact: true, icon: Wallet },
    {
      id: "low",
      label: t("finance.calendar.lowest"),
      value: d?.low.balance ?? null,
      format: "money" as const,
      compact: true,
      icon: TrendingDown,
      hint: d ? fmt.day(d.low.date, "weekdayShort") : undefined,
    },
    { id: "end", label: t("finance.calendar.inDays", { n: days.value }), value: d?.end ?? null, format: "money" as const, compact: true, icon: ChartSpline, hint: d ? fmt.day(addDays(d.today, days.value), "weekdayShort") : undefined },
    {
      id: "out",
      label: t("finance.calendar.dueOut"),
      value: totals?.out ?? null,
      format: "money" as const,
      compact: true,
      icon: CalendarClock,
      hint: totals && !isZeroMoney(totals.overdue_out) ? t("finance.calendar.overduePart", { amount: fmt.money(totals.overdue_out, undefined, { compact: true }) }) : undefined,
    },
  ];
});

// Upcoming ---------------------------------------------------------------------------------

const list = computed(() => upcoming.data.value ?? null);
const groups = computed(() => (list.value ? groupUpcoming(list.value.items, list.value.currency) : []));
const today = computed(() => list.value?.today ?? data.value?.today ?? "");

function groupLabel(group: UpcomingGroup): string {
  if (!group.day) return t("finance.calendar.overdue");
  if (group.day === today.value) return t("common.today");
  if (today.value && group.day === addDays(today.value, 1)) return t("finance.calendar.tomorrow");
  return fmt.day(group.day, "weekday");
}

const KIND_ICONS: Record<UpcomingKind, typeof Wallet> = { bill: ReceiptText, auto: Repeat, tax: Landmark, payable: HandCoins, receivable: HandCoins, payroll: Users };

function late(item: UpcomingItem): number {
  return today.value ? Math.max(0, diffDays(item.date, today.value)) : 0;
}

const paying = ref<RecurringRule | null>(null);
const payOpen = ref(false);

/** A bill opens its payment here; when its rule isn't in hand, the recurring page opens it. */
function payRule(ruleId: number): void {
  const rule = rules.data.value?.find((row) => row.id === ruleId);
  if (!rule) {
    void router.push(`${base.value}/recurring?rule=${ruleId}`);
    return;
  }
  paying.value = rule;
  payOpen.value = true;
}
const target = (item: UpcomingItem) => upcomingTarget(item, base.value, canPay.value);
const actionLabel = (item: UpcomingItem) => {
  const where = target(item);
  if (where.type === "pay") return item.direction === "in" ? t("finance.recurring.markReceived") : t("finance.recurring.pay");
  return t("finance.overview.open");
};
</script>

<template>
  <div>
    <PageHeader :title="t('finance.nav.calendar')" :description="t('finance.calendar.description')">
      <template #actions>
        <SegmentedControl
          v-model="span"
          :aria-label="t('finance.calendar.span')"
          :options="[
            { value: '30', label: t('finance.overview.days', { n: 30 }) },
            { value: '60', label: t('finance.overview.days', { n: 60 }) },
            { value: '90', label: t('finance.overview.days', { n: 90 }) },
          ]"
        />
      </template>
    </PageHeader>

    <div class="flex flex-col gap-4">
      <!-- The forecast's answer first: when cash runs out, or how low it gets (a failure shows once, in the chart's card). -->
      <SkeletonBlock v-if="forecast.isPending.value" height="64px" radius="12px" />
      <InlineAlert
        v-else-if="headline && below"
        tone="danger"
        :icon="TrendingDown"
        :title="t('finance.calendar.belowZero', { date: fmt.day(headline.date, 'weekday') })"
        :description="t('finance.calendar.belowZeroBody', { amount: fmt.money(data!.low.balance, undefined, { compact: true }), date: fmt.day(data!.low.date, 'short') })"
        data-headline="below"
      />
      <InlineAlert
        v-else-if="headline"
        :tone="isNegative(headline.balance) ? 'danger' : 'success'"
        :icon="TrendingUp"
        :title="t('finance.calendar.lowPoint', { amount: fmt.money(headline.balance, undefined, { compact: true }), date: fmt.day(headline.date, 'short') })"
        :description="t('finance.calendar.lowPointBody', { n: days })"
        data-headline="low"
      />

      <KpiStrip :items="kpis" :loading="forecast.isPending.value" :columns="4" phone="grid" />

      <ChartCard
        :title="t('finance.calendar.forecast')"
        :subtitle="basisLine"
        :loading="forecast.isPending.value"
        :error="forecast.error.value"
        :retry="() => forecast.refetch()"
        :empty="!!data && !data.points.length"
        :empty-text="t('finance.calendar.forecastEmpty')"
        :csv="csv as never"
        height="260px"
      >
        <AreaChart :categories="categories" :series="series" value-format="money" x-format="day" height="260px" :target="below ? { value: 0 } : null" :label="t('finance.calendar.forecast')" />
      </ChartCard>

      <section class="ui-card flex flex-col" :aria-label="t('finance.calendar.upcoming')" data-upcoming>
        <header class="flex flex-wrap items-center gap-x-4 gap-y-1 border-b border-line px-4 py-3">
          <CalendarClock :size="16" class="text-subtle" aria-hidden="true" />
          <h3 class="flex-1 text-sm font-semibold text-fg">{{ t("finance.calendar.upcoming") }}</h3>
          <template v-if="list">
            <span class="text-sm text-muted">{{ t("finance.calendar.totalOut") }} <span class="font-semibold tabular-nums text-fg"><MoneyText :value="list.totals.out" decimals="never" compact /></span></span>
            <span class="text-sm text-muted">{{ t("finance.calendar.totalIn") }} <span class="font-semibold tabular-nums text-success"><MoneyText :value="list.totals.in" decimals="never" compact /></span></span>
          </template>
        </header>

        <div v-if="upcoming.isPending.value" class="flex flex-col gap-2 p-4"><SkeletonBlock v-for="n in 5" :key="n" height="44px" /></div>
        <ErrorState v-else-if="upcoming.isError.value" class="m-4" compact :error="upcoming.error.value" :retry="() => upcoming.refetch()" />
        <EmptyState v-else-if="list && !list.items.length" size="sm" tone="success" :title="t('finance.calendar.nothingDue', { n: days })" :description="t('finance.calendar.nothingDueBody')" />
        <template v-else-if="list">
          <div v-for="group in groups" :key="group.key" :data-group="group.key">
            <div :class="['flex items-center gap-3 border-b border-line px-4 py-2 text-xs font-semibold', group.day ? 'bg-surface-2/50 text-muted dark:bg-surface-3/40' : 'bg-danger-soft/60 text-danger']">
              <span class="flex-1">{{ groupLabel(group) }}</span>
              <span v-if="!isZeroMoney(group.out)" class="tabular-nums">−<MoneyText :value="group.out" decimals="never" compact /></span>
              <span v-if="!isZeroMoney(group.in)" class="tabular-nums text-success">+<MoneyText :value="group.in" decimals="never" compact /></span>
            </div>
            <ul class="flex flex-col divide-y divide-line">
              <li v-for="item in group.items" :key="item.key" :data-item="item.key">
                <component
                  :is="target(item).type === 'link' ? RouterLink : 'button'"
                  v-bind="target(item).type === 'link' ? { to: (target(item) as { to: string }).to } : { type: 'button', disabled: target(item).type === 'none' }"
                  class="group flex w-full items-center gap-3 px-4 py-2.5 text-left transition-colors hover:bg-highlight disabled:cursor-default disabled:hover:bg-transparent"
                  @click="target(item).type === 'pay' && payRule((target(item) as { ruleId: number }).ruleId)"
                >
                  <span :class="['grid size-8 shrink-0 place-items-center rounded-[9px]', item.direction === 'in' ? 'bg-success-soft text-success' : 'bg-danger-soft text-danger']" aria-hidden="true">
                    <component :is="KIND_ICONS[item.kind] ?? Wallet" :size="15" />
                  </span>
                  <div class="min-w-0 flex-1">
                    <p class="truncate text-sm font-semibold text-fg" :title="item.title">{{ item.title }}</p>
                    <p class="truncate text-xs text-muted">
                      {{ t(`finance.calendar.kind.${item.kind}`) }}<template v-if="item.subtitle"> · {{ item.subtitle }}</template>
                      <template v-if="item.overdue"> · <span class="font-semibold text-danger">{{ fmt.day(item.date, "short") }}, {{ t("finance.debts.late", { n: late(item) }, late(item)) }}</span></template>
                    </p>
                  </div>
                  <span class="shrink-0 text-right">
                    <span v-if="item.amount === null" class="text-sm text-muted">{{ t("finance.calendar.unknownAmount") }}</span>
                    <span v-else :class="['text-sm font-semibold tabular-nums', item.direction === 'in' ? 'text-success' : 'text-fg']" :title="item.estimate ? t('finance.calendar.estimate') : undefined">
                      {{ item.direction === "in" ? "+" : "−" }}<template v-if="item.estimate">≈ </template><MoneyText :value="item.amount" :currency="item.currency" decimals="never" />
                    </span>
                  </span>
                  <span v-if="target(item).type !== 'none'" class="hidden shrink-0 items-center gap-1 text-xs font-semibold text-muted group-hover:text-fg sm:inline-flex">
                    {{ actionLabel(item) }}<ArrowRight :size="13" aria-hidden="true" />
                  </span>
                </component>
              </li>
            </ul>
          </div>
        </template>
      </section>
    </div>

    <RulePayDialog v-if="paying" v-model:open="payOpen" :rule="paying" />
  </div>
</template>
