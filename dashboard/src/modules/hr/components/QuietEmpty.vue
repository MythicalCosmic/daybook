<script setup lang="ts">
/**
 * "Nothing to do here" inside an overview card: a tinted icon, one line and a hint. Calmer than a
 * page-sized empty state, since in a healthy company most of these cards are empty most days.
 */
import type { Component } from "vue";

withDefaults(defineProps<{ icon: Component; title: string; description?: string; tone?: "success" | "neutral" }>(), { description: undefined, tone: "success" });
</script>

<template>
  <div class="flex items-center gap-3 rounded-[10px] bg-surface-2/60 px-3 py-3" data-quiet-empty>
    <span :class="['grid size-9 shrink-0 place-items-center rounded-full', tone === 'success' ? 'bg-success-soft text-success' : 'bg-surface text-muted']" aria-hidden="true">
      <component :is="icon" :size="17" />
    </span>
    <div class="min-w-0">
      <p class="text-sm font-semibold text-fg">{{ title }}</p>
      <p v-if="description" class="text-xs text-muted">{{ description }}</p>
    </div>
  </div>
</template>
