<script setup lang="ts">
/** A specimen card: the component's file name, an optional note, and the live component. */
withDefaults(defineProps<{ name: string; note?: string; wide?: boolean; flush?: boolean; canvas?: boolean }>(), { note: undefined, wide: false, flush: false, canvas: false });
</script>

<template>
  <article :class="['ui-card flex min-w-0 flex-col overflow-hidden', wide && '@5xl:col-span-2']">
    <header class="flex items-center gap-2 border-b border-line bg-surface-2/40 px-4 py-2 dark:bg-surface-2/50">
      <code class="font-mono text-xs font-semibold text-accent-fg">{{ name }}</code>
      <span v-if="note" class="min-w-0 truncate text-xs text-muted">· {{ note }}</span>
    </header>
    <div :class="['min-w-0 flex-1', !flush && 'p-4', canvas && 'bg-canvas']">
      <slot />
    </div>
  </article>
</template>
