<script setup lang="ts">
/**
 * Ko‘z › Alerts (docs/KOZ.md §6.5): every queue, empty counter and box that went offline, newest
 * first, with its photo, how long it lasted, its peaks and who went. Filters by branch, state, kind
 * and period live in the URL; a row opens the detail drawer (`?alert=`), where the video is.
 */
import { BellRing, Building2, CalendarRange, Hand, ListFilter, UsersRound, WifiOff } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import DataTable from "@/components/DataTable.vue";
import FilterBar from "@/components/FilterBar.vue";
import { useUrlFilters, type FilterDef } from "@/components/filters";
import PageHeader from "@/components/PageHeader.vue";
import RelativeTime from "@/components/RelativeTime.vue";
import StatusPill from "@/components/StatusPill.vue";
import type { TableColumn } from "@/components/table";
import { useDataTable } from "@/components/useDataTable";
import { useFormat } from "@/lib/useFormat";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useCompanyStore } from "@/stores/company";

import { useAlerts } from "../api";
import AlertDrawer from "../components/AlertDrawer.vue";
import { useSecondClock } from "../lib/clock";
import { formatSeconds } from "../lib/format";
import { formatClock } from "../lib/tracks";
import { ALERT_KINDS, type Alert, type AlertParams } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const clock = useSecondClock();

const branches = computed(() => company.current?.branches ?? []);
const defs = computed<FilterDef[]>(() => [
  ...(branches.value.length > 1 ? [{ key: "branch", label: t("vision.filter.branch"), type: "select" as const, icon: Building2, options: branches.value.map((b) => ({ value: String(b.id), label: b.name })) }] : []),
  { key: "state", label: t("vision.filter.state"), type: "select", icon: ListFilter, options: (["open", "resolved"] as const).map((value) => ({ value, label: t(`vision.state.${value}`) })) },
  { key: "kind", label: t("vision.filter.kind"), type: "select", icon: BellRing, options: ALERT_KINDS.map((value) => ({ value, label: t(`vision.alert.kind.${value}`) })) },
  { key: "period", label: t("vision.filter.period"), type: "date-range", icon: CalendarRange, params: ["from", "to"] },
]);
const filters = useUrlFilters(defs);
const table = useDataTable({ id: "vision.alerts", url: true, pageSize: 50, pageSizes: [25, 50, 100] });
const params = computed<AlertParams>(() => ({ ...(filters.params.value as AlertParams), page: table.page.value, page_size: table.pageSize.value }));
const query = useAlerts(params);
const alertId = useRouteState("alert", rs.optionalNumber(), { push: true });

const columns = computed<TableColumn<Alert>[]>(() => [
  { id: "what", header: t("vision.alerts.col.what"), minWidth: 260, hideable: false },
  { id: "where", header: t("vision.alerts.col.where"), minWidth: 170, value: (row) => [row.camera?.name, row.branch.name].filter(Boolean).join(" · ") },
  { id: "started", header: t("vision.alerts.col.started"), width: 170, value: (row) => row.started_at, csv: (row) => fmt.instant(row.started_at, "datetime") },
  { id: "duration", header: t("vision.alerts.col.duration"), width: 130, numeric: true, value: (row) => row.duration_s, csv: (row) => row.duration_s },
  { id: "peak", header: t("vision.alerts.col.peak"), width: 150, numeric: true, value: (row) => row.peak_queue },
  { id: "ack", header: t("vision.alerts.col.ack"), minWidth: 170, value: (row) => row.acknowledged_by?.name ?? "" },
]);

const ICONS = { queue: UsersRound, unattended: Hand, agent_offline: WifiOff } as const;
const TONES = { queue: "bg-warning-soft text-warning", unattended: "bg-danger-soft text-danger", agent_offline: "bg-surface-2 text-muted dark:bg-surface-3" } as const;

function lasted(row: Alert): string {
  if (row.state === "open") return formatClock(Math.max(0, (clock.value - new Date(row.started_at).getTime()) / 1000));
  return row.duration_s === null ? "—" : formatSeconds(row.duration_s, fmt.lang.value);
}
function peak(row: Alert): string {
  if (row.kind === "agent_offline" || row.peak_queue === null) return "—";
  return t("vision.alerts.peak", { n: row.peak_queue, wait: formatSeconds(row.peak_wait_s ?? 0, fmt.lang.value) });
}
</script>

