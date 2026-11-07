<script setup lang="ts">
/**
 * One catalogue item in a side panel, opened by `?product=<id>` (the catalogue, the stock page,
 * search): what each pharmacy holds, its batches (series, expiry, price, its legal cap), what moved,
 * the items with the same active ingredient, form and strength (a catalogue fact for the pharmacist
 * to choose from, never advice), and its other codes. Cost fields only with finance.view.
 */
import { Pencil, Plus, Trash2 } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";

import { isApiError } from "@/api/http";
import DescriptionList from "@/components/DescriptionList.vue";
import MoneyText from "@/components/MoneyText.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SelectBox from "@/components/SelectBox.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import TextInput from "@/components/TextInput.vue";
import UiButton from "@/components/UiButton.vue";
import UiDrawer from "@/components/UiDrawer.vue";
import { toast } from "@/components/useToast";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore, useCompanyToday } from "@/stores/company";

import { stockApi, useProduct, useProductBatches, useProductMovements, useRefresh } from "../api";
import { BATCH_TONES, expiryTone, packsAndParts } from "../lib";
import type { CodeKind } from "../types";
import ProductBadges from "./ProductBadges.vue";
import ProductFormDialog from "./ProductFormDialog.vue";

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const route = useRoute();
const today = useCompanyToday();
const refresh = useRefresh();

const id = computed(() => Number(route.query.product ?? 0) || 0);
const tab = ref<"overview" | "batches" | "movements" | "analogs" | "codes">("overview");
watch(id, () => (tab.value = "overview"));

const detail = useProduct(id);
const batches = useProductBatches(id);
const movements = useProductMovements(id, () => tab.value === "movements");
const product = computed(() => detail.data.value?.product ?? null);
const canManage = computed(() => company.can("stock.manage"));
const editing = ref(false);

const qty = (value: string | number | null | undefined) => (product.value ? packsAndParts(value, product.value.units_per_pack, product.value.part_label, t) : "—");

const facts = computed(() => {
  const p = product.value;
  if (!p) return [];
  return [
    { key: "inn", label: t("stock.field.inn"), value: p.inn || "—" },
    { key: "form", label: t("stock.field.dosageForm"), value: [p.dosage_form ? t(`stock.dosage.${p.dosage_form}`) : "", p.strength].filter(Boolean).join(", ") || "—" },
    { key: "pack", label: t("stock.field.unitsPerPack"), value: p.units_per_pack > 1 ? t("stock.drawer.packOf", { n: p.units_per_pack, label: p.part_label || t("stock.drawer.parts") }) : t("stock.drawer.wholePacks") },
    { key: "maker", label: t("stock.field.manufacturer"), value: p.manufacturer?.name ?? "—" },
    { key: "category", label: t("stock.field.category"), value: p.category?.name ?? "—" },
    { key: "storage", label: t("stock.field.storage"), value: t(`stock.storage.${p.storage}`) },
    { key: "barcode", label: t("stock.field.barcode"), value: p.barcode || "—", copy: !!p.barcode, mono: true },
    { key: "registration", label: t("stock.field.registration"), value: p.registration_number ? `${p.registration_number}${p.registration_until ? ` · ${fmt.day(p.registration_until)}` : ""}` : "—" },
  ];
});

const tabs = computed(() => [
  { value: "overview" as const, label: t("stock.drawer.overview") },
  { value: "batches" as const, label: t("stock.drawer.batches"), count: batches.data.value?.length },
  { value: "movements" as const, label: t("stock.drawer.movements") },
  { value: "analogs" as const, label: t("stock.drawer.analogs"), count: detail.data.value?.analogs.length },
  { value: "codes" as const, label: t("stock.drawer.codes") },
]);

const codeKind = ref<CodeKind>("barcode");
const codeText = ref("");
const codeKinds = computed(() => (["barcode", "supplier", "pos"] as const).map((value) => ({ value, label: t(`stock.code.${value}`) })));
async function addCode(): Promise<void> {
  if (!product.value || !codeText.value.trim()) return;
  try {
    await stockApi.addCode(company.currentId ?? 0, product.value.id, { kind: codeKind.value, code: codeText.value.trim() });
    codeText.value = "";
    refresh();
  } catch (error) {
    toast.error(isApiError(error) ? error.message : t("common.error.generic"));
  }
}
async function removeCode(codeId: number): Promise<void> {
  if (!product.value) return;
  await stockApi.removeCode(company.currentId ?? 0, product.value.id, codeId);
  refresh();
}
</script>

