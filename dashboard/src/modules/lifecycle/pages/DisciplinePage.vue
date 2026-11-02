<script setup lang="ts">
/**
 * Discipline (plan §13.4): every warning and reprimand with its category (the pharmacy ones first),
 * the day it happened, the fine proposed to payroll, and whether the employee has read it and
 * explained; filters in the URL; the record on `?record=`; "New record" (`?new=1` opens it from the
 * palette). Without hr.discipline the page reads only.
 */
import { Banknote, CircleCheck, CircleDot, Gavel, MessageSquareQuote, Plus, Tags, Timer } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import DataTable from "@/components/DataTable.vue";
import EmptyState from "@/components/EmptyState.vue";
import FilterBar from "@/components/FilterBar.vue";
import { useUrlFilters, type FilterDef } from "@/components/filters";
import MoneyText from "@/components/MoneyText.vue";
import PageHeader from "@/components/PageHeader.vue";
import StatusPill from "@/components/StatusPill.vue";
import type { TableColumn } from "@/components/table";
import UiButton from "@/components/UiButton.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { useDataTable } from "@/components/useDataTable";
import { useFormat } from "@/lib/useFormat";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useCompanyStore } from "@/stores/company";

import { useRecords } from "../api";
import RecordDrawer from "../components/RecordDrawer.vue";
import RecordFormDrawer from "../components/RecordFormDrawer.vue";
import { KIND_TONES, lifecycleAccess, recordParams, recordState, STATE_TONES } from "../lib";
import { GENERAL_CATEGORIES, PHARMACY_CATEGORIES, RECORD_KINDS, RECORD_STATUSES, type DisciplinaryRecord } from "../types";

const { t, te } = useI18n();
const fmt = useFormat();
const route = useRoute();
const router = useRouter();
const company = useCompanyStore();
const access = computed(() => lifecycleAccess((perm) => company.can(perm)));

const search = useRouteState("q", rs.string(""));
const defs = computed<FilterDef[]>(() => [
  { key: "active", label: t("lifecycle.filter.active"), type: "boolean", icon: Timer, pinned: true, trueLabel: t("lifecycle.filter.activeYes"), falseLabel: t("common.all") },
  { key: "kind", label: t("lifecycle.field.kind"), type: "multi", icon: Gavel, options: RECORD_KINDS.map((kind) => ({ value: kind, label: t(`lifecycle.kind.${kind}`) })) },
  {
    key: "category",
    label: t("lifecycle.field.category"),
    type: "multi",
    icon: Tags,
    options: [
      ...PHARMACY_CATEGORIES.map((value) => ({ value, label: t(`lifecycle.category.${value}`), group: t("lifecycle.categoryGroup.pharmacy") })),
      ...GENERAL_CATEGORIES.map((value) => ({ value, label: t(`lifecycle.category.${value}`), group: t("lifecycle.categoryGroup.general") })),
    ],
  },
  {
    key: "status",
    label: t("lifecycle.field.status"),
    type: "multi",
    icon: CircleDot,
    options: RECORD_STATUSES.map((status) => ({ value: status, label: t(`lifecycle.status.${status}`) })),
  },
]);
const filters = useUrlFilters(defs);
const table = useDataTable({ id: "lifecycle.discipline", url: true });
table.resetPageOn(() => [filters.params.value, search.value]);

const params = computed(() => ({ ...recordParams(filters.values.value, search.value), ...table.params.value }));
const records = useRecords(params);
const filtered = computed(() => filters.active.value > 0 || !!search.value);
const category = (value: string) => (te(`lifecycle.category.${value}`) ? t(`lifecycle.category.${value}`) : value);

const columns = computed<TableColumn<DisciplinaryRecord>[]>(() => [
  { id: "member", header: t("lifecycle.field.person"), minWidth: 200, sticky: true, hideable: false, value: (row) => row.member.name },
  { id: "kind", header: t("lifecycle.field.kind"), width: 200, value: (row) => t(`lifecycle.kind.${row.kind}`) },
  { id: "category", header: t("lifecycle.field.category"), minWidth: 170, value: (row) => category(row.category) },
  { id: "incident_on", header: t("lifecycle.field.incidentOn"), width: 136, value: (row) => row.incident_on },
  { id: "fine", header: t("lifecycle.field.fine"), width: 120, numeric: true, value: (row) => row.fine?.amount ?? (row.fine_id ? "hidden" : "") },
  { id: "response", header: t("lifecycle.field.response"), width: 130, value: (row) => (row.employee_response ? "2" : row.acknowledged_at ? "1" : "") },
  { id: "status", header: t("lifecycle.field.status"), width: 150, value: (row) => row.status },
]);

function open(row: DisciplinaryRecord): void {
  void router.push({ query: { ...route.query, record: String(row.id) } });
}
const activeKey = computed(() => (typeof route.query.record === "string" ? route.query.record : null));

const creating = ref(false);
const newParam = useRouteState("new", rs.boolean(false));
watch(
  newParam,
  (value) => {
    if (!value) return;
    newParam.value = false;
    if (access.value.discipline) creating.value = true;
  },
  { immediate: true },
);
function created(record: DisciplinaryRecord): void {
  void router.push({ query: { ...route.query, record: String(record.id) } });
}
</script>

