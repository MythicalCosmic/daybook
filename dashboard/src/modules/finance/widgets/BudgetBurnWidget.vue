<script setup lang="ts">
/**
 * Overview widget "Budgets this month" (plan §11.4 `finance.budget_burn`): the three budgets most
 * used so far, each with its bar coloured by the server's status (amber from 80 %, red from 100 %)
 * and a tick at the month's even pace, and how many are over in the header.
 */
import { PiggyBank } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink } from "vue-router";

import type { Range } from "@/api/types";
import { shareText } from "@/components/chartCard";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import ProgressBar from "@/components/ProgressBar.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import WidgetCard from "@/components/WidgetCard.vue";
import { useWidgetSkeleton } from "@/components/widgetSkeleton";
import { useFormat } from "@/lib/useFormat";
import { useCompanyToday } from "@/stores/company";

import { useBudgets } from "../api";
import { BUDGET_TONES, colorFor, monthPace } from "../lib";

const props = defineProps<{ companyId: number; range?: Range; compare?: Range | null }>();

const { t } = useI18n();
const fmt = useFormat();
const today = useCompanyToday();
const query = useBudgets(() => today.value.slice(0, 7));
const skeleton = useWidgetSkeleton(() => query.isPending.value);
const budgeted = computed(() => (query.data.value?.rows ?? []).filter((row) => row.budget !== null && row.share !== null));
const top = computed(() => [...budgeted.value].sort((a, b) => Number(b.share) - Number(a.share)).slice(0, 3));
const over = computed(() => budgeted.value.filter((row) => row.status === "over").length);
const pace = computed(() => (query.data.value ? monthPace(query.data.value.days_left, query.data.value.days_in_month) : undefined));
const to = computed(() => `/c/${props.companyId}/finance/budgets`);
</script>

<template>
  <WidgetCard :title="t('finance.widget.budgets')" :icon="PiggyBank" :count="over" count-tone="danger" :subtitle="t('finance.widget.budgetsSub')" :to="to">
    <div v-if="skeleton" class="flex flex-col gap-3 p-2">
      <div v-for="n in 3" :key="n" class="flex flex-col gap-1.5"><SkeletonBlock width="50%" /><SkeletonBlock height="6px" /></div>
    </div>
    <ErrorState v-else-if="query.isError.value" compact :error="query.error.value" :retry="() => query.refetch()" class="m-2" />
    <EmptyState v-else-if="query.data.value && !top.length" class="my-auto" size="sm" tone="neutral" :icon="PiggyBank" :title="t('finance.widget.noBudgets')" :description="t('finance.widget.noBudgetsBody')" />
    <ul v-else class="flex flex-col">
      <li v-for="row in top" :key="row.category.id">
        <RouterLink :to="to" class="flex flex-col gap-1.5 rounded-[10px] px-2 py-2 transition-colors hover:bg-highlight">
          <span class="flex min-w-0 items-center gap-2 text-sm">
            <span class="size-2 shrink-0 rounded-full" :style="{ background: colorFor(row.category.id, row.category.color) }" aria-hidden="true" />
            <span class="min-w-0 flex-1 truncate font-medium text-fg" :title="row.category.name">{{ row.category.name }}</span>
            <span :class="['shrink-0 text-xs font-semibold tabular-nums', row.status === 'over' ? 'text-danger' : row.status === 'warning' ? 'text-warning' : 'text-muted']">{{ shareText(Number(row.share) * 100, fmt.lang.value) }}</span>
          </span>
          <ProgressBar :value="Number(row.share) * 100" :max="100" size="sm" :tone="BUDGET_TONES[row.status]" :target="pace" />
          <span class="text-xs tabular-nums text-muted">{{ t("finance.widget.budgetOf", { spent: fmt.money(row.actual, undefined, { compact: true }), budget: fmt.money(row.budget, undefined, { compact: true }) }) }}</span>
        </RouterLink>
      </li>
    </ul>
  </WidgetCard>
</template>
