<script setup lang="ts">
/**
 * What a round's published reviews came to: the average rating and how the ratings spread, what
 * followed (raises, bonuses, promotions, improvement plans), what the raises add to the monthly
 * pay and what the bonuses come to (payroll.view only), per question the people's own average
 * beside the reviewers', and the same by pharmacy. The export has every review in a row.
 */
import { Award, Banknote, Gift, Star, Target, TrendingUp, Users } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import BarChart from "@/components/BarChart.vue";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import ExportButton from "@/components/ExportButton.vue";
import MoneyText from "@/components/MoneyText.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import { useFormat } from "@/lib/useFormat";

import { useResults } from "../../reviews/api";
import { RATINGS } from "../../reviews/lib";
import type { Outcome } from "../../reviews/types";

const props = defineProps<{ roundId: number }>();

const { t } = useI18n();
const fmt = useFormat();
const query = useResults(() => props.roundId);
const data = computed(() => query.data.value ?? null);

// From a concern (1) to strong (5), in the theme's own colours.
const SPREAD_COLORS = [
  "var(--c-danger)",
  "color-mix(in srgb, var(--c-danger) 50%, var(--c-warning))",
  "var(--c-warning)",
  "color-mix(in srgb, var(--c-success) 60%, var(--c-warning))",
  "var(--c-success)",
];
const spread = computed(() => {
  const value = data.value;
  const max = Math.max(1, ...RATINGS.map((rating) => value?.spread[String(rating)] ?? 0));
  return RATINGS.map((rating, index) => ({ rating, count: value?.spread[String(rating)] ?? 0, share: Math.round((100 * (value?.spread[String(rating)] ?? 0)) / max), color: SPREAD_COLORS[index] }));
});
const OUTCOME_ICONS: Record<Exclude<Outcome, "none">, typeof Star> = { raise: TrendingUp, bonus: Gift, promotion: Award, improvement_plan: Target };
const outcomes = computed(() => (["raise", "bonus", "promotion", "improvement_plan", "none"] as Outcome[]).map((value) => ({ value, count: data.value?.outcomes[value] ?? 0 })));
const questionChart = computed(() => {
  const rows = data.value?.questions ?? [];
  return {
    categories: rows.map((_, index) => t("lifecycle.reviews.results.questionShort", { number: index + 1 })),
    series: [
      { name: t("lifecycle.reviews.results.selfAverage"), data: rows.map((row) => (row.self_average ? Number(row.self_average) : null)), color: "var(--c-info)" },
      { name: t("lifecycle.reviews.results.managerAverage"), data: rows.map((row) => (row.manager_average ? Number(row.manager_average) : null)), color: "var(--c-primary)" },
    ],
  };
});
</script>

