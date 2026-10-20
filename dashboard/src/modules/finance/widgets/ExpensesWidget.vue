<script setup lang="ts">
/** Overview widget "Expenses this month" against the same days of last month (lower is better). */
import { TrendingDown } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import type { Range } from "@/api/types";
import ErrorState from "@/components/ErrorState.vue";
import KpiCard from "@/components/KpiCard.vue";

import { useOverview } from "../api";

defineProps<{ companyId: number; range?: Range; compare?: Range | null }>();

const { t } = useI18n();
const overview = useOverview();
const month = computed(() => overview.data.value?.month);
</script>

<template>
  <ErrorState v-if="overview.isError.value" compact :error="overview.error.value" :retry="() => overview.refetch()" class="h-full" />
  <KpiCard
    v-else
    class="h-full"
    :label="t('finance.overview.expensesMonth')"
    :value="month?.expense ?? null"
    :previous="month?.previous.expense ?? null"
    format="money"
    compact
    inverse
    :icon="TrendingDown"
    :delta-label="t('finance.overview.vsLastMonth')"
    :loading="overview.isPending.value"
    :to="{ path: `/c/${companyId}/finance/transactions`, query: { kind: 'expense', from: month?.from, to: month?.to } }"
  />
</template>
