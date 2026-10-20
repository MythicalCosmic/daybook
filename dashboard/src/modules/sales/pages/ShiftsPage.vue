<script setup lang="ts">
/**
 * Cashier shifts (plan §6.2): built-in views (To verify, Differences, Open now, Disputed, All) plus
 * saved ones, filters in the URL, a dense table with the difference in red or green, and the
 * shift drawer (`?shift=`). On phones the table becomes cards.
 */
import { AlertTriangle, Building2, CircleDot, ClipboardList, Sparkles, UserRound } from "@lucide/vue";
import { computed, onMounted, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import DataTable from "@/components/DataTable.vue";
import FilterBar from "@/components/FilterBar.vue";
import { useUrlFilters, type FilterDef } from "@/components/filters";
import MoneyText from "@/components/MoneyText.vue";
import PageHeader from "@/components/PageHeader.vue";
import PersonCell from "@/components/PersonCell.vue";
import SavedViewsTabs, { type ViewTab } from "@/components/SavedViewsTabs.vue";
import StatusPill from "@/components/StatusPill.vue";
import type { TableColumn } from "@/components/table";
import UiBadge from "@/components/UiBadge.vue";
import { useDataTable } from "@/components/useDataTable";
import { counter, pulse } from "@/core/pulse";
import { paramsDiffer, useSavedViews } from "@/lib/useSavedViews";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useFormat } from "@/lib/useFormat";

import { useOptions, useSettings, useShifts } from "../api";
import ShiftDrawer from "../components/ShiftDrawer.vue";
import { SHIFT_TONES, differenceClass, differenceLevel } from "../format";
import type { ShiftRow } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const route = useRoute();
const router = useRouter();
const options = useOptions();
const settings = useSettings();
const tolerance = computed(() => settings.data.value?.cash_tolerance ?? options.data.value?.settings.cash_tolerance ?? "0");

const defs = computed<FilterDef[]>(() => [
  { key: "branch", label: t("sales.filter.branch"), type: "multi", icon: Building2, options: (options.data.value?.branches ?? []).map((b) => ({ value: String(b.id), label: b.name, description: b.code })) },
  {
    key: "cashier",
    label: t("sales.filter.cashier"),
    type: "select",
    icon: UserRound,
    options: (options.data.value?.cashiers ?? []).map((c) => ({ value: String(c.id), label: c.name, avatar: { name: c.name } })),
  },
  {
    key: "status",
    label: t("sales.filter.status"),
    type: "multi",
    icon: CircleDot,
    options: (["open", "closed", "verified", "disputed"] as const).map((s) => ({ value: s, label: t(`sales.status.${s}`), color: `var(--c-${{ open: "info", closed: "warning", verified: "success", disputed: "danger" }[s]})` })),
  },
  { key: "day", label: t("sales.filter.day"), type: "date-range", params: ["from", "to"] },
  { key: "has_difference", label: t("sales.filter.difference"), type: "boolean", icon: AlertTriangle, trueLabel: t("sales.filter.withDifference"), falseLabel: t("sales.filter.noDifference") },
  { key: "mismatch", label: t("sales.filter.mismatch"), type: "boolean", icon: Sparkles, trueLabel: t("common.yes"), falseLabel: t("common.no") },
]);
const filters = useUrlFilters(defs);
const search = useRouteState<string>("q", rs.string(""));
const table = useDataTable({ id: "sales.shifts", ordering: "-opened_at", url: true, hidden: ["receipts", "verified_by", "branch"] });
watch([() => filters.params.value, search], () => table.resetPage(), { deep: true });

