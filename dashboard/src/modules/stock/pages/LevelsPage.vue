<script setup lang="ts">
/**
 * Stock by pharmacy (Qoldiqlar): what each branch holds of each item, how much of it is on sale
 * (not expired, in quarantine or recalled), a shortfall waiting for its delivery, the minimum and
 * maximum, and the nearest expiry. Filters: low, below zero, prescription, controlled, storage,
 * the mandatory list. A row opens the item's batches; `?opening=1` the opening stock form.
 */
import { Boxes, PackageOpen, SlidersHorizontal } from "@lucide/vue";
import { computed, reactive, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";

import DataTable from "@/components/DataTable.vue";
import EmptyState from "@/components/EmptyState.vue";
import FormField from "@/components/FormField.vue";
import IconButton from "@/components/IconButton.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import KpiStrip from "@/components/KpiStrip.vue";
import MoneyText from "@/components/MoneyText.vue";
import NumberInput from "@/components/NumberInput.vue";
import PageHeader from "@/components/PageHeader.vue";
import SelectBox from "@/components/SelectBox.vue";
import StatusPill from "@/components/StatusPill.vue";
import type { TableColumn } from "@/components/table";
import TextInput from "@/components/TextInput.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { useDataTable } from "@/components/useDataTable";
import { toast } from "@/components/useToast";
import { patchQuery, rs, useRouteState } from "@/lib/useRouteState";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore, useCompanyToday } from "@/stores/company";

import { stockApi, useLevels, useRefresh, useSummary } from "../api";
import OpeningDialog from "../components/OpeningDialog.vue";
import ProductBadges from "../components/ProductBadges.vue";
import ProductDrawer from "../components/ProductDrawer.vue";
import { expiryTone, num, packsAndParts, qtyText } from "../lib";
import { STORAGES, type Level } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const router = useRouter();
const today = useCompanyToday();
const refresh = useRefresh();

const search = useRouteState("q", rs.string(""));
const low = useRouteState("low", rs.boolean(false));
const negative = useRouteState("negative", rs.boolean(false));
const rx = useRouteState("rx", rs.boolean(false));
const control = useRouteState("control", rs.boolean(false));
const mandatory = useRouteState("mandatory", rs.boolean(false));
const storage = useRouteState("storage", rs.string(""));
const opening = useRouteState("opening", rs.boolean(false));

const branch = computed(() => (company.branchFilter.length === 1 ? company.branchFilter[0] : undefined));
const params = computed(() => ({
  branch: branch.value,
  q: search.value || undefined,
  low: low.value || undefined,
  negative: negative.value || undefined,
  rx: rx.value ? "true" : undefined,
  control: control.value || undefined,
  mandatory: mandatory.value || undefined,
  storage: storage.value || undefined,
}));
const levels = useLevels(params);
const summary = useSummary(computed(() => ({ branch: branch.value })));
const table = useDataTable({ id: "stock.levels", pageSize: 500 });
const canManage = computed(() => company.can("stock.manage"));

const storageOptions = computed(() => STORAGES.map((value) => ({ value, label: t(`stock.storage.${value}`) })));
const storageModel = computed({ get: () => storage.value || null, set: (value: string | null) => (storage.value = value ?? "") });

const kpis = computed(() => {
  const data = summary.data.value;
  const cost = data?.stock_value !== undefined;
  return [
    { id: "products", label: t("stock.kpi.products"), value: data?.products ?? null, format: "number" as const },
    { id: "low", label: t("stock.kpi.low"), value: data?.low ?? null, format: "number" as const, hint: t("stock.kpi.lowHint") },
    { id: "negative", label: t("stock.kpi.negative"), value: data?.negative ?? null, format: "number" as const, hint: t("stock.kpi.negativeHint") },
    {
      id: "value",
      label: cost ? t("stock.kpi.valueCost") : t("stock.kpi.valueRetail"),
      value: (cost ? data?.stock_value : data?.stock_retail_value) ?? null,
      format: "money" as const,
      compact: true,
    },
  ];
});

