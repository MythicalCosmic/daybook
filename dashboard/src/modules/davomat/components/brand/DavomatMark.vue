<script setup lang="ts">
/** Davomat's mark: a bold D with a check cut into it, on an indigo tile (core/brand.ts has the shapes and draws the same as the favicon). */
import { useId } from "vue";

import { DAVOMAT_MARK } from "@/core/brand";

withDefaults(defineProps<{ size?: number }>(), { size: 40 });

// Each copy has its own gradients: a second copy that is hidden would otherwise blank the first.
const id = `dm-${useId()}`;
</script>

<template>
  <svg viewBox="0 0 48 48" :width="size" :height="size" class="shrink-0" aria-hidden="true">
    <defs>
      <linearGradient :id="id" gradientUnits="userSpaceOnUse" x1="7.2" y1="0" x2="40.8" y2="48">
        <stop offset="0" :stop-color="DAVOMAT_MARK.from" />
        <stop offset="1" :stop-color="DAVOMAT_MARK.to" />
      </linearGradient>
      <linearGradient :id="`${id}-lit`" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stop-color="#fff" stop-opacity=".2" />
        <stop offset=".55" stop-color="#fff" stop-opacity="0" />
      </linearGradient>
    </defs>
    <rect width="48" height="48" rx="13.5" :fill="`url(#${id})`" />
    <path :d="DAVOMAT_MARK.d" fill="#fff" />
    <path :d="DAVOMAT_MARK.check" fill="none" :stroke="`url(#${id})`" stroke-width="3.4" stroke-linecap="round" stroke-linejoin="round" />
    <rect width="48" height="48" rx="13.5" :fill="`url(#${id}-lit)`" />
    <rect x=".5" y=".5" width="47" height="47" rx="13" fill="none" stroke="#fff" stroke-opacity=".1" />
  </svg>
</template>