<template>
  <div class="flex flex-col gap-4" data-results>
    <div v-if="query.isPending.value" class="grid gap-3 sm:grid-cols-4">
      <SkeletonBlock v-for="n in 4" :key="n" height="96px" radius="14px" />
    </div>
    <ErrorState v-else-if="query.isError.value" :error="query.error.value" :retry="() => query.refetch()" />
    <EmptyState v-else-if="!data?.published" :icon="Star" tone="neutral" :title="t('lifecycle.reviews.results.emptyTitle')" :description="t('lifecycle.reviews.results.emptyBody')" class="ui-card" />
    <template v-else>
      <div class="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <div class="ui-card p-4">
          <p class="flex items-center gap-1.5 text-xs font-medium text-muted"><Star :size="14" aria-hidden="true" />{{ t("lifecycle.reviews.results.average") }}</p>
          <p class="mt-1 text-2xl font-semibold tabular-nums text-fg">{{ data.average ? fmt.number(data.average, 1) : "—" }}<span class="text-sm font-normal text-muted"> / 5</span></p>
        </div>
        <div class="ui-card p-4">
          <p class="flex items-center gap-1.5 text-xs font-medium text-muted"><Users :size="14" aria-hidden="true" />{{ t("lifecycle.reviews.results.published") }}</p>
          <p class="mt-1 text-2xl font-semibold tabular-nums text-fg">{{ data.published }}<span class="text-sm font-normal text-muted"> / {{ data.people }}</span></p>
        </div>
        <div class="ui-card p-4" data-raise-cost>
          <p class="flex items-center gap-1.5 text-xs font-medium text-muted"><TrendingUp :size="14" aria-hidden="true" />{{ t("lifecycle.reviews.results.raisesCost") }}</p>
          <template v-if="data.cost">
            <p class="mt-1 text-2xl font-semibold tabular-nums text-fg"><MoneyText :value="data.cost.raises_monthly" :currency="data.cost.currency" compact /></p>
            <p v-if="Number(data.cost.raises_waiting) > 0" class="text-xs text-warning">{{ t("lifecycle.reviews.results.waiting") }}: <MoneyText :value="data.cost.raises_waiting" :currency="data.cost.currency" compact /></p>
            <p v-else class="text-xs text-muted">{{ t("lifecycle.reviews.results.perMonth") }}</p>
          </template>
          <p v-else class="mt-1 text-sm text-muted">{{ t("lifecycle.reviews.results.payHidden") }}</p>
        </div>
        <div class="ui-card p-4">
          <p class="flex items-center gap-1.5 text-xs font-medium text-muted"><Banknote :size="14" aria-hidden="true" />{{ t("lifecycle.reviews.results.bonuses") }}</p>
          <template v-if="data.cost">
            <p class="mt-1 text-2xl font-semibold tabular-nums text-fg"><MoneyText :value="data.cost.bonuses" :currency="data.cost.currency" compact /></p>
            <p v-if="Number(data.cost.bonuses_waiting) > 0" class="text-xs text-warning">{{ t("lifecycle.reviews.results.waiting") }}: <MoneyText :value="data.cost.bonuses_waiting" :currency="data.cost.currency" compact /></p>
            <p v-else class="text-xs text-muted">{{ t("lifecycle.reviews.results.approvedOnly") }}</p>
          </template>
          <p v-else class="mt-1 text-sm text-muted">{{ t("lifecycle.reviews.results.payHidden") }}</p>
        </div>
      </div>

      <div class="grid gap-4 lg:grid-cols-2">
        <section class="ui-card p-4 sm:p-5" data-spread>
          <h3 class="text-sm font-semibold text-fg">{{ t("lifecycle.reviews.results.spread") }}</h3>
          <p class="mb-4 text-xs text-muted">{{ t("lifecycle.reviews.results.spreadHint") }}</p>
          <ul class="flex flex-col gap-2.5">
            <li v-for="row in spread.slice().reverse()" :key="row.rating" class="flex items-center gap-3">
              <span class="w-24 shrink-0 text-sm text-muted">{{ row.rating }} · {{ t(`lifecycle.reviews.rating.word${row.rating}`) }}</span>
              <span class="relative h-6 flex-1 overflow-hidden rounded-[8px] bg-surface-2 dark:bg-surface-3">
                <span class="absolute inset-y-0 left-0 rounded-[8px] transition-[width] duration-500" :style="{ width: `${row.share}%`, background: row.color }" />
              </span>
              <span class="w-8 shrink-0 text-right text-sm font-semibold tabular-nums text-fg">{{ row.count }}</span>
            </li>
          </ul>
        </section>
        <section class="ui-card p-4 sm:p-5" data-outcomes>
          <h3 class="mb-4 text-sm font-semibold text-fg">{{ t("lifecycle.reviews.results.outcomes") }}</h3>
          <ul class="grid grid-cols-2 gap-2.5">
            <li v-for="item in outcomes" :key="item.value" :class="['flex items-center gap-3 rounded-[12px] border border-line px-3 py-2.5', item.value === 'none' ? 'col-span-2' : '']">
              <span class="grid size-8 shrink-0 place-items-center rounded-[10px] bg-surface-2 text-muted dark:bg-surface-3">
                <component :is="item.value === 'none' ? Users : OUTCOME_ICONS[item.value]" :size="15" aria-hidden="true" />
              </span>
              <span class="min-w-0 flex-1 truncate text-sm text-muted">{{ t(`lifecycle.reviews.outcome.${item.value}`) }}</span>
              <span class="text-lg font-semibold tabular-nums text-fg">{{ item.count }}</span>
            </li>
          </ul>
        </section>
      </div>

      <section v-if="data.questions.length" class="ui-card p-4 sm:p-5" data-questions-chart>
        <h3 class="text-sm font-semibold text-fg">{{ t("lifecycle.reviews.results.byQuestion") }}</h3>
        <p class="mb-2 text-xs text-muted">{{ t("lifecycle.reviews.results.byQuestionHint") }}</p>
        <BarChart :categories="questionChart.categories" :series="questionChart.series" :y-max="5" height="220px" legend :label="t('lifecycle.reviews.results.byQuestion')" />
        <ol class="mt-3 grid gap-1 text-xs text-muted sm:grid-cols-2">
          <li v-for="(row, index) in data.questions" :key="row.id" class="truncate" :title="row.text">{{ index + 1 }}. {{ row.text }}</li>
        </ol>
      </section>

      <section class="ui-card overflow-hidden" data-by-branch>
        <div class="flex flex-wrap items-center justify-between gap-2 px-4 pt-4 sm:px-5">
          <h3 class="text-sm font-semibold text-fg">{{ t("lifecycle.reviews.results.byBranch") }}</h3>
          <ExportButton kind="lifecycle.reviews" :params="{ round: roundId }" sensitive size="sm" />
        </div>
        <div class="mt-3 overflow-x-auto">
          <table class="w-full min-w-[560px] text-sm">
            <thead>
              <tr class="border-b border-line text-left text-xs text-muted">
                <th class="px-4 py-2 font-medium sm:px-5">{{ t("lifecycle.reviews.results.branch") }}</th>
                <th class="px-3 py-2 text-right font-medium">{{ t("lifecycle.reviews.results.people") }}</th>
                <th class="px-3 py-2 text-right font-medium">{{ t("lifecycle.reviews.results.average") }}</th>
                <th class="px-3 py-2 text-right font-medium">{{ t("lifecycle.reviews.outcome.raise") }}</th>
                <th class="px-3 py-2 text-right font-medium">{{ t("lifecycle.reviews.outcome.bonus") }}</th>
                <th class="px-3 py-2 text-right font-medium">{{ t("lifecycle.reviews.outcome.promotion") }}</th>
                <th class="px-3 py-2 text-right font-medium">{{ t("lifecycle.reviews.results.plans") }}</th>
                <th v-if="data.cost" class="px-4 py-2 text-right font-medium sm:px-5">{{ t("lifecycle.reviews.results.costColumn") }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in data.by_branch" :key="row.branch?.id ?? 0" class="border-b border-line last:border-0">
                <td class="px-4 py-2.5 font-medium text-fg sm:px-5">{{ row.branch?.name ?? t("lifecycle.reviews.results.noBranch") }}</td>
                <td class="px-3 py-2.5 text-right tabular-nums">{{ row.people }}</td>
                <td class="px-3 py-2.5 text-right tabular-nums">{{ row.average ? fmt.number(row.average, 1) : "—" }}</td>
                <td class="px-3 py-2.5 text-right tabular-nums">{{ row.raises }}</td>
                <td class="px-3 py-2.5 text-right tabular-nums">{{ row.bonuses }}</td>
                <td class="px-3 py-2.5 text-right tabular-nums">{{ row.promotions }}</td>
                <td class="px-3 py-2.5 text-right tabular-nums">{{ row.plans }}</td>
                <td v-if="data.cost" class="px-4 py-2.5 text-right tabular-nums sm:px-5">
                  <MoneyText :value="String(Number(row.raise_cost ?? 0) + Number(row.bonus_total ?? 0))" :currency="data.cost.currency" compact />
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </template>
  </div>
</template>
