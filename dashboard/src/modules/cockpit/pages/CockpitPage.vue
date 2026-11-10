<script setup lang="ts">
/**
 * Egasi paneli, the owner's morning page (`GET cockpit/`, one call): the headline numbers
 * (profit, cash now, how long cash lasts, what waits), real profit by pharmacy ranked with each
 * one's state and trend, the 90-day cash line with its low point and what causes it, the
 * decisions waiting with one-tap answers, and the insights with Got it, Make it a task and
 * Dismiss. Money shows only to those who may see finance; the rest still get their decisions.
 *
 * Phones first: decisions and insights come before the branches and the chart; on a wide screen
 * money takes the left column and what needs the owner the right one.
 */
import { CalendarClock, Gavel, Hourglass, RefreshCw, TrendingUp, Wallet } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink, useRoute } from "vue-router";

import ErrorState from "@/components/ErrorState.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import KpiStrip from "@/components/KpiStrip.vue";
import MoneyText from "@/components/MoneyText.vue";
import PageHeader from "@/components/PageHeader.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import UiButton from "@/components/UiButton.vue";
import { toast } from "@/components/useToast";
import { compare } from "@/lib/decimal";
import { dayPart } from "@/lib/dates";
import { useFormat } from "@/lib/useFormat";
import { useNow } from "@/lib/useNow";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useCompanyStore } from "@/stores/company";
import { useSessionStore } from "@/stores/session";

import { useCheckNow, useCockpit, type PeriodKey } from "../api";
import BranchCard from "../components/BranchCard.vue";
import DecisionList from "../components/DecisionList.vue";
import InsightList from "../components/InsightList.vue";
import RunwayChart from "../components/RunwayChart.vue";
import { lowKind, rankBranches, topCosts } from "../lib";

const { t } = useI18n();
const fmt = useFormat();
const route = useRoute();
const company = useCompanyStore();
const session = useSessionStore();
const now = useNow();

const cockpit = useCockpit();
const data = computed(() => cockpit.data.value ?? null);
const money = computed(() => data.value?.money ?? null);
const cash = computed(() => data.value?.cash ?? null);
const financeOff = computed(() => !company.enabled("finance"));

const period = useRouteState("period", rs.enum(["month", "last_month"] as const, "month"));
const key = computed<PeriodKey>(() => period.value);

const greeting = computed(() =>
  t(`cockpit.greeting.${dayPart(company.timezone, now.value)}`, { name: session.me?.user.first_name || session.me?.user.full_name || "" }),
);
const subtitle = computed(() => {
  const parts = [data.value ? fmt.day(data.value.today, "weekday") : "", company.current?.name ?? ""];
  if (data.value) parts.push(t("cockpit.updated", { time: fmt.instant(data.value.generated_at, "time") }));
  return parts.filter(Boolean).join(" · ");
});

const total = computed(() => money.value?.total[key.value] ?? null);
const branches = computed(() => (money.value ? rankBranches(money.value.branches, key.value) : []));
const range = computed(() => {
  const span = money.value?.periods[key.value];
  if (!span) return "";
  if (key.value === "month") return t("cockpit.period.monthRange", { from: fmt.day(span.from, "short"), to: fmt.day(span.to, "short") });
  return t("cockpit.period.lastMonthRange", { month: fmt.day(span.from, "monthYear") });
});
const missing = computed(() => (key.value === "month" ? (money.value?.total.month.missing ?? []) : []));
const missingText = computed(() =>
  missing.value.map((item) => t("cockpit.branches.missingItem", { name: item.name, amount: fmt.money(item.last_month, undefined, { compact: true }) })).join(", "),
);
const unassigned = computed(() => money.value?.unassigned?.[key.value] ?? null);
const unassignedCosts = computed(() => (unassigned.value ? unassigned.value.costs.filter((cost) => compare(cost.amount, 0) > 0).slice(0, 3) : []));
const totalCosts = computed(() => (total.value ? topCosts(total.value, 4) : []));

