<script setup lang="ts">
/**
 * Exchange rates (plan §1.6 "daily CBU fetch, own company rate, stale flag"): the dollar rate in use
 * today and where it comes from, a warning when it is an older rate, "Fetch from the Central Bank
 * now", the company's own rate for a day, and the last 60 days of rates as a chart and a list.
 */
import { CircleAlert, CircleCheck, Landmark, RefreshCw, Trash2 } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import ChartCard from "@/components/ChartCard.vue";
import DatePicker from "@/components/DatePicker.vue";
import ErrorState from "@/components/ErrorState.vue";
import FormField from "@/components/FormField.vue";
import IconButton from "@/components/IconButton.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import LineChart from "@/components/LineChart.vue";
import NumberInput from "@/components/NumberInput.vue";
import RelativeTime from "@/components/RelativeTime.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import UiButton from "@/components/UiButton.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { todayIn } from "@/lib/dates";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { financeApi, useRates, useRefresh } from "../../api";
import { useCssColor } from "../../colors";

const { t } = useI18n();
const css = useCssColor();
const fmt = useFormat();
const company = useCompanyStore();
const confirm = useConfirm();
const refresh = useRefresh();
const rates = useRates();
const data = computed(() => rates.data.value);
const canManage = computed(() => company.can("finance.manage"));
const fetching = ref(false);
const saving = ref(false);
const form = ref({ date: todayIn(company.timezone) as string | null, rate: null as number | null });

async function fetchNow(): Promise<void> {
  fetching.value = true;
  try {
    const result = await financeApi.fetchRate(company.currentId ?? 0);
    toast.success(result.detail, { description: result.rate ? `1 USD = ${fmt.money(result.rate, "UZS", { decimals: "always" })}` : undefined });
    refresh();
  } catch {
    toast.warning(t("finance.rates.fetchFailed"));
  } finally {
    fetching.value = false;
  }
}

async function setRate(): Promise<void> {
  if (!form.value.date || !form.value.rate) return;
  saving.value = true;
  try {
    await financeApi.setRate(company.currentId ?? 0, form.value.date, String(form.value.rate));
    toast.success(t("finance.rates.saved"));
    form.value.rate = null;
    refresh();
  } finally {
    saving.value = false;
  }
}

async function remove(id: string): Promise<void> {
  const answer = await confirm({ title: t("finance.rates.deleteTitle"), tone: "danger", confirmLabel: t("common.delete") });
  if (!answer) return;
  await financeApi.deleteRate(company.currentId ?? 0, Number(id.replace("company-", "")));
  refresh();
}

const official = computed(() => [...(data.value?.rows ?? [])].filter((row) => row.source !== "company").reverse());
const own = computed(() => (data.value?.rows ?? []).filter((row) => row.source === "company"));
const chartDays = computed(() => official.value.map((row) => row.date));
/**
 * The rate moves by tens of so‘m around 12,000: drawn from zero it is a flat line. The charts have no
 * axis minimum, so the series are drawn above a round floor under the period's low and every label
 * and tooltip adds the floor back: the axis reads the real rates.
 */
const chartFloor = computed(() => {
  const values = [...official.value, ...own.value].map((row) => Number(row.rate)).filter((v) => Number.isFinite(v) && v > 0);
  if (!values.length) return 0;
  const low = Math.min(...values);
  const high = Math.max(...values);
  const step = 10 ** Math.max(0, Math.floor(Math.log10(Math.max(high - low, 1))));
  return Math.max(0, Math.floor((low - Math.max(high - low, step) * 0.5) / step) * step);
});
const lift = (rate: string | null | undefined) => (rate ? Number(rate) - chartFloor.value : null);
const chartSeries = computed(() => [
  { name: t("finance.rates.cbu"), data: official.value.map((row) => lift(row.rate)), color: css("var(--c-chart-3)") },
  { name: t("finance.rates.own"), data: official.value.map((row) => lift(own.value.find((o) => o.date === row.date)?.rate)), color: css("var(--c-chart-1)") },
]);
const rateText = (value: number) => fmt.number(value + chartFloor.value, 2);
const sourceLabel = computed(() => (data.value ? t(`finance.rates.source.${data.value.current.source}`) : ""));
</script>

