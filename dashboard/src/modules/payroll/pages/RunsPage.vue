<script setup lang="ts">
/**
 * Payroll runs (plan §6.2 "Runs list (regular and final) with projected cost this month"): the
 * next payroll as it stands, then every month's run with its status and totals; a month without
 * a run offers "Prepare November payroll". `?prepare=1` (the palette) opens the month choice.
 */
import { CalendarPlus, CircleDashed, Settings2, UserRoundMinus } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";

import DataTable from "@/components/DataTable.vue";
import EmptyState from "@/components/EmptyState.vue";
import KpiStrip from "@/components/KpiStrip.vue";
import PageHeader from "@/components/PageHeader.vue";
import StatusPill from "@/components/StatusPill.vue";
import type { TableColumn } from "@/components/table";
import UiButton from "@/components/UiButton.vue";
import { useDataTable } from "@/components/useDataTable";
import { todayIn } from "@/lib/dates";
import { useFormat } from "@/lib/useFormat";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useCompanyStore } from "@/stores/company";

import { useOverview, useRuns } from "../api";
import PayAmount from "../components/PayAmount.vue";
import PrepareDialog from "../components/PrepareDialog.vue";
import { monthName, prepareTarget, RUN_TONES } from "../lib";
import type { Run } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const router = useRouter();
const company = useCompanyStore();
const canManage = computed(() => company.can("payroll.manage"));
const today = computed(() => todayIn(company.timezone));

const runs = useRuns();
const overview = useOverview();
const table = useDataTable({ id: "payroll.runs", pageSize: 100 });
const rows = computed(() => [...(runs.data.value ?? [])].sort((a, b) => (a.period < b.period ? 1 : a.period > b.period ? -1 : b.id - a.id)));
const target = computed(() => (runs.data.value ? prepareTarget(runs.data.value, today.value) : null));
const targetLabel = computed(() => (target.value ? t("payroll.runs.prepareMonth", { month: monthName(target.value, fmt.lang.value) }) : ""));

const latestDone = computed(() => rows.value.find((run) => run.kind === "regular" && (run.status === "finalized" || run.status === "paid")) ?? null);
const kpis = computed(() => {
  const data = overview.data.value;
  const projected = data?.projected ?? null;
  const last = latestDone.value?.totals ?? null;
  // Bonuses and fines of the latest month with a run (this month's draft once there is one).
  const month = data?.months.at(-1) ?? null;
  const monthHint = month ? fmt.day(month.period, "monthYear") : t("payroll.kpi.noRun");
  return [
    {
      id: "next",
      label: t("payroll.kpi.next"),
      value: projected?.net ?? null,
      format: "money" as const,
      compact: true,
      currency: data?.currency,
      // A finalized month is its run's sums; otherwise it is worked out with today's data.
      hint: projected ? t(projected.source === "run" ? "payroll.kpi.nextHintRun" : "payroll.kpi.nextHint", { month: fmt.day(projected.period, "monthYear"), n: projected.people }, projected.people) : undefined,
      // A trend from three months on: two points say little and crowd the hint.
      spark: data && data.months.length > 2 ? data.months.map((row) => row.net) : undefined,
      loading: overview.isPending.value,
      error: overview.error.value,
      retry: () => overview.refetch(),
    },
    {
      id: "last",
      label: t("payroll.kpi.last"),
      value: last?.net ?? null,
      format: "money" as const,
      compact: true,
      currency: last?.currency,
      hint: latestDone.value ? fmt.day(latestDone.value.period, "monthYear") : t("payroll.kpi.lastNone"),
      loading: runs.isPending.value,
    },
    {
      id: "bonuses",
      label: t("payroll.kpi.bonuses"),
      value: month?.bonuses ?? null,
      format: "money" as const,
      compact: true,
      currency: data?.currency,
      hint: monthHint,
      loading: overview.isPending.value,
      error: overview.error.value,
    },
    {
      id: "fines",
      label: t("payroll.kpi.fines"),
      value: month?.fines ?? null,
      format: "money" as const,
      compact: true,
      currency: data?.currency,
      hint: monthHint,
      loading: overview.isPending.value,
      error: overview.error.value,
    },
  ];
});