<template>
  <UiDrawer query-key="product" :title="product?.name ?? t('stock.drawer.title')" size="lg">
    <div v-if="detail.isPending.value" class="flex flex-col gap-3"><SkeletonBlock class="h-24" /><SkeletonBlock class="h-40" /></div>
    <div v-else-if="product" class="flex flex-col gap-4" data-testid="product-drawer">
      <div class="flex flex-wrap items-center gap-2">
        <ProductBadges :rx="product.rx_required" :control="product.control_class" :storage="product.storage" :mandatory="product.mandatory_list" :social="product.socially_significant" :e-rx="product.e_rx_group" :inactive="!product.is_active" />
        <span class="ms-auto"><UiButton v-if="canManage" size="sm" variant="secondary" :icon="Pencil" @click="editing = true">{{ t("common.edit") }}</UiButton></span>
      </div>
      <div class="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div class="rounded-[12px] bg-surface-2/60 p-3">
          <div class="text-xs text-muted">{{ t("stock.drawer.onHand") }}</div>
          <div class="text-sm font-semibold text-fg">{{ qty(product.quantity) }}</div>
        </div>
        <div class="rounded-[12px] bg-surface-2/60 p-3">
          <div class="text-xs text-muted">{{ t("stock.field.salePrice") }}</div>
          <div class="text-sm font-semibold text-fg"><MoneyText :value="product.sale_price" decimals="never" /></div>
        </div>
        <div class="rounded-[12px] bg-surface-2/60 p-3">
          <div class="text-xs text-muted">{{ t("stock.drawer.partPrice") }}</div>
          <div class="text-sm font-semibold text-fg"><MoneyText :value="product.effective_part_price" decimals="never" /></div>
        </div>
        <div class="rounded-[12px] bg-surface-2/60 p-3">
          <div class="text-xs text-muted">{{ product.cost_price !== undefined ? t("stock.drawer.lastCost") : t("stock.drawer.priceCap") }}</div>
          <div class="text-sm font-semibold text-fg">
            <MoneyText v-if="product.cost_price !== undefined" :value="product.cost_price" decimals="never" />
            <MoneyText v-else-if="detail.data.value?.price_cap" :value="detail.data.value.price_cap" decimals="never" />
            <span v-else class="text-subtle">—</span>
          </div>
        </div>
      </div>

      <SegmentedControl v-model="tab" :options="tabs" size="sm" />

      <template v-if="tab === 'overview'">
        <DescriptionList :items="facts" layout="rows" />
        <section>
          <h3 class="mb-2 text-sm font-semibold text-fg">{{ t("stock.drawer.byBranch") }}</h3>
          <ul class="divide-y divide-line rounded-[12px] border border-line">
            <li v-for="row in detail.data.value?.branches ?? []" :key="row.branch_id" class="flex items-center justify-between gap-3 px-3 py-2 text-sm">
              <span class="text-fg">{{ row.branch }}</span>
              <span class="text-end">
                <span class="font-medium tabular-nums text-fg">{{ qty(row.quantity) }}</span>
                <span v-if="Number(row.shortfall) > 0" class="block text-xs text-danger">{{ t("stock.levels.shortfallLine", { qty: qty(row.shortfall) }) }}</span>
              </span>
            </li>
            <li v-if="!(detail.data.value?.branches ?? []).length" class="px-3 py-3 text-sm text-muted">{{ t("stock.drawer.noStock") }}</li>
          </ul>
        </section>
      </template>

      <template v-else-if="tab === 'batches'">
        <ul class="divide-y divide-line rounded-[12px] border border-line" data-testid="drawer-batches">
          <li v-for="batch in batches.data.value ?? []" :key="batch.id" class="flex flex-col gap-1 px-3 py-2.5 text-sm">
            <div class="flex flex-wrap items-center gap-2">
              <span class="font-medium text-fg">{{ t("stock.batch.series", { series: batch.series }) }}</span>
              <StatusPill :tone="expiryTone(batch.expires_on, today)" variant="plain" size="sm" :label="t('stock.batch.until', { day: fmt.day(batch.expires_on) })" />
              <StatusPill v-if="batch.status !== 'sellable'" :tone="BATCH_TONES[batch.status]" size="sm" :label="t(`stock.batchStatus.${batch.status}`)" />
              <span class="ms-auto text-xs text-muted">{{ batch.branch.name }}</span>
            </div>
            <div class="flex flex-wrap gap-x-4 gap-y-0.5 text-xs text-muted">
              <span>{{ qty(batch.quantity) }}</span>
              <span>{{ t("stock.batch.price") }}: <MoneyText :value="batch.retail_price" decimals="never" /></span>
              <span v-if="batch.price_cap">{{ t("stock.batch.cap") }}: <MoneyText :value="batch.price_cap" decimals="never" /></span>
              <span v-if="batch.unit_cost !== undefined">{{ t("stock.batch.cost") }}: <MoneyText :value="batch.unit_cost" decimals="never" /></span>
              <span v-if="batch.supplier">{{ batch.supplier.name }}</span>
            </div>
          </li>
          <li v-if="!(batches.data.value ?? []).length" class="px-3 py-3 text-sm text-muted">{{ t("stock.drawer.noBatches") }}</li>
        </ul>
      </template>

      <template v-else-if="tab === 'movements'">
        <ul class="divide-y divide-line rounded-[12px] border border-line">
          <li v-for="row in movements.data.value ?? []" :key="row.id" class="flex items-center gap-3 px-3 py-2 text-sm">
            <span class="w-28 shrink-0 text-xs text-muted tabular-nums">{{ fmt.instant(row.at, "short") }}</span>
            <span class="min-w-0 flex-1 truncate text-fg">{{ t(`stock.move.${row.kind}`) }}<template v-if="row.series"> · {{ row.series }}</template> · {{ row.branch.name }}</span>
            <span :class="['shrink-0 font-medium tabular-nums', Number(row.quantity) < 0 ? 'text-danger' : 'text-success']">{{ Number(row.quantity) > 0 ? "+" : "" }}{{ qty(row.quantity) }}</span>
          </li>
          <li v-if="movements.data.value && !movements.data.value.length" class="px-3 py-3 text-sm text-muted">{{ t("stock.drawer.noMovements") }}</li>
        </ul>
      </template>

      <template v-else-if="tab === 'analogs'">
        <p class="text-sm font-medium text-fg">{{ t("stock.drawer.analogsTitle") }}</p>
        <p class="text-xs text-muted">{{ t("stock.drawer.analogsNote") }}</p>
        <ul class="divide-y divide-line rounded-[12px] border border-line" data-testid="drawer-analogs">
          <li v-for="row in detail.data.value?.analogs ?? []" :key="row.id" class="flex items-center justify-between gap-3 px-3 py-2 text-sm">
            <span class="min-w-0">
              <span class="block truncate text-fg">{{ row.name }}</span>
              <span class="block truncate text-xs text-muted">{{ [row.trade_name, row.manufacturer].filter(Boolean).join(" · ") }}</span>
            </span>
            <span class="shrink-0 text-end text-xs text-muted">
              <MoneyText :value="row.sale_price" decimals="never" />
              <span class="block tabular-nums">{{ packsAndParts(row.quantity, 1, "", t) }}</span>
            </span>
          </li>
          <li v-if="!(detail.data.value?.analogs ?? []).length" class="px-3 py-3 text-sm text-muted">{{ t("stock.drawer.noAnalogs") }}</li>
        </ul>
      </template>

      <template v-else>
        <ul class="divide-y divide-line rounded-[12px] border border-line">
          <li v-for="code in detail.data.value?.codes ?? []" :key="code.id" class="flex items-center gap-3 px-3 py-2 text-sm">
            <span class="w-36 shrink-0 text-xs text-muted">{{ t(`stock.code.${code.kind}`) }}</span>
            <span class="min-w-0 flex-1 truncate font-mono text-fg">{{ code.code }}<template v-if="code.supplier"> · {{ code.supplier.name }}</template></span>
            <UiButton v-if="canManage" size="sm" variant="ghost" :icon="Trash2" :aria-label="t('common.delete')" @click="removeCode(code.id)" />
          </li>
          <li v-if="!(detail.data.value?.codes ?? []).length" class="px-3 py-3 text-sm text-muted">{{ t("stock.drawer.noCodes") }}</li>
        </ul>
        <div v-if="canManage" class="flex flex-wrap items-center gap-2">
          <SelectBox v-model="codeKind" :options="codeKinds" size="sm" class="w-44" />
          <TextInput v-model="codeText" size="sm" class="w-48" mono :placeholder="t('stock.drawer.codePlaceholder')" />
          <UiButton size="sm" variant="secondary" :icon="Plus" :disabled="!codeText.trim()" @click="addCode">{{ t("stock.drawer.addCode") }}</UiButton>
        </div>
      </template>
    </div>
    <ProductFormDialog v-if="product" v-model:open="editing" :product="product" />
  </UiDrawer>
</template>
