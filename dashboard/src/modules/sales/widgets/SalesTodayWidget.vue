<script setup lang="ts">
/**
 * Overview widget `sales.kpi.today` (plan §1.2): today's net sales so far against the same
 * weekday last week, with the last two weeks as a sparkline. Kept lean: it is part of the
 * Overview's first load, and fetches and fails on its own.
 */
import { Store } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import type { Range } from "@/api/types";
import KpiCard from "@/components/KpiCard.vue";
import { addDays, todayIn } from "@/lib/dates";
import { isZero } from "@/lib/decimal";
import { useCompanyStore } from "@/stores/company";

import { useSummary } from "../api";

const props = defineProps<{ companyId: number; range?: Range; compare?: Range | null }>();
const { t } = useI18n();
const company = useCompanyStore();
const today = computed(() => todayIn(company.timezone));
const params = computed(() => ({ from: addDays(today.value, -13), to: today.value }));
const query = useSummary(params, "day");
const series = computed(() => query.data.value?.series ?? []);
// Shift totals arrive when shifts close: until something closed today, show yesterday instead.
const yesterday = computed(() => series.value.length > 1 && isZero(series.value.at(-1)?.net ?? "0"));
const value = computed(() => series.value.at(yesterday.value ? -2 : -1)?.net ?? null);
const weekAgo = computed(() => {
  const index = series.value.length - (yesterday.value ? 9 : 8);
  return index >= 0 ? (series.value[index]?.net ?? null) : null;
});
const link = computed(() => `/c/${props.companyId}/sales`);
</script>

<template>
  <KpiCard
    :label="yesterday ? t('sales.widget.yesterday') : t('sales.widget.today')"
    :value="query.isError.value ? null : value"
    :previous="weekAgo"
    format="money"
    compact
    :delta-label="t('sales.widget.vsWeekday')"
    :spark="series.map((point) => point.net)"
    :icon="Store"
    :to="link"
    :loading="query.isPending.value"
    :hint="query.isError.value ? t('sales.widget.error') : undefined"
  />
</template>