function runTitle(run: Run): string {
  return run.kind === "final" ? t("payroll.run.finalTitle", { name: run.member?.name ?? "—" }) : fmt.day(run.period, "monthYear");
}

const columns = computed<TableColumn<Run>[]>(() => [
  { id: "period", header: t("payroll.runs.month"), minWidth: 200, sticky: true, hideable: false, value: (row) => runTitle(row) },
  { id: "status", header: t("payroll.runs.status"), width: 130, value: (row) => t(`payroll.runStatus.${row.status}`) },
  { id: "people", header: t("payroll.runs.people"), width: 92, numeric: true, value: (row) => row.totals?.people ?? null },
  { id: "gross", header: t("payroll.totals.gross"), width: 150, numeric: true, value: (row) => row.totals?.gross ?? null },
  { id: "deductions", header: t("payroll.totals.deductions"), width: 150, numeric: true, value: (row) => row.totals?.deductions ?? null },
  { id: "net", header: t("payroll.totals.net"), width: 160, numeric: true, value: (row) => row.totals?.net ?? null },
  { id: "when", header: t("payroll.runs.when"), width: 150, value: (row) => row.paid_at ?? row.finalized_at ?? row.calculated_at ?? "" },
]);

function whenText(run: Run): string {
  if (run.status === "paid" && run.paid_at) return t("payroll.runs.paidOn", { date: fmt.instant(run.paid_at, "date") });
  if (run.finalized_at) return t("payroll.runs.finalizedOn", { date: fmt.instant(run.finalized_at, "date") });
  if (run.calculated_at) return t("payroll.runs.calculatedAt", { date: fmt.relative(run.calculated_at) });
  return t("payroll.runs.notCalculated");
}

/** The table's last column: when the status last moved (the pill beside it says how). */
function whenShort(run: Run): string {
  if (run.status === "paid" && run.paid_at) return fmt.instant(run.paid_at, "date");
  if (run.finalized_at) return fmt.instant(run.finalized_at, "date");
  if (run.calculated_at) return fmt.relative(run.calculated_at);
  return t("payroll.runs.notCalculated");
}

function open(run: Run): void {
  void router.push(`/c/${company.currentId}/payroll/runs/${run.id}`);
}

// "Prepare" from the header, the empty month card, or the palette (?prepare=1).
const prepareOpen = ref(false);
const prepareParam = useRouteState("prepare", rs.boolean(false));
watch(
  prepareParam,
  (value) => {
    if (!value) return;
    prepareParam.value = false;
    if (canManage.value) prepareOpen.value = true;
  },
  { immediate: true },
);
</script>

