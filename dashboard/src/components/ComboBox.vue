<script setup lang="ts" generic="V extends OptionValue">
/**
 * Pick one value from a long or remote list by typing. `options` filters on the client; `source`
 * asks the server (debounced, cancelled when you type on). `creatable` offers "Create “…”" and emits
 * `create` with the text. Typing a letter on the closed field opens it with that letter.
 *
 *   <ComboBox v-model="form.values.counterparty" :source="searchCounterparties" :selected="current" creatable @create="addCounterparty" />
 *
 * `selected` gives the label of a value that isn't in the first page of results (an edit form).
 */
import { ChevronsUpDown, X } from "@lucide/vue";
import { computed, ref, shallowReactive, watch } from "vue";
import { useI18n } from "vue-i18n";

import { controlIconSize, controlSizeClass, controlState, useControl, type ControlSize } from "./field";
import OptionList from "./OptionList.vue";
import OptionRow from "./OptionRow.vue";
import type { OptionSource, OptionValue, SelectOption } from "./options";
import UiPopover from "./UiPopover.vue";

const model = defineModel<V | null>({ default: null });

const props = withDefaults(
  defineProps<{
    options?: SelectOption<V>[];
    source?: OptionSource<V>;
    selected?: SelectOption<V> | null;
    placeholder?: string;
    searchPlaceholder?: string;
    emptyText?: string;
    creatable?: boolean;
    clearable?: boolean;
    size?: ControlSize;
    disabled?: boolean;
    invalid?: boolean;
    id?: string;
    /** Popover width; the field's own width by default. */
    width?: string;
  }>(),
  {
    options: () => [],
    source: undefined,
    selected: null,
    placeholder: undefined,
    searchPlaceholder: undefined,
    emptyText: undefined,
    creatable: false,
    clearable: false,
    size: "md",
    disabled: false,
    invalid: false,
    id: undefined,
    width: undefined,
  },
);

const emit = defineEmits<{ create: [query: string]; change: [option: SelectOption<V> | null] }>();

const { t } = useI18n();
const control = useControl(props);
const open = ref(false);
const seed = ref("");
const trigger = ref<HTMLButtonElement | null>(null);

// Labels of every option seen, so the field can show the current value after the list changes.
const known = shallowReactive(new Map<V, SelectOption<V>>());
function remember(list: readonly SelectOption<V>[]): void {
  for (const option of list) known.set(option.value, option);
}
watch(() => props.options, (list) => remember(list), { immediate: true });
watch(() => props.selected, (option) => option && remember([option]), { immediate: true });

const current = computed(() => (model.value === null ? null : (known.get(model.value) ?? null)));

function onPicked(option: SelectOption<V>): void {
  emit("change", option);
  open.value = false;
  trigger.value?.focus();
}

function onCreate(query: string): void {
  emit("create", query);
  open.value = false;
}

function clear(): void {
  model.value = null;
  emit("change", null);
  trigger.value?.focus();
}

/** A printable key on the closed trigger opens the list with that key typed. */
function onKeydown(event: KeyboardEvent): void {
  if (open.value || control.disabled.value) return;
  if (event.key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey && event.key !== " ") {
    event.preventDefault();
    seed.value = event.key;
    open.value = true;
  } else if (event.key === "ArrowDown") {
    event.preventDefault();
    seed.value = "";
    open.value = true;
  }
}

watch(open, (isOpen) => {
  if (!isOpen) seed.value = "";
});
</script>

<template>
  <div class="relative min-w-0">
    <UiPopover v-model:open="open" :padded="false" :width="width ?? 'max(var(--reka-popover-trigger-width), 240px)'" align="start">
      <template #trigger>
        <button
          :id="control.id.value"
          ref="trigger"
          type="button"
          role="combobox"
          :aria-expanded="open"
          aria-haspopup="listbox"
          :aria-labelledby="control.labelId.value ? `${control.labelId.value} ${control.id.value}` : undefined"
          :aria-describedby="control.describedBy.value"
          :aria-invalid="control.invalid.value || undefined"
          :disabled="control.disabled.value"
          :class="['ui-control w-full', controlSizeClass[size], clearable && current && '!pr-12']"
          :data-state="open ? 'open' : 'closed'"
          v-bind="controlState({ invalid: control.invalid.value, disabled: control.disabled.value })"
          @keydown="onKeydown"
        >
          <span v-if="current" class="flex min-w-0 flex-1 items-center gap-2"><OptionRow :option="current" compact /></span>
          <span v-else class="min-w-0 flex-1 truncate text-subtle">{{ placeholder ?? t("common.select.placeholder") }}</span>
          <ChevronsUpDown :size="controlIconSize[size] - 1" class="shrink-0 text-subtle" aria-hidden="true" />
        </button>
      </template>
      <OptionList
        :model-value="model"
        :options="options"
        :source="source"
        :creatable="creatable"
        :search-placeholder="searchPlaceholder"
        :empty-text="emptyText"
        :initial-query="seed"
        searchable
        @update:model-value="(value) => (model = value as V | null)"
        @seen="remember"
        @picked="onPicked"
        @create="onCreate"
      />
    </UiPopover>
    <button
      v-if="clearable && current && !control.disabled.value"
      type="button"
      class="pressable absolute right-7 top-1/2 grid size-5 -translate-y-1/2 place-items-center rounded-full text-subtle hover:bg-highlight hover:text-fg"
      :aria-label="t('common.clear')"
      @click="clear"
    >
      <X :size="13" />
    </button>
  </div>
</template>
