<script setup lang="ts">
/**
 * Filters as chips (plan §6.2: "Filter chips (kind, status, assignee, …)"): an optional search box,
 * one chip per active filter ("Status: Open, Late") that opens its editor in a popover, "+ Filter"
 * to add another, and "Clear filters". Bind it to the URL with `useUrlFilters(defs)`:
 *
 *   const filters = useUrlFilters(defs);
 *   <FilterBar v-model="filters.values.value" v-model:search="q" :defs="defs" />
 */
import { ListFilter, Plus, Search, X } from "@lucide/vue";
import { computed, nextTick, ref } from "vue";
import { useI18n } from "vue-i18n";

import { useFormat } from "@/lib/useFormat";

import DatePicker from "./DatePicker.vue";
import { activeCount, isEmptyValue, summarize, type FilterDef, type FilterValue, type FilterValues, type RangeValue } from "./filters";
import NumberInput from "./NumberInput.vue";
import OptionList from "./OptionList.vue";
import TextInput from "./TextInput.vue";
import UiPopover from "./UiPopover.vue";

const values = defineModel<FilterValues>({ required: true });
const search = defineModel<string>("search");

const props = withDefaults(defineProps<{ defs: FilterDef[]; searchable?: boolean; searchPlaceholder?: string; size?: "sm" | "md" }>(), {
  searchable: false,
  searchPlaceholder: undefined,
  size: "md",
});

const { t } = useI18n();
const fmt = useFormat();
const openKey = ref<string | null>(null);
const adding = ref(false);
/** Filters added but not set yet: they stay as chips while their editor is open. */
const pending = ref<string[]>([]);

const shown = computed(() =>
  props.defs.filter((def) => def.pinned || !isEmptyValue(values.value[def.key]) || pending.value.includes(def.key) || openKey.value === def.key),
);
const available = computed(() => props.defs.filter((def) => !shown.value.includes(def)));
const active = computed(() => activeCount(props.defs, values.value));

const context = computed(() => ({
  yes: t("common.filter.yes"),
  no: t("common.filter.no"),
  day: (day: string) => fmt.day(day, "short"),
  range: fmt.range,
  number: (value: string) => fmt.number(value),
  more: (n: number) => `+${n}`,
}));

function set(key: string, value: FilterValue): void {
  values.value = { ...values.value, [key]: value };
}

function remove(def: FilterDef): void {
  pending.value = pending.value.filter((key) => key !== def.key);
  if (openKey.value === def.key) openKey.value = null;
  set(def.key, def.type === "multi" ? [] : null);
}

function clearAll(): void {
  pending.value = [];
  openKey.value = null;
  const next: FilterValues = {};
  for (const def of props.defs) next[def.key] = def.type === "multi" ? [] : null;
  values.value = next;
  if (search.value) search.value = "";
}

async function add(key: string | number | (string | number)[] | null): Promise<void> {
  if (typeof key !== "string") return;
  adding.value = false;
  pending.value = [...pending.value, key];
  await nextTick();
  // Let the add menu return focus first, then open the new chip's editor.
  setTimeout(() => (openKey.value = key), 0);
}

function onOpen(def: FilterDef, open: boolean): void {
  if (open) {
    openKey.value = def.key;
    return;
  }
  if (openKey.value === def.key) openKey.value = null;
  pending.value = pending.value.filter((key) => key !== def.key);
}

function rangeOf(def: FilterDef): RangeValue {
  const value = values.value[def.key];
  return value && typeof value === "object" && !Array.isArray(value) ? value : { from: null, to: null };
}

function setRange(def: FilterDef, part: "from" | "to", value: string | null): void {
  const next = { ...rangeOf(def), [part]: value };
  set(def.key, next.from || next.to ? next : null);
}

