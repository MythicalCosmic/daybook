<script setup lang="ts">
/**
 * The register (Asosiy vositalar reestri): what the company owns, what it is worth today and
 * what it costs a month. KPIs on top, expenses that look like equipment and aren't an asset yet
 * ("turn into an asset"), filters, and one row per asset with its book value and the next thing
 * its upkeep needs. `?new=1` opens the form (the command palette, Get started).
 */
import { Boxes, PackagePlus, Receipt } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";

import DataTable from "@/components/DataTable.vue";
import EmptyState from "@/components/EmptyState.vue";
import ExportButton from "@/components/ExportButton.vue";
import KpiStrip from "@/components/KpiStrip.vue";
import MoneyText from "@/components/MoneyText.vue";
import PageHeader from "@/components/PageHeader.vue";
import SelectBox from "@/components/SelectBox.vue";
import StatusPill from "@/components/StatusPill.vue";
import type { TableColumn } from "@/components/table";
import TextInput from "@/components/TextInput.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import UiButton from "@/components/UiButton.vue";
import { useDataTable } from "@/components/useDataTable";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore, useCompanyToday } from "@/stores/company";

import { useCategories, useItems, usePurchases, useSummary } from "../api";
import AssetFormDialog from "../components/AssetFormDialog.vue";
import { categoryIcon, STATUS_TONES, upkeepTone } from "../lib";
import type { AssetRow, Purchase } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const router = useRouter();

const search = useRouteState("q", rs.string(""));
const status = useRouteState("status", rs.string(""));
const category = useRouteState("category", rs.string(""));
const disposed = useRouteState("disposed", rs.boolean(false));
const creating = useRouteState("new", rs.boolean(false));

const canManage = computed(() => company.can("assets.manage"));
const params = computed(() => ({
  q: search.value || undefined,
  status: status.value || undefined,
  category: category.value || undefined,
  disposed: disposed.value || undefined,
  branch: company.branchFilter.length === 1 ? company.branchFilter[0] : undefined,
}));
const items = useItems(params);
const summary = useSummary(computed(() => ({ branch: params.value.branch })));
const categories = useCategories();
const purchases = usePurchases(canManage);
const table = useDataTable({ id: "assets.register", pageSize: 100 });

const today = useCompanyToday();
const fromPurchase = ref<Purchase | null>(null);

const kpis = computed(() => {
  const data = summary.data.value;
  return [
    { id: "count", label: t("assets.kpi.count"), value: data?.count ?? null, format: "number" as const, hint: data?.low_value ? t("assets.kpi.lowValueHint", { n: data.low_value }) : undefined },
    { id: "cost", label: t("assets.kpi.cost"), value: data?.cost ?? null, format: "money" as const, compact: true },
    { id: "book", label: t("assets.kpi.book"), value: data?.book ?? null, format: "money" as const, compact: true, hint: t("assets.kpi.bookHint") },
    { id: "month", label: t("assets.kpi.thisMonth"), value: data?.this_month ?? null, format: "money" as const, hint: t("assets.kpi.thisMonthHint") },
    { id: "due", label: t("assets.kpi.upkeep"), value: data?.upkeep_due ?? null, format: "number" as const, to: `/c/${company.currentId}/assets/planning` },
  ];
});

const statusOptions = computed(() => (["in_use", "in_storage", "repair", "suspended", "disposed"] as const).map((value) => ({ value, label: t(`assets.status.${value}`) })));
const categoryOptions = computed(() => (categories.data.value ?? []).map((row) => ({ value: String(row.id), label: row.name })));
// The selects clear to null; the URL keeps "" for "any".
const statusModel = computed({ get: () => status.value || null, set: (value: string | null) => (status.value = value ?? "") });
const categoryModel = computed({ get: () => category.value || null, set: (value: string | null) => (category.value = value ?? "") });

const columns = computed<TableColumn<AssetRow>[]>(() => [
  { id: "number", header: t("assets.col.number"), width: 104, sticky: true },
  { id: "name", header: t("assets.col.name"), minWidth: 280 },
  { id: "branch", header: t("assets.col.branch"), value: (row) => row.branch?.name ?? "", minWidth: 130 },
  { id: "custodian", header: t("assets.col.custodian"), value: (row) => row.custodian?.name ?? "", minWidth: 140 },
  { id: "status", header: t("assets.col.status"), width: 140 },
  { id: "cost", header: t("assets.col.cost"), numeric: true, width: 136 },
  { id: "book_value", header: t("assets.col.book"), numeric: true, width: 136, hint: t("assets.col.bookHint") },
  { id: "monthly", header: t("assets.col.monthly"), numeric: true, width: 124, hint: t("assets.col.monthlyHint") },
  { id: "next_due", header: t("assets.col.next"), width: 170, value: (row) => row.next_due?.day ?? "" },
]);
const filtered = computed(() => Boolean(search.value || status.value || category.value || disposed.value));

function open(row: AssetRow): void {
  void router.push(`/c/${company.currentId}/assets/items/${row.id}`);
}

function turnIntoAsset(purchase: Purchase): void {
  fromPurchase.value = purchase;
  creating.value = true;
}

watch(creating, (value) => {
  if (!value) fromPurchase.value = null;
});

function saved(id: number): void {
  void router.push(`/c/${company.currentId}/assets/items/${id}`);
}
</script>

