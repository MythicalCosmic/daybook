<script setup lang="ts">
/**
 * A readings routine's journal (PLAN-OWNER §14.10): what was taken, how often out of range, the
 * rechecks and the days nobody took it; a line chart of one reading over its allowed band with
 * excursions marked; every value with who took it and the note; and the branch's month as a PDF
 * (the official temperature and humidity log, a signature line per day).
 */
import { FileDown, Thermometer } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import ChartCard from "@/components/ChartCard.vue";
import { EChartAsync } from "@/components/chartCard";
import KpiStrip from "@/components/KpiStrip.vue";
import PageSection from "@/components/PageSection.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SelectBox from "@/components/SelectBox.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import UiButton from "@/components/UiButton.vue";
import { useChartTheme } from "@/components/useChartTheme";
import { addMonths, startOfMonth, todayIn } from "@/lib/dates";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { openReadingsPdf, useRoutineReadings } from "../api";
import { rangeText, specRange, valueText } from "../readings";
import { readingsOption } from "../readingsChart";
import type { Routine } from "../types";

const props = defineProps<{ routine: Routine; range: { from: string; to: string } }>();

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const host = ref<HTMLElement | null>(null);
const theme = useChartTheme(host);

const query = useRoutineReadings(
  computed(() => props.routine.id),
  computed(() => props.range),
);
const data = computed(() => query.data.value ?? null);
const specs = computed(() => data.value?.specs.length ? data.value.specs : (props.routine.readings ?? []));
const key = ref<string>("");
watch(
  specs,
  (list) => {
    if (!list.some((spec) => spec.key === key.value)) key.value = list[0]?.key ?? "";
  },
  { immediate: true },
);
const spec = computed(() => specs.value.find((item) => item.key === key.value) ?? null);
const keyOptions = computed(() => specs.value.map((item) => ({ value: item.key, label: item.label })));

const kpis = computed(() => {
  const totals = data.value?.totals;
  return [
    { id: "taken", label: t("routines.readings.kpi.taken"), value: totals?.taken ?? null },
    { id: "excursions", label: t("routines.readings.kpi.excursions"), value: totals?.excursions ?? null, hint: t("routines.readings.kpi.excursionsHint") },
    { id: "rechecks", label: t("routines.readings.kpi.rechecks"), value: totals?.rechecks ?? null },
    { id: "missed", label: t("routines.readings.kpi.missed"), value: totals?.missed ?? null, hint: t("routines.readings.kpi.missedHint") },
  ];
});

const option = computed(() => {
  const chosen = spec.value;
  const rows = data.value?.series ?? [];
  if (!chosen) return null;
  return readingsOption(theme.value, {
    days: rows.map((row) => row.date),
    values: rows.map((row) => (row[chosen.key] === null || row[chosen.key] === undefined ? null : Number(row[chosen.key]))),
    min: chosen.min === null ? null : Number(chosen.min),
    max: chosen.max === null ? null : Number(chosen.max),
    label: chosen.label,
    unit: chosen.unit,
    lang: fmt.lang.value,
    words: { out: t("routines.readings.outOfRange"), allowed: t("routines.readings.allowedShort") },
  });
});
const hasValues = computed(() => (data.value?.series ?? []).some((row) => spec.value && row[spec.value.key] !== null && row[spec.value.key] !== undefined));

// Newest first in the table, as a journal is read.
const rows = computed(() => [...(data.value?.rows ?? [])].reverse());

// The month's log of the routine's branch, as a PDF.
const today = computed(() => todayIn(company.timezone));
const months = computed(() =>
  Array.from({ length: 12 }, (_, index) => {
    const first = addMonths(startOfMonth(today.value), -index);
    return { value: first.slice(0, 7), label: fmt.day(first, "monthYear") };
  }),
);
const month = ref(months.value[0]?.value ?? "");
const downloading = ref(false);
async function download(): Promise<void> {
  const branch = props.routine.branch;
  if (!branch || !month.value) return;
  downloading.value = true;
  try {
    await openReadingsPdf(company.currentId ?? 0, branch.id, month.value);
  } catch {
    // the HTTP layer showed why
  } finally {
    downloading.value = false;
  }
}
</script>

