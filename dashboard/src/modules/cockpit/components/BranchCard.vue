<script setup lang="ts">
/**
 * One pharmacy's real profit for the period: its rank, a state pill (earning, watch, losing
 * money) with the reason, profit and margin with their change, the monthly profit trend, revenue
 * and gross margin, and the costs that took the money, each as a share bar.
 */
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import DeltaBadge from "@/components/DeltaBadge.vue";
import MoneyText from "@/components/MoneyText.vue";
import SparkLine from "@/components/SparkLine.vue";
import StatusPill from "@/components/StatusPill.vue";
import { compare } from "@/lib/decimal";
import { useFormat } from "@/lib/useFormat";

import type { CockpitBranch, PeriodKey } from "../api";
import { marginPoints, monthDay, profitChange, STATE_TONE, topCosts } from "../lib";

const props = defineProps<{ branch: CockpitBranch; period: PeriodKey; rank: number }>();

const { t } = useI18n();
const fmt = useFormat();

const figures = computed(() => props.branch[props.period]);
const state = computed(() => props.branch.states[props.period]);
const losing = computed(() => compare(figures.value.profit, 0) < 0);
const change = computed(() => profitChange(figures.value));
const points = computed(() => marginPoints(figures.value));
const costs = computed(() => topCosts(figures.value, 3));
const noRevenue = computed(() => compare(figures.value.revenue, 0) <= 0);
const STATE_COLOR = { green: "var(--c-success)", amber: "var(--c-warning)", red: "var(--c-danger)" } as const;
const trend = computed(() => props.branch.trend.map((point) => point.profit));
const last = computed(() => props.branch.trend.at(-1));
const reasons = computed(() => state.value.reasons.filter((reason) => reason !== "loss" || state.value.state !== "red"));
const percent = (value: string | null) => (value === null ? "—" : fmt.percent(Number(value), 1));
</script>

<template>
  <article
    class="ui-card flex min-w-0 flex-col gap-4 p-4 transition-colors hover:border-line-strong sm:p-5"
    :data-branch="branch.id"
    :data-state="state.state"
    :aria-label="branch.name"
  >
    <header class="flex items-start gap-3">
      <span
        :class="[
          'grid size-8 shrink-0 place-items-center rounded-full text-sm font-semibold tabular-nums',
          rank === 1 ? 'bg-accent-soft text-accent-fg' : 'bg-surface-2 text-muted dark:bg-surface-3',
        ]"
        :aria-label="t('cockpit.branches.rank', { n: rank })"
        >{{ rank }}</span
      >
      <div class="min-w-0 flex-1">
        <h3 class="truncate text-base font-semibold leading-6 text-fg" :title="branch.name">{{ branch.name }}</h3>
        <p v-if="reasons.length" class="truncate text-xs text-muted">
          {{ reasons.map((reason) => t(`cockpit.branches.reason.${reason}`)).join(" · ") }}
        </p>
      </div>
      <StatusPill :tone="STATE_TONE[state.state]" :label="t(`cockpit.branches.state.${state.state}`)" size="sm" />
    </header>

    <div class="flex items-end justify-between gap-4">
      <div class="min-w-0">
        <p class="text-xs font-medium text-muted">{{ t("cockpit.branches.profit") }}</p>
        <p :class="['mt-0.5 truncate text-2xl font-semibold leading-8 tabular-nums', losing ? 'text-danger' : 'text-fg']" data-profit>
          <MoneyText :value="figures.profit" compact decimals="never" />
        </p>
        <div class="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted">
          <span class="tabular-nums">{{ t("cockpit.branches.margin", { margin: percent(figures.margin) }) }}</span>
          <DeltaBadge v-if="points !== null" :value="points" points size="sm" />
          <DeltaBadge v-else-if="change !== null" :value="change" size="sm" />
        </div>
      </div>
      <div v-if="trend.length > 1" class="flex shrink-0 flex-col items-end gap-1">
        <SparkLine :data="trend" :color="STATE_COLOR[state.state]" :width="112" :height="40" :label="t('cockpit.branches.trendLabel', { name: branch.name })" />
        <span v-if="last" class="text-[11px] tabular-nums text-subtle">
          {{ t("cockpit.branches.lastMonth", { month: fmt.day(monthDay(last.month), "monthYear"), amount: fmt.money(last.profit, undefined, { compact: true }) }) }}
        </span>
      </div>
    </div>

    <dl class="grid grid-cols-2 gap-3 rounded-[10px] bg-surface-2/60 p-3 dark:bg-surface-3/40">
      <div class="min-w-0">
        <dt class="text-xs text-muted">{{ t("cockpit.branches.revenue") }}</dt>
        <dd class="truncate text-sm font-semibold tabular-nums text-fg"><MoneyText :value="figures.revenue" compact decimals="never" /></dd>
      </div>
      <div class="min-w-0">
        <dt class="text-xs text-muted" :title="t('cockpit.branches.grossHint')">{{ t("cockpit.branches.gross") }}</dt>
        <dd class="truncate text-sm font-semibold tabular-nums text-fg">
          <template v-if="noRevenue">{{ t("cockpit.branches.noRevenue") }}</template>
          <template v-else>{{ percent(figures.gross_margin) }}</template>
        </dd>
      </div>
    </dl>

    <div v-if="costs.length" class="flex flex-col gap-2">
      <p class="text-xs font-medium text-muted">{{ t("cockpit.branches.costs") }}</p>
      <ul class="flex flex-col gap-2">
        <li v-for="cost in costs" :key="cost.key" class="flex flex-col gap-1" :data-cost="cost.key">
          <div class="flex items-baseline justify-between gap-3 text-sm">
            <span class="min-w-0 truncate text-fg">{{ cost.key === "_other" ? t("cockpit.decisions.group.other") : cost.name }}</span>
            <span class="shrink-0 tabular-nums text-muted"><MoneyText :value="cost.amount" compact decimals="never" /></span>
          </div>
          <span class="h-1.5 overflow-hidden rounded-full bg-surface-2 dark:bg-surface-3" aria-hidden="true">
            <span class="block h-full rounded-full bg-[var(--c-chart-2)] opacity-80" :style="{ width: `${Math.max(2, Math.min(100, cost.share))}%` }" />
          </span>
        </li>
      </ul>
    </div>
  </article>
</template>
