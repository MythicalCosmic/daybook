<script setup lang="ts">
/**
 * A short label on hover or focus, optionally with a shortcut: `<UiTooltip content="Inbox" shortcut="g i">`.
 * The default slot is the trigger (rendered as-is). Needs the TooltipProvider that App.vue mounts.
 */
import { TooltipArrow, TooltipContent, TooltipPortal, TooltipRoot, TooltipTrigger } from "reka-ui";

import KbdKey from "./KbdKey.vue";

withDefaults(
  defineProps<{
    content?: string;
    shortcut?: string;
    side?: "top" | "right" | "bottom" | "left";
    align?: "start" | "center" | "end";
    sideOffset?: number;
    disabled?: boolean;
    delay?: number;
  }>(),
  { content: undefined, shortcut: undefined, side: "top", align: "center", sideOffset: 6, disabled: false, delay: undefined },
);
</script>

<template>
  <slot v-if="disabled || (!content && !$slots.content)" />
  <TooltipRoot v-else :delay-duration="delay">
    <TooltipTrigger as-child>
      <slot />
    </TooltipTrigger>
    <TooltipPortal>
      <TooltipContent
        :side="side"
        :align="align"
        :side-offset="sideOffset"
        :collision-padding="8"
        class="anim-pop z-[80] flex max-w-[280px] select-none items-center gap-2 rounded-[7px] bg-[#201e1d] px-2 py-1 text-xs font-medium text-[#f7f3ec] shadow-pop dark:bg-surface-3 dark:text-fg"
      >
        <slot name="content">{{ content }}</slot>
        <KbdKey v-if="shortcut" :keys="shortcut" inverted class="-mr-0.5 opacity-90" />
        <TooltipArrow class="fill-[#201e1d] dark:fill-[var(--c-surface-3)]" :width="10" :height="5" />
      </TooltipContent>
    </TooltipPortal>
  </TooltipRoot>
</template>
