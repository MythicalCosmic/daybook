<script setup lang="ts">
/**
 * One file of sale lines (plan §14.7): what it brought (receipts, matched and unmatched lines,
 * duplicates left out, rows that couldn't be read, lines above the legal price), the day check
 * against the tills' totals per branch and day, and the rows that couldn't be read. While the
 * file is being read the drawer asks again every two seconds.
 */
import { AlertTriangle, CheckCircle2, ListChecks } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import ErrorState from "@/components/ErrorState.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import KpiStrip from "@/components/KpiStrip.vue";
import MoneyText from "@/components/MoneyText.vue";
import PageSection from "@/components/PageSection.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import UiButton from "@/components/UiButton.vue";
import UiDrawer from "@/components/UiDrawer.vue";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { useImport } from "../api";
import { importTone } from "../format";

const props = defineProps<{ importId: number | null }>();
const emit = defineEmits<{ close: [] }>();
const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const query = useImport(() => props.importId);
const open = computed({
  get: () => props.importId !== null,
  set: (value: boolean) => {
    if (!value) emit("close");
  },
});
const row = computed(() => query.data.value);
const reading = computed(() => !!row.value && ["queued", "processing"].includes(row.value.status));
const kpis = computed(() => {
  const value = row.value;
  if (!value) return [];
  return [
    { id: "receipts", label: t("sales.import.col.receipts"), value: value.receipts },
    { id: "matched", label: t("sales.import.col.matched"), value: value.matched },
    { id: "unmatched", label: t("sales.import.col.unmatched"), value: value.unmatched },
    { id: "duplicates", label: t("sales.import.col.duplicates"), value: value.duplicates },
    { id: "breaches", label: t("sales.import.col.breaches"), value: value.breaches },
  ];
});
const flagged = computed(() => (row.value?.day_check ?? []).filter((day) => day.flagged).length);
const linesLink = computed(() => `/c/${company.currentId}/sales/lines?import=${props.importId}`);
const matchLink = computed(() => `/c/${company.currentId}/sales/import?tab=match`);
</script>

<template>
  <UiDrawer v-model:open="open" size="lg" :title="row ? row.profile.name : t('sales.import.title')" :description="row ? fmt.instant(row.created_at, 'short') : undefined">
    <div v-if="query.isPending.value" class="flex flex-col gap-3 p-5"><SkeletonBlock v-for="n in 3" :key="n" height="80px" radius="12px" /></div>
    <ErrorState v-else-if="query.isError.value" class="m-5" :error="query.error.value" :retry="() => query.refetch()" />
    <div v-else-if="row" class="flex flex-col gap-4 p-5 max-sm:p-4">
      <div class="flex flex-wrap items-center gap-2">
        <StatusPill :tone="importTone(row.status)" :label="t(`sales.import.status.${row.status}`)" :live="reading" />
        <span v-if="row.created_by" class="text-sm text-muted">{{ row.created_by.name }}</span>
      </div>
      <InlineAlert v-if="row.status === 'failed'" tone="danger" :title="t('sales.import.failedTitle')" :description="row.error" />
      <InlineAlert v-else-if="reading" tone="info" :description="t('sales.import.reading')" />
      <template v-else>
        <KpiStrip :items="kpis" :columns="5" phone="grid" />
        <InlineAlert v-if="row.unmatched" tone="warning" :title="t('sales.import.unmatchedTitle', { n: row.unmatched }, row.unmatched)" :description="t('sales.import.unmatchedBody')">
          <template #actions><UiButton size="sm" variant="secondary" :icon="ListChecks" :to="matchLink">{{ t("sales.import.openMatch") }}</UiButton></template>
        </InlineAlert>
        <InlineAlert v-if="row.breaches" tone="danger" :title="t('sales.import.breachesTitle', { n: row.breaches }, row.breaches)" :description="t('sales.import.breachesBody')">
          <template #actions><UiButton size="sm" variant="secondary" :to="`${linesLink}&cap=1`">{{ t("sales.import.openBreaches") }}</UiButton></template>
        </InlineAlert>

        <PageSection variant="card" :title="t('sales.import.dayCheck')" :description="t('sales.import.dayCheckHint')">
          <p v-if="!row.day_check.length" class="text-sm text-muted">{{ t("sales.import.noDays") }}</p>
          <div v-else class="overflow-x-auto">
            <table class="w-full min-w-[520px] text-sm">
              <thead>
                <tr class="text-start text-xs text-subtle">
                  <th class="pb-2 text-start font-medium">{{ t("sales.import.col.day") }}</th>
                  <th class="pb-2 text-start font-medium">{{ t("sales.col.branch") }}</th>
                  <th class="pb-2 text-end font-medium">{{ t("sales.import.col.imported") }}</th>
                  <th class="pb-2 text-end font-medium">{{ t("sales.import.col.tills") }}</th>
                  <th class="pb-2 text-end font-medium">{{ t("sales.import.col.coverage") }}</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-line">
                <tr v-for="day in row.day_check" :key="`${day.branch.id}-${day.day}`">
                  <td class="py-2">{{ fmt.day(day.day) }}</td>
                  <td class="py-2">{{ day.branch.name }}</td>
                  <td class="py-2 text-end tabular-nums"><MoneyText :value="day.imported" /></td>
                  <td class="py-2 text-end tabular-nums">
                    <MoneyText v-if="day.tills !== null" :value="day.tills" />
                    <span v-else class="text-subtle">{{ t("sales.import.noTills") }}</span>
                  </td>
                  <td class="py-2 text-end">
                    <span :class="['inline-flex items-center gap-1 tabular-nums', day.flagged ? 'font-semibold text-warning' : 'text-success']">
                      <component :is="day.flagged ? AlertTriangle : CheckCircle2" :size="14" />
                      {{ day.coverage !== null ? fmt.percent(Number(day.coverage), 1) : "—" }}
                    </span>
                  </td>
                </tr>
              </tbody>
            </table>
            <p v-if="flagged" class="mt-2 text-xs text-muted">{{ t("sales.import.flaggedHint", { n: flagged }, flagged) }}</p>
          </div>
        </PageSection>

        <PageSection v-if="row.problems.length || row.unreadable" variant="card" :title="t('sales.import.problems', { n: row.problems.length }, row.problems.length)">
          <ul class="flex flex-col gap-1.5 text-sm">
            <li v-for="(problem, index) in row.problems" :key="index" class="flex gap-2">
              <span v-if="problem.row" class="shrink-0 text-subtle tabular-nums">{{ t("sales.import.row", { n: problem.row }) }}</span>
              <span class="text-fg">{{ problem.message }}</span>
            </li>
          </ul>
        </PageSection>
        <div><UiButton variant="secondary" :to="linesLink">{{ t("sales.import.openLines") }}</UiButton></div>
      </template>
    </div>
  </UiDrawer>
</template>