<template>
  <div>
    <PageHeader :title="t('lifecycle.nav.discipline')" :description="t('lifecycle.discipline.description')">
      <template v-if="access.discipline" #actions>
        <UiButton variant="primary" :icon="Plus" @click="creating = true">{{ t("lifecycle.record.new") }}</UiButton>
      </template>
    </PageHeader>

    <DataTable
      :state="table"
      :columns="columns"
      :rows="records.data.value?.results"
      :total="records.data.value?.count"
      row-key="id"
      :loading="records.isPending.value"
      :fetching="records.isFetching.value"
      :error="records.error.value"
      :retry="() => records.refetch()"
      clickable
      :active-key="activeKey"
      :filtered="filtered"
      @row-click="open"
      @clear-filters="
        filters.clear();
        search = '';
      "
    >
      <template #toolbar>
        <FilterBar v-model="filters.values.value" v-model:search="search" :defs="defs" searchable :search-placeholder="t('lifecycle.discipline.search')" />
      </template>
      <template #empty>
        <EmptyState :icon="Gavel" :tone="filtered ? 'primary' : 'success'" :title="filtered ? t('lifecycle.empty.noMatch') : t('lifecycle.discipline.emptyTitle')" :description="filtered ? t('lifecycle.empty.noMatchBody') : t('lifecycle.discipline.emptyBody')">
          <UiButton v-if="!filtered && access.discipline" :icon="Plus" @click="creating = true">{{ t("lifecycle.record.new") }}</UiButton>
        </EmptyState>
      </template>
      <template #cell-member="{ row }">
        <div class="flex min-w-0 items-center gap-2.5">
          <UserAvatar :name="row.member.name" :src="row.member.photo_url" :size="28" />
          <div class="min-w-0">
            <p class="truncate text-base font-medium text-fg" :title="row.member.name">{{ row.member.name }}</p>
            <p v-if="row.position" class="truncate text-xs text-muted">{{ row.position }}</p>
          </div>
        </div>
      </template>
      <template #cell-kind="{ row }"><StatusPill :tone="KIND_TONES[row.kind]" size="sm" :label="t(`lifecycle.kind.${row.kind}`)" /></template>
      <template #cell-category="{ row }"><span class="truncate text-sm text-fg" :title="category(row.category)">{{ category(row.category) }}</span></template>
      <template #cell-incident_on="{ row }"><span class="text-sm tabular-nums text-fg">{{ fmt.day(row.incident_on, "medium") }}</span></template>
      <template #cell-fine="{ row }">
        <span v-if="row.fine" class="inline-flex items-center gap-1.5 text-sm font-semibold tabular-nums text-fg"><Banknote :size="14" class="text-warning" aria-hidden="true" /><MoneyText :value="row.fine.amount" :currency="row.fine.currency" /></span>
        <!-- A fine was proposed, but its amount is for payroll.view only. -->
        <span v-else-if="row.fine_id" class="inline-flex items-center gap-1.5 text-sm text-muted" :title="t('lifecycle.record.fineHidden')"><Banknote :size="14" class="text-warning" aria-hidden="true" /><MoneyText value="0" hidden /></span>
        <span v-else class="text-sm text-subtle">—</span>
      </template>
      <template #cell-response="{ row }">
        <span v-if="row.employee_response" class="inline-flex items-center gap-1.5 text-sm text-info"><MessageSquareQuote :size="15" aria-hidden="true" />{{ t("lifecycle.record.explained") }}</span>
        <span v-else-if="row.acknowledged_at" class="inline-flex items-center gap-1.5 text-sm text-success"><CircleCheck :size="15" aria-hidden="true" />{{ t("lifecycle.record.read") }}</span>
        <span v-else class="text-sm text-subtle">{{ t("lifecycle.record.notRead") }}</span>
      </template>
      <template #cell-status="{ row }"><StatusPill :tone="STATE_TONES[recordState(row)]" size="sm" variant="outline" :label="t(`lifecycle.status.${recordState(row)}`)" /></template>
      <template #card="{ row }">
        <div class="flex items-start gap-3">
          <UserAvatar :name="row.member.name" :src="row.member.photo_url" :size="36" />
          <div class="min-w-0 flex-1">
            <div class="flex items-center gap-2">
              <p class="min-w-0 flex-1 truncate text-base font-semibold text-fg">{{ row.member.name }}</p>
              <span class="shrink-0 text-xs tabular-nums text-muted">{{ fmt.day(row.incident_on, "short") }}</span>
            </div>
            <p class="truncate text-sm text-muted">{{ category(row.category) }}</p>
            <div class="mt-1.5 flex flex-wrap items-center gap-1.5">
              <StatusPill :tone="KIND_TONES[row.kind]" size="sm" :label="t(`lifecycle.kind.${row.kind}`)" />
              <span v-if="row.fine" class="inline-flex items-center gap-1 rounded-full bg-warning-soft px-2 py-0.5 text-xs font-semibold tabular-nums text-warning"><Banknote :size="12" aria-hidden="true" /><MoneyText :value="row.fine.amount" :currency="row.fine.currency" compact /></span>
              <span v-if="row.employee_response" class="inline-flex items-center gap-1 text-xs text-info"><MessageSquareQuote :size="13" aria-hidden="true" />{{ t("lifecycle.record.explained") }}</span>
              <span v-else-if="row.acknowledged_at" class="inline-flex items-center gap-1 text-xs text-success"><CircleCheck :size="13" aria-hidden="true" />{{ t("lifecycle.record.read") }}</span>
            </div>
          </div>
        </div>
      </template>
    </DataTable>

    <RecordDrawer />
    <RecordFormDrawer v-model:open="creating" @saved="created" />
  </div>
</template>