// Views: built-in ones set the filters; saved ones store them.
type BuiltinView = ViewTab & { params: Record<string, string | string[]> };
const builtin = (id: string, name: string, params: Record<string, string | string[]>, count?: number): BuiltinView => ({ id, name, builtin: true, count, params });
const BUILTIN = computed<BuiltinView[]>(() => [
  builtin("verify", t("sales.view.verify"), { status: ["closed"] }, counter("sales.to_verify")(pulse.value) || undefined),
  builtin("difference", t("sales.view.difference"), { has_difference: "true" }),
  builtin("open", t("sales.view.open"), { status: ["open"] }),
  builtin("disputed", t("sales.view.disputed"), { status: ["disputed"] }),
  builtin("all", t("sales.view.all"), {}),
]);
const saved = useSavedViews("sales.shifts");
const views = computed<ViewTab[]>(() => [...BUILTIN.value, ...saved.tabs.value]);
const view = useRouteState<string>("view", rs.string("all"));
const activeView = computed<ViewTab["id"]>({
  get: () => (/^\d+$/.test(view.value) ? Number(view.value) : view.value),
  set: (id) => {
    const builtin = BUILTIN.value.find((v) => v.id === id);
    const state = builtin ? builtin.params : ((saved.find(id)?.state ?? {}) as Record<string, string | string[]>);
    const keys = ["branch", "cashier", "status", "from", "to", "has_difference", "mismatch", "q", "page"];
    const query: Record<string, string | string[] | undefined> = { ...route.query } as never;
    for (const key of keys) delete query[key];
    void router.replace({ query: { ...query, ...state, view: id === "all" ? undefined : String(id) } });
  },
});
const viewParams = computed<Record<string, unknown>>(() => {
  const builtin = BUILTIN.value.find((v) => v.id === activeView.value);
  if (builtin) return builtin.params;
  return saved.find(activeView.value)?.state ?? {};
});
const current = computed<Record<string, unknown>>(() => ({ ...filters.params.value, ...(search.value ? { q: search.value } : {}) }));
const dirty = computed(() => paramsDiffer(current.value, viewParams.value));

async function saveView(input: { name: string; shared: boolean }): Promise<void> {
  const created = await saved.create.mutateAsync({ name: input.name, state: current.value, is_shared: input.shared });
  activeView.value = created.id;
}

const params = computed(() => ({ ...current.value, ...table.params.value }));
const query = useShifts(params);
const rows = computed(() => query.data.value?.results);

const columns = computed<TableColumn<ShiftRow>[]>(() => [
  { id: "code", header: t("sales.col.shift"), sortable: "number", width: 150, hideable: false, sticky: true },
  { id: "business_day", header: t("sales.col.day"), sortable: true, width: 132, format: (v) => fmt.day(String(v), "short") },
  { id: "cashier", header: t("sales.col.cashier"), minWidth: 190, value: (row) => row.cashier.name },
  { id: "branch", header: t("sales.col.branch"), width: 130, value: (row) => row.branch.name },
  { id: "status", header: t("sales.col.status"), width: 130 },
  { id: "net", header: t("sales.col.net"), sortable: true, numeric: true, width: 150, csv: (row) => row.net },
  { id: "receipts", header: t("sales.col.receipts"), numeric: true, width: 100 },
  { id: "counted_cash", header: t("sales.col.counted"), numeric: true, width: 150, csv: (row) => row.counted_cash },
  { id: "difference", header: t("sales.col.difference"), sortable: true, numeric: true, width: 140, csv: (row) => row.difference },
  { id: "verified_by", header: t("sales.col.verifiedBy"), width: 160, value: (row) => row.verified_by?.name ?? "" },
]);

const activeShift = computed(() => {
  const raw = route.query.shift;
  const value = Array.isArray(raw) ? raw[0] : raw;
  return value ? Number(value) : null;
});
function openShift(row: ShiftRow): void {
  void router.push({ query: { ...route.query, shift: String(row.id) } });
}
const filtered = computed(() => filters.active.value > 0 || !!search.value);

// A link to a built-in view without its filters (?view=verify from the palette or a
// notification) gets them, so the list matches the tab.
onMounted(() => {
  const builtinView = BUILTIN.value.find((v) => v.id === view.value);
  if (builtinView && view.value !== "all" && !filters.active.value) activeView.value = builtinView.id;
});
</script>

