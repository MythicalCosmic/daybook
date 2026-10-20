<script setup lang="ts" generic="V extends string | number">
/**
 * Two to five mutually exclusive views or ranges side by side ("Table · Board · Calendar",
 * "Today · 7d · 30d"). The thumb slides to the chosen segment; arrow keys move it.
 *
 *   <SegmentedControl v-model="view" :options="[{ value: 'table', label: t('tasks.table'), icon: Rows3 }, …]" />
 */
import { RadioGroupItem, RadioGroupRoot } from "reka-ui";
import { nextTick, onMounted, ref, watch, type Component } from "vue";

import { formatCount } from "@/lib/format";

export interface SegmentOption<T> {
  value: T;
  label: string;
  icon?: Component;
  count?: number;
  disabled?: boolean;
  /** Hide the label and keep the icon (the label stays as the accessible name). */
  iconOnly?: boolean;
}

const model = defineModel<V>({ required: true });

const props = withDefaults(
  defineProps<{
    options: SegmentOption<V>[];
    size?: "sm" | "md";
    block?: boolean;
    disabled?: boolean;
    ariaLabel?: string;
  }>(),
  { size: "md", block: false, disabled: false, ariaLabel: undefined },
);

const root = ref<HTMLElement | null>(null);
const thumb = ref<{ left: number; width: number } | null>(null);

function measure(): void {
  const el = root.value?.querySelector<HTMLElement>('[data-state="checked"]');
  thumb.value = el ? { left: el.offsetLeft, width: el.offsetWidth } : null;
}

watch([model, () => props.options], () => nextTick(measure), { deep: true });
onMounted(() => {
  measure();
  void document.fonts?.ready.then(measure);
});

function onUpdate(value: unknown): void {
  model.value = value as V;
}
</script>

<template>
  <RadioGroupRoot
    :model-value="model"
    :disabled="disabled"
    :aria-label="ariaLabel"
    orientation="horizontal"
    loop
    :class="['relative isolate inline-flex shrink-0 rounded-[9px] bg-surface-2 p-0.5 dark:bg-surface-3/60', block && 'flex w-full']"
    @update:model-value="onUpdate"
  >
    <div ref="root" class="contents">
      <span
        v-if="thumb"
        class="pointer-events-none absolute inset-y-0.5 -z-10 rounded-[7px] bg-surface shadow-raised transition-[left,width] duration-240 ease-out dark:bg-surface-2"
        :style="{ left: `${thumb.left}px`, width: `${thumb.width}px` }"
        aria-hidden="true"
      />
      <RadioGroupItem
        v-for="option in options"
        :key="String(option.value)"
        :value="option.value"
        :disabled="option.disabled"
        :aria-label="option.iconOnly ? option.label : undefined"
        :title="option.iconOnly ? option.label : undefined"
        :class="[
          'relative inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded-[7px] font-semibold outline-offset-[-2px] transition-colors duration-150',
          size === 'sm' ? 'h-6 px-2 text-xs' : 'h-7 px-2.5 text-sm',
          option.iconOnly && (size === 'sm' ? 'w-7 px-0' : 'w-8 px-0'),
          block && 'flex-1',
          'text-muted hover:text-fg data-[state=checked]:text-fg data-[disabled]:pointer-events-none data-[disabled]:opacity-40',
          !thumb && 'data-[state=checked]:bg-surface data-[state=checked]:shadow-raised',
        ]"
      >
        <component :is="option.icon" v-if="option.icon" :size="size === 'sm' ? 13 : 15" aria-hidden="true" />
        <span v-if="!option.iconOnly">{{ option.label }}</span>
        <span
          v-if="option.count !== undefined"
          class="rounded-full bg-[color-mix(in_srgb,var(--c-text)_8%,transparent)] px-1.5 py-px text-[10px] leading-none tabular-nums"
          >{{ formatCount(option.count) }}</span
        >
      </RadioGroupItem>
    </div>
  </RadioGroupRoot>
</template>