const runwayValue = computed(() => cash.value?.runway.days ?? null);
const kpis = computed(() => {
  const items = [];
  if (total.value) {
    items.push({
      id: "profit",
      label: t("cockpit.kpi.profit"),
      value: total.value.profit,
      previous: total.value.previous?.profit ?? null,
      format: "money" as const,
      compact: true,
      icon: TrendingUp,
      deltaLabel: key.value === "month" ? t("cockpit.kpi.vsSameDays") : t("cockpit.kpi.vsMonthBefore"),
      hint: total.value.margin !== null ? t("cockpit.kpi.margin", { margin: fmt.percent(Number(total.value.margin), 1) }) : undefined,
      spark: money.value?.total.trend.map((point) => point.profit),
      sparkColor: "var(--c-chart-1)",
    });
  }
  if (cash.value) {
    items.push({
      id: "cash",
      label: t("cockpit.kpi.cash"),
      value: cash.value.now,
      format: "money" as const,
      compact: true,
      icon: Wallet,
      hint: t("cockpit.kpi.cashLow", { amount: fmt.money(cash.value.low.balance, undefined, { compact: true }), date: fmt.day(cash.value.low.date, "short") }),
      spark: cash.value.points.filter((_, index) => index % 3 === 0).map((point) => point.balance),
      sparkColor: lowKind(cash.value) === "fine" ? "var(--c-chart-2)" : lowKind(cash.value) === "short" ? "var(--c-danger)" : "var(--c-warning)",
    });
    const runway = cash.value.runway;
    items.push({
      id: "runway",
      label: t("cockpit.kpi.runway"),
      value: runwayValue.value,
      format: (value: number) => t("cockpit.kpi.runwayDays", { n: fmt.number(value) }, Math.round(value)),
      icon: Hourglass,
      hint:
        runway.days === null
          ? t("cockpit.kpi.runwayNone")
          : runway.basis === "forecast" && runway.below_zero_on
            ? t("cockpit.kpi.runwayForecast", { date: fmt.day(runway.below_zero_on, "short") })
            : t("cockpit.kpi.runwaySpending", { amount: fmt.money(cash.value.daily_spend, undefined, { compact: true }) }),
    });
  }
  const waiting = data.value?.decisions.total ?? 0;
  items.push({
    id: "decisions",
    label: t("cockpit.kpi.decisions"),
    value: waiting,
    icon: Gavel,
    hint: waiting ? t("cockpit.kpi.decisionsHint", { n: waiting }, waiting) : t("cockpit.kpi.decisionsNone"),
  });
  return items;
});

const focus = computed(() => {
  const raw = Number(Array.isArray(route.query.insight) ? route.query.insight[0] : route.query.insight);
  return Number.isFinite(raw) && raw > 0 ? raw : null;
});
const lowLine = computed(() => {
  const c = cash.value;
  if (!c) return "";
  const date = fmt.day(c.low.date, "weekday");
  const amount = fmt.money(c.low.balance, undefined, { compact: true });
  switch (lowKind(c)) {
    case "short":
      return t("cockpit.cash.short", { date, amount: fmt.money(c.low.short_by, undefined, { compact: true }) });
    case "under":
      return t("cockpit.cash.under", { date, amount, gap: fmt.money(c.low.under_buffer_by, undefined, { compact: true }) });
    default:
      return t("cockpit.cash.fine", { date, amount });
  }
});
const lowTone = computed(() => (cash.value ? { short: "danger", under: "warning", fine: "success" }[lowKind(cash.value)] : "neutral") as "danger" | "warning" | "success");
const bufferLine = computed(() => {
  const c = cash.value;
  if (!c) return "";
  const amount = fmt.money(c.buffer, undefined, { compact: true });
  return c.buffer_source === "setting" ? t("cockpit.cash.buffer", { amount }) : t("cockpit.cash.bufferUsual", { amount });
});

const check = useCheckNow();
async function checkNow(): Promise<void> {
  try {
    const result = await check.mutateAsync();
    const fresh = (result.created ?? 0) + (result.reopened ?? 0);
    toast.success(fresh ? t("cockpit.checked", { n: fresh }, fresh) : t("cockpit.checkedNothing"));
  } catch {
    // The HTTP layer said why (for one: checked a minute ago).
  }
}
const financePath = computed(() => `/c/${company.currentId}/finance`);
</script>

