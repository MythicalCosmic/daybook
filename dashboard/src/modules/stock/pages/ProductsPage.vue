<script setup lang="ts">
/**
 * Medicines (Dorilar): the catalogue, with the marks a pharmacist looks for (prescription only,
 * controlled, cold chain, the mandatory list), what is on hand at your pharmacies and the nearest
 * expiry. Filters live in the URL; `?product=<id>` opens an item, `?new=1` the form, `?import=1`
 * the spreadsheet import (Get started links there).
 */
import { FileUp, Pill, Plus, Printer } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";

import DataTable from "@/components/DataTable.vue";
import EmptyState from "@/components/EmptyState.vue";
import MoneyText from "@/components/MoneyText.vue";
import PageHeader from "@/components/PageHeader.vue";
import SelectBox from "@/components/SelectBox.vue";
import StatusPill from "@/components/StatusPill.vue";
import type { TableColumn } from "@/components/table";
import TextInput from "@/components/TextInput.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import UiButton from "@/components/UiButton.vue";
import { useDataTable } from "@/components/useDataTable";
import { patchQuery, rs, useRouteState } from "@/lib/useRouteState";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore, useCompanyToday } from "@/stores/company";

import { useCategories, useProducts } from "../api";
import ImportWizard from "../components/ImportWizard.vue";
import PriceTagsDialog from "../components/PriceTagsDialog.vue";
import ProductBadges from "../components/ProductBadges.vue";
import ProductDrawer from "../components/ProductDrawer.vue";
import ProductFormDialog from "../components/ProductFormDialog.vue";
import { expiryTone, packsAndParts } from "../lib";
import { PRODUCT_KINDS, STORAGES, type Product } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const router = useRouter();
const today = useCompanyToday();

const search = useRouteState("q", rs.string(""));
const category = useRouteState("category", rs.string(""));
const kind = useRouteState("kind", rs.string(""));
const rx = useRouteState("rx", rs.string(""));
const storage = useRouteState("storage", rs.string(""));
const control = useRouteState("control", rs.boolean(false));
const mandatory = useRouteState("mandatory", rs.boolean(false));
const inactive = useRouteState("inactive", rs.boolean(false));
const creating = useRouteState("new", rs.boolean(false));
const importing = useRouteState("import", rs.boolean(false));
const tagsOpen = ref(false);

const canManage = computed(() => company.can("stock.manage"));
const table = useDataTable({ id: "stock.products", pageSize: 50 });
table.resetPageOn(() => [search.value, category.value, kind.value, rx.value, storage.value, control.value, mandatory.value, inactive.value]);
const params = computed(() => ({
  q: search.value || undefined,
  category: category.value || undefined,
  kind: kind.value || undefined,
  rx: rx.value || undefined,
  storage: storage.value || undefined,
  control: control.value || undefined,
  mandatory: mandatory.value || undefined,
  active: inactive.value ? "all" : undefined,
  page: table.page.value,
  page_size: table.pageSize.value,
}));
const products = useProducts(params);
const categories = useCategories();

const categoryOptions = computed(() => (categories.data.value ?? []).map((row) => ({ value: String(row.id), label: row.name })));
const kindOptions = computed(() => PRODUCT_KINDS.map((value) => ({ value, label: t(`stock.kind.${value}`) })));
const rxOptions = computed(() => [
  { value: "true", label: t("stock.filter.rxOnly") },
  { value: "false", label: t("stock.filter.otcOnly") },
]);
const storageOptions = computed(() => STORAGES.map((value) => ({ value, label: t(`stock.storage.${value}`) })));
// The selects clear to null; the URL keeps "" for "any".
const nullable = (source: { value: string }) => computed({ get: () => source.value || null, set: (value: string | null) => (source.value = value ?? "") });
const categoryModel = nullable(category);
const kindModel = nullable(kind);
const rxModel = nullable(rx);
const storageModel = nullable(storage);

const hasCost = computed(() => (products.data.value?.results ?? []).some((row) => row.cost_price !== undefined));
const columns = computed<TableColumn<Product>[]>(() => [
  { id: "name", header: t("stock.col.name"), minWidth: 300, sticky: true },
  { id: "inn", header: t("stock.col.inn"), minWidth: 150, value: (row) => row.inn },
  { id: "pack", header: t("stock.col.pack"), width: 150, value: (row) => [row.dosage_form ? t(`stock.dosage.${row.dosage_form}`) : "", row.strength].filter(Boolean).join(" · ") },
  { id: "sale_price", header: t("stock.col.price"), numeric: true, width: 130 },
  ...(hasCost.value ? [{ id: "cost_price", header: t("stock.col.cost"), numeric: true, width: 130 } as TableColumn<Product>] : []),
  { id: "quantity", header: t("stock.col.onHand"), numeric: true, width: 160 },
  { id: "nearest_expiry", header: t("stock.col.nearestExpiry"), width: 150 },
]);
const filtered = computed(() => Boolean(search.value || category.value || kind.value || rx.value || storage.value || control.value || mandatory.value || inactive.value));