<template>
  <div class="flex flex-col gap-4">
    <ErrorState v-if="rates.isError.value" :error="rates.error.value" :retry="() => rates.refetch()" />
    <template v-else>
      <section class="ui-card flex flex-wrap items-center gap-x-8 gap-y-4 p-5">
        <div class="flex items-center gap-3">
          <span class="grid size-11 place-items-center rounded-[12px] bg-info-soft text-info" aria-hidden="true"><Landmark :size="20" /></span>
          <div>
            <p class="text-sm font-medium text-muted">{{ t("finance.rates.today") }}</p>
            <SkeletonBlock v-if="rates.isPending.value" width="180px" height="30px" />
            <p v-else-if="data?.current.rate" class="text-2xl font-semibold tabular-nums text-fg">1 USD = {{ fmt.money(data.current.rate, "UZS", { decimals: "always" }) }}</p>
            <p v-else class="text-lg font-semibold text-muted">{{ t("finance.rates.none") }}</p>
          </div>
        </div>
        <div v-if="data" class="flex flex-col items-start gap-1.5">
          <StatusPill :tone="data.current.stale ? 'warning' : 'success'" :icon="data.current.stale ? CircleAlert : CircleCheck" :label="data.current.stale ? t('finance.rates.stale') : t('finance.rates.fresh')" />
          <p class="text-xs text-muted">
            {{ sourceLabel }}<template v-if="data.current.date"> · {{ fmt.day(data.current.date, "short") }}</template>
            <template v-if="data.current.last_fetched_at"> · {{ t("finance.rates.fetched") }} <RelativeTime :value="data.current.last_fetched_at" /></template>
          </p>
        </div>
        <UiButton v-if="canManage" class="sm:ml-auto" :icon="RefreshCw" :loading="fetching" @click="fetchNow">{{ t("finance.rates.fetchNow") }}</UiButton>
      </section>

      <InlineAlert v-if="data?.current.stale" tone="warning" :title="t('finance.rates.staleTitle')" :description="t('finance.rates.staleBody')" />

      <div class="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
        <ChartCard :title="t('finance.rates.chart')" :subtitle="t('finance.rates.chartHint')" :loading="rates.isPending.value" :empty="!official.length" height="260px">
          <LineChart :categories="chartDays" :series="chartSeries" x-format="day" height="260px" legend :value-format="rateText" />
        </ChartCard>
        <section v-if="canManage" class="ui-card flex flex-col gap-3 p-4">
          <div>
            <h3 class="text-sm font-semibold text-fg">{{ t("finance.rates.ownTitle") }}</h3>
            <p class="text-xs text-muted">{{ t("finance.rates.ownHint") }}</p>
          </div>
          <div class="grid grid-cols-2 gap-2">
            <FormField :label="t('finance.field.date')">
              <DatePicker v-model="form.date" :max="todayIn(company.timezone)" />
            </FormField>
            <FormField :label="t('finance.rates.rate')">
              <NumberInput v-model="form.rate" :min="1" :step="0.01" :decimals="2" />
            </FormField>
          </div>
          <UiButton variant="primary" :loading="saving" :disabled="!form.date || !form.rate" @click="setRate">{{ t("finance.rates.setOwn") }}</UiButton>
          <ul v-if="own.length" class="flex flex-col divide-y divide-line border-t border-line">
            <li v-for="row in own" :key="row.id" class="flex items-center gap-2 py-2 text-sm">
              <span class="w-24 text-muted">{{ fmt.day(row.date, "short") }}</span>
              <span class="flex-1 font-semibold tabular-nums text-fg">{{ fmt.number(row.rate, 2) }}</span>
              <span class="truncate text-xs text-subtle">{{ row.set_by }}</span>
              <IconButton :icon="Trash2" size="sm" :label="t('common.delete')" @click="remove(row.id)" />
            </li>
          </ul>
        </section>
      </div>
    </template>
  </div>
</template>
