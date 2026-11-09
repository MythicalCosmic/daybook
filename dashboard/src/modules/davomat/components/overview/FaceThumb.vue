<script setup lang="ts">
/**
 * A face: the terminal's snapshot or the profile photo (initials when neither), in a soft ring of
 * its status colour. Without a name (an unknown face) and without a photo, a face outline.
 */
import { ScanFace } from "@lucide/vue";

import UserAvatar from "@/components/UserAvatar.vue";

import type { FaceTone } from "./overviewApi";

withDefaults(defineProps<{ src?: string | null; name?: string; size?: number; tone?: FaceTone }>(), { src: null, name: "", size: 40, tone: "neutral" });

const rings: Record<FaceTone, string> = {
  success: "ring-success/55",
  warning: "ring-warning/60",
  danger: "ring-danger/55",
  info: "ring-info/50",
  primary: "ring-primary/50",
  neutral: "ring-line-strong",
};
</script>

<template>
  <span :class="['inline-flex shrink-0 rounded-full ring-2 ring-offset-2 ring-offset-[var(--c-surface)]', rings[tone]]" :style="{ width: `${size}px`, height: `${size}px` }">
    <UserAvatar v-if="name || src" :name="name" :src="src" :size="size" />
    <span v-else class="grid size-full place-items-center rounded-full bg-surface-2 text-subtle"><ScanFace :size="Math.round(size * 0.5)" aria-hidden="true" /></span>
  </span>
</template>