<template>
  <div>
    <PageHeader :title="t('assets.nav.items')" :description="t('assets.register.description')">
      <template #actions>
        <ExportButton kind="assets.register" :params="{ disposed: disposed || undefined }" />
        <UiButton v-if="canManage" variant="primary" :icon="PackagePlus" @click="creating = true">{{ t("assets.register.new") }}</UiButton>
      </template>
    </PageHeader>

    <KpiStrip class="mb-4" :items="kpis" :loading="summary.isPending.value" :columns="5" phone="grid" />

    <section v-if="canManage && purchases.data.value?.length" class="ui-card mb-4 flex flex-col gap-3 p-4" :aria-label="t('assets.purchases.title')">
      <div class="flex items-start gap-3">
        <span class="grid size-9 shrink-0 place-items-center rounded-[10px] bg-accent-soft text-accent-fg"><Receipt :size="18" aria-hidden="true" /></span>
        <div class="min-w-0">
          <h2 class="text-sm font-semibold text-fg">{{ t("assets.purchases.title", { n: purchases.data.value.length }) }}</h2>
          <p class="text-sm text-muted">{{ t("assets.purchases.body") }}</p>
        </div>
      </div>
      <ul class="flex flex-col divide-y divide-line">
        <li v-for="purchase in purchases.data.value.slice(0, 4)" :key="purchase.id" class="flex flex-wrap items-center gap-x-4 gap-y-1 py-2">
          <span class="w-24 text-sm text-muted tabular-nums">{{ fmt.day(purchase.occurred_on) }}</span>
          <span class="min-w-0 flex-1 truncate text-sm text-fg">{{ purchase.description || purchase.category || t("assets.purchases.noDescription") }}</span>
          <span class="text-sm font-semibold tabular-nums text-fg"><MoneyText :value="purchase.base_amount" decimals="never" /></span>
          <UiButton size="sm" variant="secondary" @click="turnIntoAsset(purchase)">{{ t("assets.purchases.turn") }}</UiButton>
        </li>
      </ul>
    </section>

    <div v-if="items.data.value && !items.data.value.length && !filtered" class="ui-card">
      <EmptyState :icon="Boxes" :title="t('assets.register.emptyTitle')" :description="t('assets.register.emptyBody')">
        <UiButton v-if="canManage" variant="primary" :icon="PackagePlus" @click="creating = true">{{ t("assets.register.new") }}</UiButton>
      </EmptyState>
    </div>

    <DataTable
      v-else
      :state="table"
      :columns="columns"
      :rows="items.data.value"
      :total="items.data.value?.length"
      row-key="id"
      :loading="items.isPending.value"
      :fetching="items.isFetching.value"
      :error="items.error.value"
      :retry="() => items.refetch()"
      clickable
      :filtered="filtered"
      csv-name="assets"
      @row-click="open"
      @clear-filters="
        search = '';
        status = '';
        category = '';
        disposed = false;
      "
    >
      <template #toolbar>
        <div class="flex flex-wrap items-center gap-2">
          <TextInput v-model="search" :debounce="300" type="search" size="sm" class="w-full sm:w-64" :placeholder="t('assets.filter.search')" clearable />
          <SelectBox v-model="statusModel" size="sm" class="w-44" :options="statusOptions" clearable :placeholder="t('assets.filter.anyStatus')" />
          <SelectBox v-model="categoryModel" size="sm" class="w-56" :options="categoryOptions" clearable :placeholder="t('assets.filter.anyCategory')" />
          <ToggleSwitch v-model="disposed" size="sm" :label="t('assets.filter.disposed')" />
        </div>
      </template>
      <template #cell-name="{ row }">
        <div class="flex min-w-0 items-center gap-2.5">
          <img v-if="row.photo_url" :src="row.photo_url" alt="" class="size-8 shrink-0 rounded-[8px] object-cover" loading="lazy" />
          <span v-else class="grid size-8 shrink-0 place-items-center rounded-[8px] bg-surface-2 text-muted"><component :is="categoryIcon(row.icon)" :size="16" aria-hidden="true" /></span>
          <span class="min-w-0">
            <span class="block truncate font-medium text-fg">{{ row.name }}</span>
            <span class="block truncate text-xs text-muted">{{ row.category.name }}</span>
          </span>
        </div>
      </template>
      <template #cell-status="{ row }">
        <StatusPill :tone="STATUS_TONES[row.status]" :label="t(`assets.status.${row.status}`)" size="sm" />
      </template>
      <template #cell-cost="{ row }"><MoneyText :value="row.cost" decimals="never" /></template>
      <template #cell-book_value="{ row }"><span class="font-semibold"><MoneyText :value="row.book_value" decimals="never" /></span></template>
      <template #cell-monthly="{ row }">
        <MoneyText v-if="Number(row.monthly) > 0" :value="row.monthly" decimals="never" />
        <span v-else class="text-subtle">—</span>
      </template>
      <template #cell-next_due="{ row }">
        <StatusPill v-if="row.next_due" :tone="upkeepTone(row.next_due.day, today)" variant="plain" size="sm" :label="`${t(`assets.upkeep.${row.next_due.what}`)} · ${fmt.day(row.next_due.day)}`" />
        <span v-else class="text-subtle">—</span>
      </template>
    </DataTable>

    <AssetFormDialog v-model:open="creating" :purchase="fromPurchase" @saved="saved" />
  </div>
</template>
