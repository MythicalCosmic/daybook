<script setup lang="ts" generic="V extends OptionValue">
/**
 * The searchable list inside ComboBox, MultiSelect, the pickers and FilterBar editors: a filter
 * field, grouped options, keyboard navigation (↑ ↓ Enter, the first match is highlighted), async
 * loading with a debounce, and an optional "Create “…”" row. Single or multiple selection.
 */
import { Check, Plus, Search } from "@lucide/vue";
import { refDebounced } from "@vueuse/core";
import { ListboxContent, ListboxFilter, ListboxGroup, ListboxGroupLabel, ListboxItem, ListboxRoot } from "reka-ui";
import { computed, nextTick, onBeforeUnmount, ref, shallowRef, watch, type ComponentPublicInstance } from "vue";
import { useI18n } from "vue-i18n";

import ErrorState from "./ErrorState.vue";
import OptionRow from "./OptionRow.vue";
import { groupOptions, matchOption, normalize, type OptionSource, type OptionValue, type SelectOption } from "./options";
import UiSpinner from "./UiSpinner.vue";

const CREATE = "__create__";

const props = withDefaults(
  defineProps<{
    modelValue: V | V[] | null;
    multiple?: boolean;
    options?: SelectOption<V>[];
    source?: OptionSource<V>;
    creatable?: boolean;
    searchable?: boolean;
    searchPlaceholder?: string;
    emptyText?: string;
    /** Seeds the filter (a key typed on a closed trigger). */
    initialQuery?: string;
    maxHeight?: string;
    debounce?: number;
  }>(),
  {
    multiple: false,
    options: () => [],
    source: undefined,
    creatable: false,
    searchable: undefined,
    searchPlaceholder: undefined,
    emptyText: undefined,
    initialQuery: "",
    maxHeight: "300px",
    debounce: 200,
  },
);

const emit = defineEmits<{
  "update:modelValue": [value: V | V[] | null];
  create: [query: string];
  /** Options shown so far, so the owner can remember labels of async results. */
  seen: [options: SelectOption<V>[]];
  /** A single choice was made (the owner closes its popover). */
  picked: [option: SelectOption<V>];
}>();

const { t } = useI18n();
const query = ref(props.initialQuery);
const debounced = refDebounced(query, computed(() => (props.source ? props.debounce : 0)));
const remote = shallowRef<SelectOption<V>[]>([]);
const loading = ref(false);
const failed = shallowRef<unknown>(null);
const listbox = ref<ComponentPublicInstance & { highlightFirstItem?: () => void } | null>(null);
let controller: AbortController | null = null;

const showSearch = computed(() => props.searchable ?? (!!props.source || props.options.length > 7 || props.creatable));

async function load(text: string): Promise<void> {
  if (!props.source) return;
  controller?.abort();
  const current = new AbortController();
  controller = current;
  loading.value = true;
  failed.value = null;
  try {
    const result = await props.source(text.trim(), current.signal);
    if (current.signal.aborted) return;
    remote.value = result;
    emit("seen", result);
  } catch (error) {
    if (current.signal.aborted || (error instanceof DOMException && error.name === "AbortError")) return;
    failed.value = error;
  } finally {
    if (controller === current) loading.value = false;
  }
}

watch(debounced, (text) => void load(text), { immediate: true });
onBeforeUnmount(() => controller?.abort());

const visible = computed<SelectOption<V>[]>(() => {
  if (props.source) return remote.value;
  return props.options.filter((option) => matchOption(option, query.value));
});

const groups = computed(() => groupOptions(visible.value));

const canCreate = computed(() => {
  const text = query.value.trim();
  if (!props.creatable || !text) return false;
  return !visible.value.some((option) => normalize(option.label) === normalize(text));
});

// Keep the best match highlighted, so Enter picks it.
watch([visible, canCreate], () => nextTick(() => listbox.value?.highlightFirstItem?.()), { flush: "post" });

const selected = computed(() => {
  const value = props.modelValue;
  if (value === null || value === undefined) return [] as V[];
  return Array.isArray(value) ? value : [value];
});

function onUpdate(next: unknown): void {
  if (props.multiple) {
    const list = (Array.isArray(next) ? next : []) as Array<V | typeof CREATE>;
    if (list.includes(CREATE)) {
      emit("create", query.value.trim());
      return;
    }
    emit("update:modelValue", list as V[]);
    return;
  }
  if (next === CREATE) {
    emit("create", query.value.trim());
    return;
  }
  // Re-picking the current value keeps it (a listbox would toggle it off).
  const value = (next ?? props.modelValue) as V | null;
  emit("update:modelValue", value);
  const option = visible.value.find((o) => o.value === value);
  if (option) emit("picked", option);
}

defineExpose({ reload: () => load(query.value) });
</script>

<template>
  <ListboxRoot
    ref="listbox"
    :model-value="multiple ? selected : (modelValue ?? undefined)"
    :multiple="multiple"
    highlight-on-hover
    class="flex flex-col outline-none"
    @update:model-value="onUpdate"
  >
    <div v-if="showSearch" class="flex h-10 shrink-0 items-center gap-2 border-b border-line px-3">
      <Search :size="15" class="shrink-0 text-subtle" aria-hidden="true" />
      <ListboxFilter
        v-model="query"
        auto-focus
        class="ui-input h-full text-base"
        :placeholder="searchPlaceholder ?? t('common.select.search')"
      />
      <UiSpinner v-if="loading" :size="14" class="text-subtle" />
    </div>
    <ListboxContent class="overflow-y-auto overscroll-contain p-1" :style="{ maxHeight }">
      <ErrorState v-if="failed" compact :error="failed" :retry="() => load(query)" class="m-1 border-0 !bg-transparent" />
      <template v-else>
        <ListboxGroup v-for="group in groups" :key="group.label ?? '_'">
          <ListboxGroupLabel v-if="group.label" class="ui-option-label">{{ group.label }}</ListboxGroupLabel>
          <ListboxItem
            v-for="option in group.options"
            :key="String(option.value)"
            :value="option.value"
            :disabled="option.disabled"
            class="ui-option group"
          >
            <span
              v-if="multiple"
              :class="[
                'grid size-4 shrink-0 place-items-center rounded-[4px] border transition-colors',
                selected.includes(option.value) ? 'border-primary bg-primary text-on-primary' : 'border-line-strong bg-surface',
              ]"
              aria-hidden="true"
            >
              <Check v-if="selected.includes(option.value)" :size="12" :stroke-width="3" />
            </span>
            <OptionRow :option="option" />
            <Check v-if="!multiple && selected.includes(option.value)" :size="15" class="shrink-0 text-primary" aria-hidden="true" />
          </ListboxItem>
        </ListboxGroup>
        <ListboxItem v-if="canCreate" :value="CREATE" class="ui-option text-primary">
          <Plus :size="16" aria-hidden="true" />
          <span class="min-w-0 flex-1 truncate">{{ t("common.select.create", { q: query.trim() }) }}</span>
        </ListboxItem>
        <p v-if="!visible.length && !canCreate && !loading" class="px-3 py-6 text-center text-sm text-muted">
          {{ emptyText ?? t("common.select.empty") }}
        </p>
        <p v-else-if="!visible.length && loading" class="flex items-center justify-center gap-2 px-3 py-6 text-sm text-muted">
          <UiSpinner :size="14" />{{ t("common.loading") }}
        </p>
      </template>
    </ListboxContent>
    <slot name="footer" />
  </ListboxRoot>
</template>