const hasCost = computed(() => (levels.data.value ?? []).some((row) => row.value !== undefined));
const columns = computed<TableColumn<Level>[]>(() => [
  { id: "product", header: t("stock.col.name"), minWidth: 280, sticky: true, value: (row) => row.product.name },
  { id: "branch", header: t("stock.col.branch"), minWidth: 120, value: (row) => row.branch.name },
  // "9 qadoq 1 blister" fits; the limits column is a button.
  { id: "quantity", header: t("stock.col.onHand"), numeric: true, width: 150 },
  { id: "sellable", header: t("stock.col.onSale"), numeric: true, width: 150, hint: t("stock.col.onSaleHint") },
  { id: "limits", header: t("stock.col.limits"), width: 100 },
  { id: "nearest_expiry", header: t("stock.col.nearestExpiry"), width: 140 },
  { id: "sale_price", header: t("stock.col.price"), numeric: true, width: 120 },
  ...(hasCost.value ? [{ id: "value", header: t("stock.col.valueCost"), numeric: true, width: 140 } as TableColumn<Level>] : []),
]);
const filtered = computed(() => Boolean(search.value || low.value || negative.value || rx.value || control.value || mandatory.value || storage.value));
const qty = (row: Level, value: string | null) => packsAndParts(value, row.units_per_pack, row.part_label, t);

function open(row: Level): void {
  patchQuery(router, { product: String(row.product.id) });
}

const limits = ref<Level | null>(null);
const limitForm = reactive({ min: null as number | null, max: null as number | null });
const savingLimits = ref(false);
function editLimits(row: Level): void {
  limits.value = row;
  limitForm.min = row.min_qty === null ? null : num(row.min_qty);
  limitForm.max = row.max_qty === null ? null : num(row.max_qty);
}
async function saveLimits(): Promise<void> {
  if (!limits.value) return;
  savingLimits.value = true;
  try {
    await stockApi.setLimits(company.currentId ?? 0, limits.value.id, {
      min_qty: limitForm.min === null ? null : String(limitForm.min),
      max_qty: limitForm.max === null ? null : String(limitForm.max),
    });
    toast.success(t("stock.levels.limitsSaved"));
    refresh();
    limits.value = null;
  } finally {
    savingLimits.value = false;
  }
}

function clear(): void {
  search.value = "";
  low.value = false;
  negative.value = false;
  rx.value = false;
  control.value = false;
  mandatory.value = false;
  storage.value = "";
}
</script>