function open(row: Product): void {
  patchQuery(router, { product: String(row.id) });
}

function clear(): void {
  search.value = "";
  category.value = "";
  kind.value = "";
  rx.value = "";
  storage.value = "";
  control.value = false;
  mandatory.value = false;
  inactive.value = false;
}
</script>

<template>
  <div>
    <PageHeader :title="t('stock.nav.products')" :description="t('stock.products.description')">
      <template #actions>
        <UiButton variant="secondary" :icon="Printer" data-testid="price-tags-open" @click="tagsOpen = true">{{ t("stock.priceTags.button") }}</UiButton>
        <UiButton v-if="canManage" variant="secondary" :icon="FileUp" @click="importing = true">{{ t("stock.products.import") }}</UiButton>
        <UiButton v-if="canManage" variant="primary" :icon="Plus" @click="creating = true">{{ t("stock.products.new") }}</UiButton>
      </template>
    </PageHeader>

    <div v-if="products.data.value && !products.data.value.count && !filtered" class="ui-card">
      <EmptyState :icon="Pill" :title="t('stock.products.emptyTitle')" :description="t('stock.products.emptyBody')">
        <UiButton v-if="canManage" variant="primary" :icon="FileUp" @click="importing = true">{{ t("stock.products.import") }}</UiButton>
      </EmptyState>
    </div>

    <DataTable
      v-else
      :state="table"
      :columns="columns"
      :rows="products.data.value?.results"
      :total="products.data.value?.count"
      row-key="id"
      :loading="products.isPending.value"
      :fetching="products.isFetching.value"
      :error="products.error.value"
      :retry="() => products.refetch()"
      clickable
      :filtered="filtered"
      csv-name="medicines"
      @row-click="open"
      @clear-filters="clear"
    >
      <template #toolbar>
        <div class="flex flex-wrap items-center gap-2">
          <TextInput v-model="search" :debounce="300" type="search" size="sm" class="w-full sm:w-64" :placeholder="t('stock.filter.search')" clearable />
          <SelectBox v-model="categoryModel" size="sm" class="w-48" :options="categoryOptions" clearable :placeholder="t('stock.filter.anyCategory')" />
          <SelectBox v-model="kindModel" size="sm" class="w-40" :options="kindOptions" clearable :placeholder="t('stock.filter.anyKind')" />
          <SelectBox v-model="rxModel" size="sm" class="w-44" :options="rxOptions" clearable :placeholder="t('stock.filter.anyRx')" />
          <SelectBox v-model="storageModel" size="sm" class="w-44" :options="storageOptions" clearable :placeholder="t('stock.filter.anyStorage')" />
          <ToggleSwitch v-model="control" size="sm" :label="t('stock.filter.controlled')" />
          <ToggleSwitch v-model="mandatory" size="sm" :label="t('stock.filter.mandatory')" />
          <ToggleSwitch v-model="inactive" size="sm" :label="t('stock.filter.inactive')" />
        </div>
      </template>
      <template #cell-name="{ row }">
        <span class="flex min-w-0 flex-col gap-0.5">
          <span class="truncate font-medium text-fg">{{ row.name }}</span>
          <span class="flex min-w-0 items-center gap-1.5">
            <span v-if="row.manufacturer" class="truncate text-xs text-muted">{{ row.manufacturer.name }}</span>
            <ProductBadges :rx="row.rx_required" :control="row.control_class" :storage="row.storage" :mandatory="row.mandatory_list" :inactive="!row.is_active" />
          </span>
        </span>
      </template>
      <template #cell-sale_price="{ row }"><MoneyText :value="row.sale_price" decimals="never" /></template>
      <template #cell-cost_price="{ row }">
        <MoneyText v-if="row.cost_price" :value="row.cost_price" decimals="never" />
        <span v-else class="text-subtle">—</span>
      </template>
      <template #cell-quantity="{ row }">
        <span v-if="row.quantity === null" class="text-subtle">—</span>
        <span v-else :class="Number(row.quantity) < 0 ? 'text-danger' : Number(row.quantity) === 0 ? 'text-subtle' : 'text-fg'">{{ packsAndParts(row.quantity, row.units_per_pack, row.part_label, t) }}</span>
      </template>
      <template #cell-nearest_expiry="{ row }">
        <StatusPill v-if="row.nearest_expiry" :tone="expiryTone(row.nearest_expiry, today)" variant="plain" size="sm" :label="fmt.day(row.nearest_expiry)" />
        <span v-else class="text-subtle">—</span>
      </template>
    </DataTable>

    <ProductDrawer />
    <ProductFormDialog v-model:open="creating" @saved="(id) => patchQuery(router, { product: String(id), new: undefined })" />
    <ImportWizard v-model:open="importing" />
    <PriceTagsDialog v-model:open="tagsOpen" />
  </div>
</template>
