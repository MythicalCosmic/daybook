<script setup lang="ts">
/**
 * A ledger row's category in the table (plan §6.2: "inline category edit"): a chip, or for an
 * entry the person may change a borderless picker of the categories of its kind. The change shows
 * at once and rolls back if the server refuses.
 */
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import SelectBox from "@/components/SelectBox.vue";

import { useCategorize, useCategories } from "../api";
import { categoryOptions, colorFor, findCategory } from "../lib";
import type { Transaction } from "../types";

const props = defineProps<{ row: Transaction }>();

const { t } = useI18n();
const categorize = useCategorize();
const editable = computed(() => props.row.can_edit && props.row.is_manual && (props.row.kind === "income" || props.row.kind === "expense"));
const tree = useCategories(editable);
const options = computed(() => categoryOptions(tree.data.value, props.row.kind === "income" ? "income" : "expense", { activeOnly: true }));

const value = computed({
  get: () => props.row.category?.id ?? null,
  set: (id: number | null) => {
    if (!id || id === props.row.category?.id) return;
    const node = findCategory(tree.data.value, id);
    if (!node) return;
    const parent = tree.data.value?.find((top) => top.children.some((child) => child.id === id));
    categorize.mutate({ row: props.row, category: { id: node.id, name: node.name, color: node.color, parent_name: parent?.name ?? null } });
  },
});
</script>

<template>
  <SelectBox
    v-if="editable && options.length"
    v-model="value"
    :options="options"
    variant="ghost"
    size="sm"
    class="-ml-2 max-w-full"
    :placeholder="t('finance.tx.pickCategory')"
    :aria-label="t('finance.field.category')"
  />
  <span v-else-if="row.category" class="inline-flex min-w-0 items-center gap-1.5 text-sm text-fg" :title="row.category.parent_name ? `${row.category.name} · ${row.category.parent_name}` : row.category.name">
    <span class="size-2 shrink-0 rounded-full" :style="{ background: colorFor(row.category.id, row.category.color) }" aria-hidden="true" />
    <span class="truncate">{{ row.category.name }}</span>
    <span v-if="row.category.parent_name" class="truncate text-xs text-subtle">· {{ row.category.parent_name }}</span>
  </span>
  <span v-else class="text-sm text-subtle">—</span>
</template>
