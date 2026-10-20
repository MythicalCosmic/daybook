<script setup lang="ts">
/** The top of a settings panel: its title, one line about it, and its actions. */
defineProps<{ title: string; description?: string }>();
</script>

<template>
  <header class="mb-5 flex flex-wrap items-start gap-x-4 gap-y-3">
    <div class="min-w-[min(100%,240px)] flex-1">
      <h2 class="text-lg font-semibold tracking-[-0.01em] text-fg">{{ title }}</h2>
      <p v-if="description" class="mt-1 max-w-[640px] text-base text-muted">{{ description }}</p>
    </div>
    <div v-if="$slots.actions" class="flex shrink-0 flex-wrap items-center gap-2">
      <slot name="actions" />
    </div>
  </header>
</template>
