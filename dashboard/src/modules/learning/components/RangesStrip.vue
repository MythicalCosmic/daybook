<script setup lang="ts">
/**
 * The parts of a video someone actually played, as filled stretches of a bar (docs/PLAN-LEARNING.md
 * §4.2): gaps are what they skipped. Read out as "Watched 62 %".
 */
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import { segments } from "../lib";

const props = withDefaults(defineProps<{ ranges: readonly (readonly [number, number])[]; duration: number; percent?: number; size?: "sm" | "md" }>(), {
  percent: undefined,
  size: "md",
});

const { t } = useI18n();
const parts = computed(() => segments(props.ranges, props.duration));
const label = computed(() => t("learning.watched.strip", { percent: props.percent ?? Math.round(parts.value.reduce((sum, part) => sum + part.width, 0)) }));
</script>

<template>
  <div
    class="relative w-full overflow-hidden rounded-full bg-[color-mix(in_srgb,var(--c-text)_8%,transparent)]"
    :class="size === 'sm' ? 'h-1.5' : 'h-2.5'"
    role="img"
    :aria-label="label"
    :title="label"
  >
    <span
      v-for="(part, index) in parts"
      :key="index"
      class="absolute inset-y-0 rounded-full bg-primary"
      :style="{ left: `${part.left}%`, width: `${part.width}%` }"
    />
  </div>
</template>