<template>
  <div class="flex flex-col gap-4">
    <PageHeader :title="t('vision.alerts.title')" :description="t('vision.alerts.description')" class="!mb-0" />
    <DataTable
      :state="table"
      :columns="columns"
      :rows="query.data.value?.results"
      :total="query.data.value?.count"
      row-key="id"
      clickable
      :active-key="alertId"
      :loading="query.isPending.value"
      :fetching="query.isFetching.value"
      :error="query.error.value"
      :retry="() => query.refetch()"
      :filtered="filters.active.value > 0"
      :empty-title="t('vision.alerts.emptyTitle')"
      :empty-description="t('vision.alerts.emptyBody')"
      :empty-icon="BellRing"
      csv-name="koz-alerts"
      @row-click="(row: Alert) => (alertId = row.id)"
      @clear-filters="filters.clear()"
    >
      <template #toolbar><FilterBar v-model="filters.values.value" :defs="defs" /></template>
      <template #cell-what="{ row }">
        <span class="flex min-w-0 items-center gap-3">
          <span class="relative block h-9 w-16 shrink-0 overflow-hidden rounded-[7px] bg-surface-2 dark:bg-surface-3">
            <img v-if="row.photo_url" :src="row.photo_url" alt="" class="size-full object-cover" loading="lazy" />
            <span v-else :class="['grid size-full place-items-center', TONES[row.kind]]"><component :is="ICONS[row.kind]" :size="15" /></span>
          </span>
          <span class="min-w-0">
            <span class="flex items-center gap-1.5">
              <span :class="['grid size-5 shrink-0 place-items-center rounded-full', TONES[row.kind]]"><component :is="ICONS[row.kind]" :size="11" /></span>
              <span class="line-clamp-2 font-medium leading-tight text-fg">{{ t(`vision.alert.kind.${row.kind}`) }}</span>
            </span>
            <StatusPill v-if="row.state === 'open'" class="mt-0.5" size="sm" :tone="row.kind === 'unattended' ? 'danger' : 'warning'" live :label="t('vision.alerts.ongoing')" />
          </span>
        </span>
      </template>
      <template #cell-where="{ row }">
        <span class="flex min-w-0 flex-col">
          <span class="truncate text-fg">{{ row.camera?.name ?? "—" }}</span>
          <span class="truncate text-xs text-muted">{{ row.branch.name }}</span>
        </span>
      </template>
      <template #cell-started="{ row }">
        <span class="flex flex-col">
          <span class="tabular-nums text-fg">{{ fmt.instant(row.started_at, "short") }}</span>
          <RelativeTime :value="row.started_at" class="text-xs text-muted" />
        </span>
      </template>
      <template #cell-duration="{ row }">
        <span :class="['tabular-nums', row.state === 'open' ? 'font-semibold text-warning' : 'text-fg']">{{ lasted(row) }}</span>
      </template>
      <template #cell-peak="{ row }"><span class="tabular-nums text-fg">{{ peak(row) }}</span></template>
      <template #cell-ack="{ row }">
        <span v-if="row.acknowledged_by" class="truncate text-fg">{{ t("vision.alerts.ackBy", { name: row.acknowledged_by.name }) }}</span>
        <span v-else class="text-sm text-subtle">{{ row.kind === "agent_offline" ? "—" : t("vision.alerts.noAck") }}</span>
      </template>
      <template #card="{ row }">
        <div class="flex items-center gap-3">
          <span class="relative block h-12 w-20 shrink-0 overflow-hidden rounded-[8px] bg-surface-2 dark:bg-surface-3">
            <img v-if="row.photo_url" :src="row.photo_url" alt="" class="size-full object-cover" loading="lazy" />
            <span v-else :class="['grid size-full place-items-center', TONES[row.kind]]"><component :is="ICONS[row.kind]" :size="17" /></span>
          </span>
          <div class="min-w-0 flex-1">
            <p class="flex items-center gap-1.5 text-sm font-semibold text-fg">
              <span class="truncate">{{ t(`vision.alert.kind.${row.kind}`) }}</span>
              <StatusPill v-if="row.state === 'open'" size="sm" :tone="row.kind === 'unattended' ? 'danger' : 'warning'" live :label="t('vision.alerts.ongoing')" />
            </p>
            <p class="truncate text-xs text-muted">{{ [row.camera?.name, row.branch.name].filter(Boolean).join(" · ") }} · {{ fmt.instant(row.started_at, "short") }}</p>
            <p class="truncate text-xs text-muted">{{ lasted(row) }}<template v-if="row.kind !== 'agent_offline'"> · {{ peak(row) }}</template></p>
          </div>
        </div>
      </template>
    </DataTable>
    <AlertDrawer />
  </div>
</template>