<template>
  <PageSection :title="t('routines.readings.journalTitle')" :description="t('routines.readings.journalHint')" data-testid="readings-journal">
    <template #actions>
      <div v-if="routine.branch" class="flex flex-wrap items-center gap-2">
        <SelectBox v-model="month" :options="months" size="sm" class="w-[170px]" :aria-label="t('routines.readings.month')" />
        <UiButton size="sm" :icon="FileDown" :loading="downloading" @click="download">{{ t("routines.readings.pdf") }}</UiButton>
      </div>
    </template>

    <div class="flex flex-col gap-4">
      <KpiStrip :items="kpis" :loading="query.isPending.value" :columns="4" phone="compact" />

      <div ref="host">
        <ChartCard
          :title="spec ? spec.label : t('routines.readings.journalTitle')"
          :subtitle="spec ? [specRange(spec, fmt.lang.value) && t('routines.readings.allowed', { range: specRange(spec, fmt.lang.value) }), fmt.range(range)].filter(Boolean).join(' · ') : undefined"
          :loading="query.isPending.value"
          :error="query.error.value"
          :retry="() => query.refetch()"
          :empty="!hasValues"
          :empty-text="t('routines.readings.chartEmpty')"
          height="260px"
        >
          <template v-if="keyOptions.length > 1" #actions>
            <SegmentedControl v-model="key" :options="keyOptions" size="sm" :aria-label="t('routines.readings.which')" />
          </template>
          <EChartAsync v-if="option" :option="option" height="260px" :label="spec?.label" />
        </ChartCard>
      </div>

      <div class="ui-card overflow-hidden">
        <div v-if="query.isPending.value" class="flex flex-col gap-2 p-4"><SkeletonBlock v-for="n in 4" :key="n" height="26px" /></div>
        <p v-else-if="!rows.length" class="flex items-center gap-2 p-4 text-sm text-muted"><Thermometer :size="15" aria-hidden="true" />{{ t("routines.readings.noRows") }}</p>
        <div v-else class="max-h-[420px] overflow-auto">
          <table class="w-full min-w-[640px] text-sm">
            <thead class="sticky top-0 bg-surface-2 text-left text-xs font-medium text-muted">
              <tr>
                <th class="px-4 py-2.5 font-medium">{{ t("routines.readings.col.when") }}</th>
                <th class="px-3 py-2.5 font-medium">{{ t("routines.readings.col.reading") }}</th>
                <th class="px-3 py-2.5 text-right font-medium">{{ t("routines.readings.col.value") }}</th>
                <th class="px-3 py-2.5 font-medium">{{ t("routines.readings.col.allowed") }}</th>
                <th class="px-3 py-2.5 font-medium">{{ t("routines.readings.col.who") }}</th>
                <th class="px-4 py-2.5 font-medium">{{ t("routines.readings.col.note") }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in rows" :key="row.id" class="border-t border-line" :data-in-range="row.in_range">
                <td class="whitespace-nowrap px-4 py-2 tabular-nums">
                  {{ fmt.day(row.day, "short") }} · {{ row.time }}
                  <span v-if="row.is_recheck" class="ml-1 rounded-full bg-success-soft px-1.5 py-px text-xs font-medium text-success">{{ t("routines.readings.recheck") }}</span>
                </td>
                <td class="px-3 py-2 text-muted">{{ row.label }}</td>
                <td :class="['whitespace-nowrap px-3 py-2 text-right font-semibold tabular-nums', row.in_range ? 'text-fg' : 'text-danger']">{{ valueText(row.value, row.unit, fmt.lang.value) }}</td>
                <td class="whitespace-nowrap px-3 py-2 text-muted">{{ rangeText(row.min, row.max, row.unit, fmt.lang.value) }}</td>
                <td class="px-3 py-2">{{ row.recorded_by?.name ?? "" }}</td>
                <td class="px-4 py-2 text-muted">{{ row.note }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
      <p v-if="data?.missed.length" class="text-sm text-muted">
        {{ t("routines.readings.missedDays", { days: data.missed.map((day) => fmt.day(day, "short")).join(", ") }) }}
      </p>
    </div>
  </PageSection>
</template>