<template>
  <div class="flex flex-col gap-4">
    <PageHeader :title="greeting" :description="subtitle">
      <template #actions>
        <SegmentedControl
          v-if="money"
          v-model="period"
          size="sm"
          :aria-label="t('cockpit.period.label')"
          :options="[
            { value: 'month', label: t('cockpit.period.month') },
            { value: 'last_month', label: t('cockpit.period.lastMonth') },
          ]"
        />
        <UiButton v-if="data?.can.settings" variant="ghost" size="sm" :icon="RefreshCw" :loading="check.isPending.value" data-check @click="checkNow">{{ t("cockpit.checkNow") }}</UiButton>
      </template>
    </PageHeader>

    <!-- First load: the page's own shape, so nothing jumps when it arrives. -->
    <template v-if="cockpit.isPending.value">
      <SkeletonBlock height="112px" radius="14px" />
      <div class="grid gap-4 lg:grid-cols-[minmax(0,1fr)_380px]">
        <div class="grid gap-4 sm:grid-cols-2"><SkeletonBlock v-for="n in 2" :key="n" height="300px" radius="14px" /></div>
        <SkeletonBlock height="300px" radius="14px" />
      </div>
    </template>
    <ErrorState v-else-if="cockpit.isError.value" class="ui-card" :title="t('cockpit.error')" :error="cockpit.error.value" :retry="() => cockpit.refetch()" />

    <template v-else-if="data">
      <KpiStrip :items="kpis" :columns="kpis.length > 3 ? 4 : kpis.length === 3 ? 3 : 2" phone="grid" data-headline />

      <InlineAlert v-if="!data.can.money && financeOff" tone="neutral" :title="t('cockpit.financeOff.title')" :description="t('cockpit.financeOff.body')" />
      <InlineAlert v-else-if="!data.can.money" tone="neutral" :title="t('cockpit.noMoney.title')" :description="t('cockpit.noMoney.body')" data-no-money />

      <div class="flex flex-col gap-4 lg:grid lg:grid-cols-[minmax(0,1fr)_minmax(320px,380px)] lg:items-start">
        <!-- Money: the left column on a wide screen, after what needs the owner on a phone. -->
        <div class="contents lg:flex lg:min-w-0 lg:flex-col lg:gap-4">
          <section v-if="money" class="order-3 flex min-w-0 flex-col gap-3 lg:order-none" :aria-label="t('cockpit.branches.title')" data-branches>
            <div class="flex flex-wrap items-end justify-between gap-x-4 gap-y-1 px-1">
              <div class="min-w-0">
                <h2 class="text-base font-semibold text-fg">{{ t("cockpit.branches.title") }}</h2>
                <p class="text-xs text-muted">{{ range }}</p>
              </div>
              <RouterLink :to="`${financePath}/reports`" class="text-xs font-semibold text-muted transition-colors hover:text-fg">{{ t("cockpit.branches.openPnl") }}</RouterLink>
            </div>

            <InlineAlert v-if="missing.length" tone="info" size="sm" :description="t('cockpit.branches.missing', { list: missingText })" data-missing />

            <div v-if="branches.length" class="grid min-w-0 gap-3 sm:grid-cols-2">
              <BranchCard v-for="(branch, index) in branches" :key="branch.id" :branch="branch" :period="key" :rank="index + 1" />
            </div>
            <div v-else class="ui-card px-4 py-8 text-center">
              <p class="text-sm font-semibold text-fg">{{ t("cockpit.branches.empty") }}</p>
              <p class="mx-auto mt-1 max-w-md text-sm text-muted">{{ t("cockpit.branches.emptyBody") }}</p>
            </div>

            <!-- The whole company, and what no pharmacy carries. -->
            <div v-if="total" class="ui-card flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:gap-6" data-total>
              <div class="min-w-0 sm:w-48">
                <p class="text-xs font-medium text-muted">{{ t("cockpit.branches.total") }}</p>
                <p :class="['text-xl font-semibold tabular-nums', compare(total.profit, 0) < 0 ? 'text-danger' : 'text-fg']"><MoneyText :value="total.profit" compact decimals="never" /></p>
                <p class="text-xs tabular-nums text-muted">
                  {{ t("cockpit.branches.revenue") }}: <MoneyText :value="total.revenue" compact decimals="never" />
                  <template v-if="total.margin !== null"> · {{ t("cockpit.branches.margin", { margin: fmt.percent(Number(total.margin), 1) }) }}</template>
                </p>
              </div>
              <ul class="flex min-w-0 flex-1 flex-wrap gap-x-4 gap-y-1.5 text-xs">
                <li v-for="cost in totalCosts" :key="cost.key" class="flex min-w-0 items-center gap-1.5">
                  <span class="size-2 shrink-0 rounded-full bg-[var(--c-chart-2)]" aria-hidden="true" />
                  <span class="truncate text-muted">{{ cost.key === "_other" ? t("cockpit.decisions.group.other") : cost.name }}</span>
                  <span class="font-semibold tabular-nums text-fg"><MoneyText :value="cost.amount" compact decimals="never" /></span>
                </li>
              </ul>
              <p v-if="unassigned && unassignedCosts.length" class="text-xs text-muted sm:max-w-[16rem]" data-unassigned>
                <span class="font-semibold text-fg">{{ t("cockpit.branches.unassigned") }}:</span>
                {{
                  unassignedCosts.map((cost) => `${cost.name} ${fmt.money(cost.amount, undefined, { compact: true })}`).join(", ")
                }}
              </p>
            </div>
          </section>

          <section v-if="cash" class="ui-card order-4 flex min-w-0 flex-col lg:order-none" :aria-label="t('cockpit.cash.title')" data-runway>
            <header class="flex flex-wrap items-start gap-x-4 gap-y-1 px-4 pb-1 pt-4">
              <div class="min-w-0 flex-1">
                <h2 class="text-base font-semibold text-fg">{{ t("cockpit.cash.title") }}</h2>
                <p class="text-xs text-muted">{{ t("cockpit.cash.subtitle") }}</p>
              </div>
              <RouterLink :to="`${financePath}/calendar?days=90`" class="inline-flex items-center gap-1 text-xs font-semibold text-muted transition-colors hover:text-fg">
                <CalendarClock :size="13" aria-hidden="true" />{{ t("cockpit.cash.calendar") }}
              </RouterLink>
            </header>
            <div class="px-4">
              <InlineAlert :tone="lowTone" size="sm" :title="lowLine" :description="bufferLine" class="mt-2" data-low />
            </div>
            <div class="px-2 pb-2 pt-1"><RunwayChart :cash="cash" height="250px" /></div>
            <div v-if="cash.low.causes.length" class="border-t border-line px-4 py-3">
              <p class="mb-2 text-xs font-medium text-muted">{{ t("cockpit.cash.causes") }}</p>
              <ul class="flex flex-col gap-1.5">
                <li v-for="cause in cash.low.causes" :key="`${cause.title}:${cause.date}`" class="flex items-center gap-3 text-sm" data-cause>
                  <span class="w-12 shrink-0 text-xs tabular-nums text-subtle">{{ fmt.day(cause.date, "short") }}</span>
                  <span class="min-w-0 flex-1 truncate text-fg" :title="cause.title">{{ cause.title }}</span>
                  <span class="hidden shrink-0 text-xs text-muted sm:inline">{{ t(`cockpit.cash.kind.${cause.kind}`) }}<template v-if="cause.overdue"> · {{ t("cockpit.cash.overdue") }}</template></span>
                  <span class="shrink-0 font-semibold tabular-nums text-fg">−<MoneyText :value="cause.amount" compact decimals="never" /></span>
                </li>
              </ul>
            </div>
          </section>
        </div>

        <!-- What needs the owner: the right column, first on a phone. -->
        <div class="contents lg:flex lg:min-w-0 lg:flex-col lg:gap-4">
          <DecisionList :decisions="data.decisions" class="order-1 lg:order-none" />
          <InsightList :insights="data.insights" :allowed="data.can.insights" :focus="focus" class="order-2 lg:order-none" />
        </div>
      </div>
    </template>
  </div>
</template>