function numberPart(value: string | null): number | null {
  if (value === null || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

const addOptions = computed(() => available.value.map((def) => ({ value: def.key, label: def.label, icon: def.icon })));
const chipHeight = computed(() => (props.size === "sm" ? "h-7" : "h-8"));
</script>

<template>
  <div class="flex min-w-0 flex-wrap items-center gap-1.5" role="group" :aria-label="t('common.filters')">
    <TextInput
      v-if="searchable"
      :model-value="search ?? ''"
      type="search"
      :icon="Search"
      clearable
      :size="size"
      :placeholder="searchPlaceholder ?? t('common.filter.search')"
      class="w-full sm:w-[240px]"
      @update:model-value="(value) => (search = value ?? '')"
    />

    <div
      v-for="def in shown"
      :key="def.key"
      :class="[
        'inline-flex max-w-full items-center overflow-hidden rounded-button border bg-surface shadow-xs transition-colors',
        chipHeight,
        isEmptyValue(values[def.key]) ? 'border-dashed border-line-strong' : 'border-line-strong',
      ]"
    >
      <UiPopover :open="openKey === def.key" :padded="false" width="280px" @update:open="(open: boolean) => onOpen(def, open)">
        <template #trigger>
          <button type="button" class="flex h-full min-w-0 items-center gap-1.5 pl-2.5 pr-2 text-sm hover:bg-highlight">
            <component :is="def.icon" v-if="def.icon" :size="14" class="shrink-0 text-subtle" aria-hidden="true" />
            <span class="shrink-0 font-medium text-muted">{{ def.label }}</span>
            <span v-if="!isEmptyValue(values[def.key])" class="min-w-0 truncate font-semibold text-fg">{{ summarize(def, values[def.key] ?? null, context) }}</span>
          </button>
        </template>
        <!-- Editors -->
        <OptionList
          v-if="def.type === 'select' || def.type === 'multi'"
          :model-value="(values[def.key] as string | string[] | null) ?? (def.type === 'multi' ? [] : null)"
          :multiple="def.type === 'multi'"
          :options="def.options"
          :source="def.source"
          :search-placeholder="def.placeholder"
          @update:model-value="(value) => set(def.key, value as FilterValue)"
          @picked="openKey = null"
        />
        <div v-else-if="def.type === 'boolean'" class="flex flex-col p-1" role="radiogroup" :aria-label="def.label">
          <button
            v-for="choice in [true, false]"
            :key="String(choice)"
            type="button"
            role="radio"
            :aria-checked="values[def.key] === choice"
            :class="['ui-option hover:bg-highlight', values[def.key] === choice && 'bg-accent-soft font-semibold text-accent-fg']"
            @click="
              set(def.key, choice);
              openKey = null;
            "
          >
            {{ choice ? (def.trueLabel ?? t("common.filter.yes")) : (def.falseLabel ?? t("common.filter.no")) }}
          </button>
        </div>
        <div v-else-if="def.type === 'date-range'" class="flex flex-col gap-2 p-3">
          <label class="flex flex-col gap-1 text-xs font-semibold text-muted">
            {{ t("common.filter.from") }}
            <DatePicker :model-value="rangeOf(def).from" :max="rangeOf(def).to" clearable size="sm" @update:model-value="(day) => setRange(def, 'from', day)" />
          </label>
          <label class="flex flex-col gap-1 text-xs font-semibold text-muted">
            {{ t("common.filter.to") }}
            <DatePicker :model-value="rangeOf(def).to" :min="rangeOf(def).from" clearable size="sm" @update:model-value="(day) => setRange(def, 'to', day)" />
          </label>
        </div>
        <div v-else-if="def.type === 'number-range'" class="flex items-end gap-2 p-3">
          <label class="flex flex-1 flex-col gap-1 text-xs font-semibold text-muted">
            {{ t("common.filter.from") }}
            <NumberInput
              :model-value="numberPart(rangeOf(def).from)"
              size="sm"
              :steppers="false"
              @update:model-value="(n) => setRange(def, 'from', n === null ? null : String(n))"
            />
          </label>
          <label class="flex flex-1 flex-col gap-1 text-xs font-semibold text-muted">
            {{ t("common.filter.to") }}
            <NumberInput
              :model-value="numberPart(rangeOf(def).to)"
              size="sm"
              :steppers="false"
              @update:model-value="(n) => setRange(def, 'to', n === null ? null : String(n))"
            />
          </label>
        </div>
        <div v-else class="p-3">
          <TextInput
            :model-value="(values[def.key] as string | null) ?? ''"
            size="sm"
            autofocus
            :placeholder="def.placeholder"
            @update:model-value="(value) => set(def.key, value || null)"
            @enter="openKey = null"
          />
        </div>
      </UiPopover>
      <button
        type="button"
        class="grid h-full w-7 shrink-0 place-items-center border-l border-line text-subtle hover:bg-highlight hover:text-fg"
        :aria-label="t('common.filter.remove', { name: def.label })"
        @click="remove(def)"
      >
        <X :size="13" />
      </button>
    </div>

    <UiPopover v-if="available.length" v-model:open="adding" :padded="false" width="240px">
      <template #trigger>
        <button
          type="button"
          :class="[
            'pressable inline-flex items-center gap-1.5 rounded-button px-2.5 text-sm font-semibold text-muted hover:bg-highlight hover:text-fg data-[state=open]:bg-highlight',
            chipHeight,
          ]"
        >
          <component :is="shown.length ? Plus : ListFilter" :size="15" aria-hidden="true" />
          {{ t("common.filter.add") }}
        </button>
      </template>
      <OptionList :model-value="null" :options="addOptions" :search-placeholder="t('common.filter.choose')" @update:model-value="add" />
    </UiPopover>

    <button
      v-if="active > 0 || (search ?? '').length > 0"
      type="button"
      :class="['rounded-button px-2 text-sm font-semibold text-muted hover:text-fg', chipHeight]"
      @click="clearAll"
    >
      {{ t("common.filter.clearAll") }}
    </button>
  </div>
</template>
