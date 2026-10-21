<script setup lang="ts">
/**
 * Overview widget `sales.kpi.today` (plan §1.2): today's net sales from the shifts closed so far,
 * or yesterday's against the same weekday the week before (a day still running isn't compared
 * with a whole one), with the last two weeks as a sparkline. Kept lean: it is part of the
 * Overview's first load, and fetches and fails on its own.
 */
import { Store } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import type { Range } from "@/api/types";
import KpiCard from "@/components/KpiCard.vue";
import { addDays, todayIn } from "@/lib/dates";
import { isZero } from "@/lib/decimal";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { useSummary } from "../api";

const props = defineProps<{ companyId: number; range?: Range; compare?: Range | null }>();
const { t } = useI18n();
const fmt = useFormat();
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
// The trend ends on the day the number shows: yesterday's tile leaves out today, still empty.
const trend = computed(() => (yesterday.value ? series.value.slice(0, -1) : series.value));
const trendLabels = computed<[string, string] | undefined>(() => {
  const first = trend.value[0]?.date;
  return first && trend.value.length > 1 ? [fmt.day(first, "short"), yesterday.value ? t("common.yesterday") : t("common.today")] : undefined;
});
const link = computed(() => `/c/${props.companyId}/sales`);
</script>

<template>
  <KpiCard
    :error="query.isError.value ? query.error.value : undefined"
    :retry="() => query.refetch()"
    class="h-full"
    :label="yesterday ? t('sales.widget.yesterday') : t('sales.widget.today')"
    :value="value"
    :previous="yesterday ? weekAgo : undefined"
    format="money"
    compact
    :delta-label="yesterday ? t('sales.widget.vsWeekday') : undefined"
    :spark="trend.map((point) => point.net)"
    :spark-labels="trendLabels"
    :icon="Store"
    :to="link"
    :loading="query.isPending.value"
    :hint="yesterday ? undefined : t('sales.widget.soFar')"
  />
</template>