<template>
  <div>
    <PageHeader :title="t('sales.shifts.title')" :description="t('sales.shifts.description')" />
    <div class="flex flex-col gap-3">
      <SavedViewsTabs
        v-model="activeView"
        :views="views"
        :dirty="dirty"
        @save="saveView"
        @update="(v) => saved.update.mutate({ id: Number(v.id), state: current })"
        @rename="(v, name) => saved.update.mutate({ id: Number(v.id), name })"
        @share="(v, shared) => saved.update.mutate({ id: Number(v.id), is_shared: shared })"
        @delete="(v) => (saved.remove.mutate(Number(v.id)), (activeView = 'all'))"
      />
      <DataTable
        :state="table"
        :columns="columns"
        :rows="rows"
        :total="query.data.value?.count"
        row-key="id"
        clickable
        :active-key="activeShift"
        :loading="query.isPending.value"
        :fetching="query.isFetching.value"
        :error="query.error.value"
        :retry="() => query.refetch()"
        :filtered="filtered"
        :empty-title="t('sales.shifts.emptyTitle')"
        :empty-description="t('sales.shifts.emptyBody')"
        :empty-icon="ClipboardList"
        export-kind="sales.shifts"
        :export-params="current"
        :row-class="(row) => (row.status === 'disputed' ? 'bg-danger-soft/25' : undefined)"
        @row-click="openShift"
        @clear-filters="(filters.clear(), (search = ''))"
      >
        <template #toolbar>
          <FilterBar v-model="filters.values.value" v-model:search="search" :defs="defs" searchable :search-placeholder="t('sales.shifts.search')" />
        </template>
        <template #cell-code="{ row }">
          <span class="flex min-w-0 flex-col">
            <span class="flex items-center gap-1.5 font-semibold text-fg">
              {{ row.code }}
              <Sparkles v-if="row.ai_mismatch" :size="13" class="text-warning" :aria-label="t('sales.filter.mismatch')" />
            </span>
            <span class="truncate text-xs text-muted">{{ row.branch.name }} · {{ row.register.name }}</span>
          </span>
        </template>
        <template #cell-cashier="{ row }">
          <PersonCell :person="row.cashier" size="sm" :subtitle="fmt.instant(row.opened_at, 'time') + (row.closed_at ? ` – ${fmt.instant(row.closed_at, 'time')}` : '')" />
        </template>
        <template #cell-status="{ row }">
          <span class="flex items-center gap-1.5">
            <StatusPill size="sm" :tone="SHIFT_TONES[row.status]" :label="t(`sales.status.${row.status}`)" :live="row.status === 'open'" />
            <UiBadge v-if="row.forced" size="sm" tone="warning">{{ t("sales.shift.forcedShort") }}</UiBadge>
          </span>
        </template>
        <template #cell-net="{ row }"><MoneyText :value="row.net" class="font-semibold" /></template>
        <template #cell-counted_cash="{ row }"><MoneyText :value="row.counted_cash" /></template>
        <template #cell-difference="{ row }">
          <span :class="['font-semibold tabular-nums', differenceClass(differenceLevel(row.difference, tolerance))]">
            <MoneyText v-if="row.difference !== null" :value="row.difference" sign="always" />
            <span v-else>—</span>
          </span>
        </template>
        <template #card="{ row }">
          <div class="flex flex-col gap-2">
            <div class="flex items-start justify-between gap-3">
              <div class="min-w-0">
                <p class="flex items-center gap-1.5 text-base font-semibold text-fg">{{ row.code }}<Sparkles v-if="row.ai_mismatch" :size="13" class="text-warning" /></p>
                <p class="truncate text-xs text-muted">{{ row.cashier.name }} · {{ row.branch.name }} · {{ fmt.day(row.business_day, "short") }}</p>
              </div>
              <StatusPill size="sm" :tone="SHIFT_TONES[row.status]" :label="t(`sales.status.${row.status}`)" />
            </div>
            <div class="flex items-end justify-between gap-3">
              <MoneyText :value="row.net" class="text-md font-semibold text-fg" />
              <span :class="['text-sm font-semibold tabular-nums', differenceClass(differenceLevel(row.difference, tolerance))]">
                <MoneyText v-if="row.difference !== null" :value="row.difference" sign="always" />
              </span>
            </div>
          </div>
        </template>
      </DataTable>
    </div>
    <ShiftDrawer />
  </div>
</template>
