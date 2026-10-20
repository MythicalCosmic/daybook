<script setup lang="ts" generic="V extends OptionValue">
/**
 * Pick several values. The field shows chips (or "3 selected" with `display="count"`); the list has
 * a search, checkboxes, and "Select all" / "Clear" at the bottom. Backspace on the closed field
 * removes the last value. Works with `options` (client filter) or `source` (server search).
 *
 *   <MultiSelect v-model="filters.status" :options="statusOptions" :placeholder="t('tasks.anyStatus')" />
 */
import { ChevronsUpDown } from "@lucide/vue";
import { computed, ref, shallowReactive, watch } from "vue";
import { useI18n } from "vue-i18n";

import { controlIconSize, controlSizeClass, controlState, useControl, type ControlSize } from "./field";
import OptionList from "./OptionList.vue";
import type { OptionSource, OptionValue, SelectOption } from "./options";
import UiPopover from "./UiPopover.vue";
import UserAvatar from "./UserAvatar.vue";

const model = defineModel<V[]>({ default: () => [] });

const props = withDefaults(
  defineProps<{
    options?: SelectOption<V>[];
    source?: OptionSource<V>;
    /** Labels for values not in the first page of a remote list. */
    selected?: SelectOption<V>[];
    placeholder?: string;
    searchPlaceholder?: string;
    emptyText?: string;
    display?: "chips" | "count";
    /** Chips shown before "+N". */
    maxChips?: number;
    max?: number;
    creatable?: boolean;
    size?: ControlSize;
    disabled?: boolean;
    invalid?: boolean;
    id?: string;
    width?: string;
  }>(),
  {
    options: () => [],
    source: undefined,
    selected: () => [],
    placeholder: undefined,
    searchPlaceholder: undefined,
    emptyText: undefined,
    display: "chips",
    maxChips: 3,
    max: undefined,
    creatable: false,
    size: "md",
    disabled: false,
    invalid: false,
    id: undefined,
    width: undefined,
  },
);

const emit = defineEmits<{ create: [query: string] }>();

const { t } = useI18n();
const control = useControl(props);
const open = ref(false);

const known = shallowReactive(new Map<V, SelectOption<V>>());
function remember(list: readonly SelectOption<V>[]): void {
  for (const option of list) known.set(option.value, option);
}
watch(() => props.options, remember, { immediate: true });
watch(() => props.selected, remember, { immediate: true });

const chosen = computed(() => model.value.map((value) => known.get(value) ?? { value, label: String(value) }));
const shown = computed(() => chosen.value.slice(0, props.maxChips));
const hidden = computed(() => Math.max(0, chosen.value.length - props.maxChips));

function update(next: V | V[] | null): void {
  const list = Array.isArray(next) ? next : next === null ? [] : [next];
  model.value = props.max !== undefined ? list.slice(0, props.max) : list;
}

const selectable = computed(() => props.options.filter((option) => !option.disabled));
const canSelectAll = computed(() => !props.source && selectable.value.length > 0 && selectable.value.length <= 200);

function selectAll(): void {
  update(selectable.value.map((option) => option.value));
}

function onKeydown(event: KeyboardEvent): void {
  if (open.value || control.disabled.value) return;
  if (event.key === "Backspace" && model.value.length) {
    event.preventDefault();
    model.value = model.value.slice(0, -1);
  } else if (event.key === "ArrowDown") {
    event.preventDefault();
    open.value = true;
  }
}
</script>

<template>
  <UiPopover v-model:open="open" :padded="false" :width="width ?? 'max(var(--reka-popover-trigger-width), 260px)'" align="start">
    <template #trigger>
      <button
        :id="control.id.value"
        type="button"
        role="combobox"
        :aria-expanded="open"
        aria-haspopup="listbox"
        :aria-labelledby="control.labelId.value ? `${control.labelId.value} ${control.id.value}` : undefined"
        :aria-describedby="control.describedBy.value"
        :aria-invalid="control.invalid.value || undefined"
        :disabled="control.disabled.value"
        :class="['ui-control w-full !py-[3px]', controlSizeClass[size]]"
        :data-state="open ? 'open' : 'closed'"
        v-bind="controlState({ invalid: control.invalid.value, disabled: control.disabled.value })"
        @keydown="onKeydown"
      >
        <span v-if="!chosen.length" class="min-w-0 flex-1 truncate text-subtle">{{ placeholder ?? t("common.select.placeholder") }}</span>
        <span v-else-if="display === 'count' && chosen.length > 1" class="min-w-0 flex-1 truncate">{{ t("common.select.selected", { n: chosen.length }) }}</span>
        <span v-else class="flex min-w-0 flex-1 flex-wrap items-center gap-1">
          <span v-for="option in shown" :key="String(option.value)" class="ui-chip">
            <UserAvatar v-if="option.avatar" :name="option.avatar.name" :src="option.avatar.src" :size="16" class="-ml-0.5" />
            <span v-else-if="option.color" class="size-1.5 rounded-full" :style="{ background: option.color }" />
            <span class="truncate pr-0.5">{{ option.label }}</span>
          </span>
          <span v-if="hidden" class="ui-chip !px-1.5 text-muted">{{ t("common.moreCount", { n: hidden }) }}</span>
        </span>
        <ChevronsUpDown :size="controlIconSize[size] - 1" class="shrink-0 text-subtle" aria-hidden="true" />
      </button>
    </template>
    <OptionList
      :model-value="model"
      multiple
      :options="options"
      :source="source"
      :creatable="creatable"
      :search-placeholder="searchPlaceholder"
      :empty-text="emptyText"
      @update:model-value="update"
      @seen="remember"
      @create="(query) => emit('create', query)"
    >
      <template #footer>
        <div class="flex items-center gap-2 border-t border-line px-2 py-1.5 text-sm">
          <span class="flex-1 px-1 text-xs text-muted">{{ t("common.select.selected", { n: model.length }) }}</span>
          <button v-if="canSelectAll" type="button" class="rounded-[6px] px-2 py-1 font-semibold text-primary hover:bg-accent-soft" @click="selectAll">
            {{ t("common.select.selectAll") }}
          </button>
          <button
            type="button"
            class="rounded-[6px] px-2 py-1 font-semibold text-muted hover:bg-highlight hover:text-fg disabled:opacity-40"
            :disabled="!model.length"
            @click="model = []"
          >
            {{ t("common.clear") }}
          </button>
        </div>
      </template>
    </OptionList>
  </UiPopover>
</template>
