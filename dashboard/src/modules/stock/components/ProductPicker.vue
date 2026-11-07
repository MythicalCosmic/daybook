<script setup lang="ts">
/**
 * Pick a catalogue item by name, INN or barcode (searched on the server). `v-model` is the
 * product's id; `change` hands over the whole product (its parts per pack, Rx mark, price).
 */
import { ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import ComboBox from "@/components/ComboBox.vue";
import type { SelectOption } from "@/components/options";
import { useCompanyStore } from "@/stores/company";

import { searchProducts } from "../api";
import type { Product } from "../types";

const model = defineModel<number | null>({ default: null });
const props = withDefaults(defineProps<{ initial?: { id: number; name: string } | null; invalid?: boolean; disabled?: boolean; size?: "sm" | "md" }>(), {
  initial: null,
  invalid: false,
  disabled: false,
  size: "md",
});
const emit = defineEmits<{ change: [product: Product | null] }>();

const { t } = useI18n();
const company = useCompanyStore();
const found = new Map<number, Product>();
const selected = ref<SelectOption<number> | null>(props.initial ? { value: props.initial.id, label: props.initial.name } : null);

watch(
  () => props.initial,
  (value) => {
    if (value) selected.value = { value: value.id, label: value.name };
  },
);

async function source(query: string, signal: AbortSignal): Promise<SelectOption<number>[]> {
  const rows = await searchProducts(company.currentId ?? 0, query, signal);
  for (const row of rows) found.set(row.id, row);
  return rows.map((row) => ({
    value: row.id,
    label: row.name,
    description: [row.inn, row.barcode, row.rx_required ? t("stock.badge.rx") : ""].filter(Boolean).join(" · "),
    keywords: [row.inn, row.barcode, row.trade_name].filter(Boolean),
  }));
}

function changed(option: SelectOption<number> | null): void {
  selected.value = option;
  emit("change", option ? (found.get(Number(option.value)) ?? null) : null);
}
</script>

<template>
  <ComboBox
    v-model="model"
    :source="source"
    :selected="selected"
    :placeholder="t('stock.picker.product')"
    :search-placeholder="t('stock.picker.search')"
    :empty-text="t('stock.picker.none')"
    :invalid="invalid"
    :disabled="disabled"
    :size="size"
    clearable
    @change="changed"
  />
</template>