<template>
  <div>
    <PageHeader :title="t('payroll.runs.title')" :description="t('payroll.runs.description')">
      <template #actions>
        <UiButton v-if="canManage" variant="ghost" :icon="Settings2" :to="`/c/${company.currentId}/settings/payroll`">{{ t("payroll.runs.settings") }}</UiButton>
        <UiButton v-if="canManage" variant="primary" :icon="CalendarPlus" data-testid="prepare" @click="prepareOpen = true">{{ target ? targetLabel : t("payroll.runs.prepare") }}</UiButton>
      </template>
    </PageHeader>

    <KpiStrip class="mb-5" :items="kpis" :columns="4" phone="compact" />

    <button
      v-if="canManage && target && rows.length"
      type="button"
      class="mb-4 flex w-full items-center gap-3 rounded-[12px] border border-dashed border-line-strong bg-surface px-4 py-3 text-left transition-colors hover:border-primary hover:bg-accent-soft"
      data-testid="prepare-card"
      @click="prepareOpen = true"
    >
      <span class="grid size-9 shrink-0 place-items-center rounded-[10px] bg-surface-2 text-muted"><CircleDashed :size="18" /></span>
      <span class="min-w-0 flex-1">
        <span class="block text-base font-semibold text-fg">{{ fmt.day(target, "monthYear") }}</span>
        <span class="block text-sm text-muted">{{ t("payroll.runs.notPrepared") }}</span>
      </span>
      <span class="shrink-0 text-sm font-semibold text-accent-fg">{{ t("payroll.runs.prepare") }}</span>
    </button>

    <DataTable
      :state="table"
      :columns="columns"
      :rows="rows"
      row-key="id"
      :loading="runs.isPending.value"
      :fetching="runs.isFetching.value"
      :error="runs.error.value"
      :retry="() => runs.refetch()"
      clickable
      hide-pagination
      csv-name="payroll-runs"
      @row-click="open"
    >
      <template #empty>
        <EmptyState :icon="CalendarPlus" :title="t('payroll.runs.emptyTitle')" :description="canManage ? t('payroll.runs.emptyBody') : t('payroll.runs.emptyBodyView')">
          <UiButton v-if="canManage" variant="primary" :icon="CalendarPlus" @click="prepareOpen = true">{{ target ? targetLabel : t("payroll.runs.prepare") }}</UiButton>
        </EmptyState>
      </template>
      <template #cell-period="{ row }">
        <div class="flex min-w-0 items-center gap-2.5">
          <span v-if="row.kind === 'final'" class="grid size-8 shrink-0 place-items-center rounded-[9px] bg-warning-soft text-warning" :title="t('payroll.run.final')"><UserRoundMinus :size="16" /></span>
          <div class="min-w-0">
            <p class="truncate text-base font-semibold text-fg">{{ runTitle(row) }}</p>
            <p v-if="row.kind === 'final'" class="truncate text-xs text-muted">{{ fmt.day(row.period, "monthYear") }}</p>
            <p v-else-if="row.warnings.length && row.status === 'draft'" class="truncate text-xs font-medium text-warning">{{ t("payroll.run.warningsCount", { n: row.warnings.length }, row.warnings.length) }}</p>
          </div>
        </div>
      </template>
      <template #cell-status="{ row }"><StatusPill :tone="RUN_TONES[row.status]" size="sm" :label="t(`payroll.runStatus.${row.status}`)" /></template>
      <template #cell-people="{ row }"><span class="tabular-nums text-fg">{{ row.totals?.people ?? "—" }}</span></template>
      <template #cell-gross="{ row }"><PayAmount cell :value="row.totals?.gross" :currency="row.totals?.currency" /></template>
      <template #cell-deductions="{ row }"><PayAmount cell :value="row.totals?.deductions" :currency="row.totals?.currency" /></template>
      <template #cell-net="{ row }"><PayAmount cell strong :value="row.totals?.net" :currency="row.totals?.currency" /></template>
      <template #cell-when="{ row }"><span class="truncate text-sm text-muted" :title="whenText(row)">{{ whenShort(row) }}</span></template>
      <template #card="{ row }">
        <div class="flex items-start gap-3">
          <div class="min-w-0 flex-1">
            <div class="flex min-w-0 items-center gap-2">
              <p class="truncate text-base font-semibold text-fg">{{ runTitle(row) }}</p>
              <StatusPill :tone="RUN_TONES[row.status]" size="sm" :label="t(`payroll.runStatus.${row.status}`)" />
            </div>
            <p class="mt-0.5 truncate text-xs text-muted">
              {{ t("payroll.runs.peopleCount", { n: row.totals?.people ?? 0 }, row.totals?.people ?? 0) }} · {{ whenText(row) }}
            </p>
            <p v-if="row.warnings.length && row.status === 'draft'" class="mt-0.5 text-xs font-medium text-warning">{{ t("payroll.run.warningsCount", { n: row.warnings.length }, row.warnings.length) }}</p>
          </div>
          <PayAmount cell strong :value="row.totals?.net" :currency="row.totals?.currency" />
        </div>
      </template>
    </DataTable>

    <PrepareDialog v-model:open="prepareOpen" :runs="runs.data.value ?? []" :suggested="target" />
  </div>
</template>
