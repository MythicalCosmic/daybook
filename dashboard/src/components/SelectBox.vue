<script setup lang="ts" generic="V extends OptionValue">
/**
 * Pick one value from a short list (status, period, payment method). Long or remote lists use
 * ComboBox. Options can carry an icon, a color dot, an avatar and a description, and be grouped.
 *
 *   <SelectBox v-model="status" :options="[{ value: 'open', label: t('tasks.open') }, …]" />
 */
import { Check, ChevronDown, ChevronsUpDown, ChevronUp, X } from "@lucide/vue";
import {
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectItemIndicator,
  SelectItemText,
  SelectLabel,
  SelectPortal,
  SelectRoot,
  SelectScrollDownButton,
  SelectScrollUpButton,
  SelectTrigger,
  SelectViewport,
} from "reka-ui";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import { controlIconSize, controlSizeClass, controlState, useControl, type ControlSize } from "./field";
import OptionRow from "./OptionRow.vue";
import { groupOptions, type OptionValue, type SelectOption } from "./options";

const model = defineModel<V | null>({ default: null });

const props = withDefaults(
  defineProps<{
    options: SelectOption<V>[];
    placeholder?: string;
    size?: ControlSize;
    clearable?: boolean;
    disabled?: boolean;
    invalid?: boolean;
    id?: string;
    /** "ghost" drops the border (toolbars, table cells). */
    variant?: "field" | "ghost";
  }>(),
  { placeholder: undefined, size: "md", clearable: false, disabled: false, invalid: false, id: undefined, variant: "field" },
);

const { t } = useI18n();
const control = useControl(props);
const open = ref(false);

const current = computed(() => props.options.find((option) => option.value === model.value) ?? null);
const groups = computed(() => groupOptions(props.options));

function onUpdate(value: unknown): void {
  model.value = (value ?? null) as V | null;
}
</script>

<template>
  <div class="relative min-w-0">
    <SelectRoot v-model:open="open" :model-value="model ?? undefined" :disabled="control.disabled.value" @update:model-value="onUpdate">
      <SelectTrigger
        :id="control.id.value"
        :aria-labelledby="control.labelId.value ? `${control.labelId.value} ${control.id.value}` : undefined"
        :aria-describedby="control.describedBy.value"
        :aria-invalid="control.invalid.value || undefined"
        :class="[
          'ui-control w-full',
          controlSizeClass[size],
          variant === 'ghost' && '!border-transparent !bg-transparent !shadow-none hover:!bg-highlight',
          clearable && current && '!pr-12',
        ]"
        v-bind="controlState({ invalid: control.invalid.value, disabled: control.disabled.value })"
      >
        <span v-if="current" class="flex min-w-0 flex-1 items-center gap-2"><OptionRow :option="current" compact /></span>
        <span v-else class="min-w-0 flex-1 truncate text-subtle">{{ placeholder ?? t("common.select.placeholder") }}</span>
        <ChevronsUpDown :size="controlIconSize[size] - 1" class="shrink-0 text-subtle" aria-hidden="true" />
      </SelectTrigger>
      <SelectPortal>
        <SelectContent
          position="popper"
          :side-offset="6"
          :collision-padding="8"
          class="ui-menu anim-pop max-h-[min(360px,var(--reka-select-content-available-height))] min-w-[var(--reka-select-trigger-width)]"
        >
          <SelectScrollUpButton class="flex h-6 items-center justify-center text-subtle"><ChevronUp :size="14" /></SelectScrollUpButton>
          <SelectViewport class="p-1">
            <SelectGroup v-for="group in groups" :key="group.label ?? '_'">
              <SelectLabel v-if="group.label" class="ui-option-label">{{ group.label }}</SelectLabel>
              <SelectItem v-for="option in group.options" :key="String(option.value)" :value="option.value" :disabled="option.disabled" class="ui-option">
                <OptionRow :option="option" />
                <SelectItemText class="sr-only">{{ option.label }}</SelectItemText>
                <SelectItemIndicator class="shrink-0 text-primary"><Check :size="15" /></SelectItemIndicator>
              </SelectItem>
            </SelectGroup>
          </SelectViewport>
          <SelectScrollDownButton class="flex h-6 items-center justify-center text-subtle"><ChevronDown :size="14" /></SelectScrollDownButton>
        </SelectContent>
      </SelectPortal>
    </SelectRoot>
    <button
      v-if="clearable && current && !control.disabled.value"
      type="button"
      class="pressable absolute right-7 top-1/2 grid size-5 -translate-y-1/2 place-items-center rounded-full text-subtle hover:bg-highlight hover:text-fg"
      :aria-label="t('common.clear')"
      @click="model = null"
    >
      <X :size="13" />
    </button>
  </div>
</template>