<template>
  <div>
    <PageHeader :title="t('stock.nav.levels')" :description="t('stock.levels.description')">
      <template #actions>
        <UiButton v-if="canManage" variant="secondary" :icon="PackageOpen" @click="opening = true">{{ t("stock.levels.opening") }}</UiButton>
      </template>
    </PageHeader>

    <KpiStrip class="mb-4" :items="kpis" :loading="summary.isPending.value" :columns="4" phone="grid" />
    <InlineAlert v-if="summary.data.value?.estimate" class="mb-4" tone="neutral" size="sm">{{ t("stock.levels.estimate") }}</InlineAlert>

    <div v-if="levels.data.value && !levels.data.value.length && !filtered" class="ui-card">
      <EmptyState :icon="Boxes" :title="t('stock.levels.emptyTitle')" :description="t('stock.levels.emptyBody')">
        <UiButton v-if="canManage" variant="primary" :icon="PackageOpen" @click="opening = true">{{ t("stock.levels.opening") }}</UiButton>
      </EmptyState>
    </div>

    <DataTable
      v-else
      :state="table"
      :columns="columns"
      :rows="levels.data.value"
      row-key="id"
      :loading="levels.isPending.value"
      :fetching="levels.isFetching.value"
      :error="levels.error.value"
      :retry="() => levels.refetch()"
      clickable
      hide-pagination
      :filtered="filtered"
      csv-name="stock"
      export-kind="inventory.levels"
      :export-params="{ branch }"
      @row-click="open"
      @clear-filters="clear"
    >
      <template #toolbar>
        <div class="flex flex-wrap items-center gap-2">
          <TextInput v-model="search" :debounce="300" type="search" size="sm" class="w-full sm:w-64" :placeholder="t('stock.filter.search')" clearable />
          <ToggleSwitch v-model="low" size="sm" :label="t('stock.filter.low')" />
          <ToggleSwitch v-model="negative" size="sm" :label="t('stock.filter.negative')" />
          <ToggleSwitch v-model="rx" size="sm" :label="t('stock.filter.rxOnly')" />
          <ToggleSwitch v-model="control" size="sm" :label="t('stock.filter.controlled')" />
          <ToggleSwitch v-model="mandatory" size="sm" :label="t('stock.filter.mandatory')" />
          <SelectBox v-model="storageModel" size="sm" class="w-44" :options="storageOptions" clearable :placeholder="t('stock.filter.anyStorage')" />
        </div>
      </template>
      <template #cell-product="{ row }">
        <span class="flex min-w-0 flex-col gap-0.5">
          <span class="line-clamp-2 font-medium leading-snug text-fg" :title="row.product.name">{{ row.product.name }}</span>
          <ProductBadges :rx="row.rx_required" :control="row.control_class" :storage="row.storage" :mandatory="row.mandatory_list" />
        </span>
      </template>
      <template #cell-quantity="{ row }">
        <span :class="num(row.quantity) < 0 ? 'font-medium text-danger' : 'text-fg'">{{ qty(row, row.quantity) }}</span>
        <span v-if="num(row.shortfall) > 0" class="block text-xs text-danger">{{ t("stock.levels.waiting") }}</span>
      </template>
      <template #cell-sellable="{ row }">
        <span :class="num(row.sellable) < num(row.quantity) ? 'text-warning' : 'text-muted'">{{ qty(row, row.sellable) }}</span>
      </template>
      <template #cell-limits="{ row }">
        <span class="flex items-center gap-1.5">
          <StatusPill v-if="row.low" tone="warning" size="sm" :label="t('stock.levels.low')" />
          <span v-else-if="row.min_qty !== null || row.max_qty !== null" class="text-xs text-muted tabular-nums">{{ row.min_qty !== null ? qtyText(row.min_qty) : "—" }} / {{ row.max_qty !== null ? qtyText(row.max_qty) : "—" }}</span>
          <IconButton v-if="canManage" :icon="SlidersHorizontal" size="sm" :label="t('stock.levels.setLimits')" @click.stop="editLimits(row)" />
        </span>
      </template>
      <template #cell-nearest_expiry="{ row }">
        <StatusPill v-if="row.nearest_expiry" :tone="expiryTone(row.nearest_expiry, today)" variant="plain" size="sm" :label="fmt.day(row.nearest_expiry)" />
        <span v-else class="text-subtle">—</span>
      </template>
      <template #cell-sale_price="{ row }"><MoneyText :value="row.sale_price" decimals="never" /></template>
      <template #cell-value="{ row }"><MoneyText :value="row.value" decimals="never" /></template>
    </DataTable>

    <ProductDrawer />
    <OpeningDialog v-model:open="opening" />
    <UiDialog :open="!!limits" :title="t('stock.levels.limitsTitle')" :description="limits ? `${limits.product.name} · ${limits.branch.name}` : undefined" size="sm" @update:open="(value) => !value && (limits = null)">
      <div class="grid grid-cols-2 gap-3">
        <FormField :label="t('stock.levels.min')" :hint="t('stock.levels.inParts')">
          <NumberInput v-model="limitForm.min" :min="0" />
        </FormField>
        <FormField :label="t('stock.levels.max')" :hint="t('stock.levels.inParts')">
          <NumberInput v-model="limitForm.max" :min="0" />
        </FormField>
      </div>
      <template #footer>
        <UiButton variant="ghost" @click="limits = null">{{ t("common.cancel") }}</UiButton>
        <UiButton variant="primary" :loading="savingLimits" @click="saveLimits">{{ t("common.save") }}</UiButton>
      </template>
    </UiDialog>
  </div>
</template>
