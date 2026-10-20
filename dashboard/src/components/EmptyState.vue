<script setup lang="ts">
/**
 * Nothing here yet: a small brand mark, a Caprasimo headline, one sentence, one action.
 * `size="sm"` fits inside cards and drawers; "lg" fills a page.
 */
import type { Component } from "vue";

withDefaults(
  defineProps<{
    title: string;
    description?: string;
    icon?: Component;
    size?: "sm" | "md" | "lg";
    tone?: "primary" | "success" | "neutral";
  }>(),
  { description: undefined, icon: undefined, size: "md", tone: "primary" },
);

const tones = {
  primary: { ring: "var(--c-accent-soft)", fg: "var(--c-primary)", dot: "var(--c-success)" },
  success: { ring: "var(--c-success-soft)", fg: "var(--c-success)", dot: "var(--c-primary)" },
  neutral: { ring: "var(--c-surface-2)", fg: "var(--c-muted)", dot: "var(--c-primary)" },
} as const;
</script>

<template>
  <div
    :class="[
      'flex flex-col items-center text-center',
      size === 'sm' ? 'gap-2 px-4 py-8' : size === 'md' ? 'gap-3 px-6 py-14' : 'gap-4 px-6 py-24',
    ]"
  >
    <slot name="illustration">
      <div class="relative" :class="size === 'sm' ? 'mb-1' : 'mb-2'" aria-hidden="true">
        <div
          class="grid place-items-center rounded-full"
          :class="size === 'sm' ? 'size-12' : 'size-16'"
          :style="{ background: tones[tone].ring, color: tones[tone].fg, boxShadow: `0 0 0 8px color-mix(in srgb, ${tones[tone].ring} 45%, transparent)` }"
        >
          <component :is="icon" v-if="icon" :size="size === 'sm' ? 20 : 26" />
          <svg v-else :width="size === 'sm' ? 20 : 26" :height="size === 'sm' ? 20 : 26" viewBox="0 0 24 24" fill="none">
            <path d="M5.5 12.4 9.8 16.6 18.5 7.4" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
        </div>
        <span
          class="absolute -bottom-0.5 -right-0.5 rounded-full ring-[3px] ring-[var(--c-surface)]"
          :class="size === 'sm' ? 'size-3.5' : 'size-[18px]'"
          :style="{ background: tones[tone].dot }"
        />
      </div>
    </slot>
    <h3 :class="['font-display text-fg', size === 'sm' ? 'text-md' : size === 'md' ? 'text-lg' : 'text-xl']">{{ title }}</h3>
    <p v-if="description" :class="['max-w-[380px] text-muted', size === 'sm' ? 'text-sm' : 'text-base']">{{ description }}</p>
    <div v-if="$slots.default" class="mt-2 flex flex-wrap items-center justify-center gap-2">
      <slot />
    </div>
  </div>
</template>
