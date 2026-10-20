<script setup lang="ts">
/**
 * Keyboard keys: `<KbdKey keys="mod+k" />` renders ⌘ K on a Mac and Ctrl K elsewhere;
 * `<KbdKey :keys="['g', 't']" />` renders a sequence.
 */
import { computed } from "vue";

import { formatCombo, keyLabel } from "@/core/hotkeys";

const props = withDefaults(
  defineProps<{
    keys: string | string[];
    size?: "sm" | "md";
    /** For dark surfaces such as tooltips. */
    inverted?: boolean;
  }>(),
  { size: "sm", inverted: false },
);

const labels = computed(() => (Array.isArray(props.keys) ? props.keys.map((k) => keyLabel(k)) : formatCombo(props.keys)));
</script>

<template>
  <span class="inline-flex items-center gap-[3px] align-middle" :aria-label="labels.join(' ')">
    <kbd
      v-for="(label, index) in labels"
      :key="index"
      aria-hidden="true"
      :class="[
        'inline-flex select-none items-center justify-center rounded-[5px] font-sans font-medium leading-none',
        size === 'sm' ? 'h-[18px] min-w-[18px] px-[5px] text-[11px]' : 'h-[22px] min-w-[22px] px-1.5 text-xs',
        inverted
          ? 'bg-white/14 text-current ring-1 ring-inset ring-white/12'
          : 'border border-line bg-surface text-muted shadow-[0_1px_0_var(--c-border)]',
      ]"
      >{{ label }}</kbd
    >
  </span>
</template>
