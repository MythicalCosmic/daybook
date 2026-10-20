<script setup lang="ts">
/**
 * Floating content anchored to a trigger (filter editors, pickers, small forms).
 * `<UiPopover><template #trigger><UiButton>…</UiButton></template> …content… </UiPopover>`
 */
import { PopoverContent, PopoverPortal, PopoverRoot, PopoverTrigger } from "reka-ui";

const open = defineModel<boolean>("open", { default: false });

withDefaults(
  defineProps<{
    side?: "top" | "right" | "bottom" | "left";
    align?: "start" | "center" | "end";
    sideOffset?: number;
    width?: string;
    padded?: boolean;
    modal?: boolean;
  }>(),
  { side: "bottom", align: "start", sideOffset: 6, width: undefined, padded: true, modal: false },
);
</script>

<template>
  <PopoverRoot v-model:open="open" :modal="modal">
    <PopoverTrigger as-child>
      <slot name="trigger" :open="open" />
    </PopoverTrigger>
    <PopoverPortal>
      <PopoverContent
        :side="side"
        :align="align"
        :side-offset="sideOffset"
        :collision-padding="8"
        :class="['anim-pop z-[70] max-h-[var(--reka-popover-content-available-height)] overflow-auto rounded-[12px] border border-line bg-surface text-fg shadow-pop outline-none', padded && 'p-3']"
        :style="width ? { width } : undefined"
      >
        <slot :close="() => (open = false)" />
      </PopoverContent>
    </PopoverPortal>
  </PopoverRoot>
</template>
