<script setup lang="ts">
/**
 * An on/off switch for settings that apply at once (module switches, notifications). `label` and
 * `description` sit on the left with the switch at the end when `layout="row"` (settings lists).
 * `loading` keeps it disabled while the change saves.
 */
import { SwitchRoot, SwitchThumb } from "reka-ui";
import { useId } from "vue";

import { useControl } from "./field";
import UiSpinner from "./UiSpinner.vue";

const model = defineModel<boolean>({ default: false });

const props = withDefaults(
  defineProps<{
    label?: string;
    description?: string;
    layout?: "inline" | "row";
    size?: "sm" | "md";
    loading?: boolean;
    disabled?: boolean;
    id?: string;
  }>(),
  { label: undefined, description: undefined, layout: "inline", size: "md", loading: false, disabled: false, id: undefined },
);

const control = useControl(props);
const descriptionId = useId();
</script>

<template>
  <label
    :for="control.id.value"
    :class="[
      'group flex min-w-0 gap-3',
      layout === 'row' ? 'w-full items-start justify-between' : 'inline-flex items-center',
      control.disabled.value || loading ? 'cursor-not-allowed' : 'cursor-pointer',
    ]"
  >
    <span v-if="layout === 'row' && (label || description)" class="min-w-0 flex-1">
      <span class="block text-base font-medium text-fg">{{ label }}</span>
      <span v-if="description" :id="descriptionId" class="mt-0.5 block text-sm text-muted">{{ description }}</span>
    </span>
    <SwitchRoot
      :id="control.id.value"
      v-model="model"
      :disabled="control.disabled.value || loading"
      :aria-describedby="description ? descriptionId : control.describedBy.value"
      :aria-busy="loading || undefined"
      :class="[
        'relative inline-flex shrink-0 items-center rounded-full border border-transparent outline-offset-2 transition-colors duration-150',
        size === 'sm' ? 'h-[18px] w-[30px]' : 'h-[22px] w-[38px]',
        'bg-[color-mix(in_srgb,var(--c-text)_16%,transparent)] data-[state=checked]:bg-primary',
        'group-hover:bg-[color-mix(in_srgb,var(--c-text)_22%,transparent)] data-[state=checked]:group-hover:bg-primary-hover',
        'disabled:opacity-50',
        layout === 'row' && 'mt-0.5',
      ]"
    >
      <SwitchThumb
        :class="[
          'pointer-events-none grid place-items-center rounded-full bg-white shadow-[0_1px_2px_rgb(0_0_0/0.2),0_0_0_0.5px_rgb(0_0_0/0.04)] transition-transform duration-200 ease-out',
          size === 'sm' ? 'size-[14px] translate-x-[1px] data-[state=checked]:translate-x-[13px]' : 'size-[18px] translate-x-[1px] data-[state=checked]:translate-x-[17px]',
        ]"
      >
        <UiSpinner v-if="loading" :size="size === 'sm' ? 9 : 11" class="text-muted" />
      </SwitchThumb>
    </SwitchRoot>
    <span v-if="layout === 'inline' && (label || $slots.default)" class="min-w-0 text-base font-medium text-fg">
      <slot>{{ label }}</slot>
      <span v-if="description" :id="descriptionId" class="block text-sm font-normal text-muted">{{ description }}</span>
    </span>
  </label>
</template>
