<script setup lang="ts">
/** One section of the component kitchen: an anchor, a title, a line about what is here, specimens. */
defineProps<{ id: string; title: string; description?: string }>();
</script>

<template>
  <section :id="id" class="scroll-mt-24">
    <header class="mb-4 flex items-baseline gap-3 border-b border-line pb-3">
      <h2 class="text-lg font-semibold tracking-[-0.01em] text-fg">{{ title }}</h2>
      <p v-if="description" class="min-w-0 truncate text-sm text-muted">{{ description }}</p>
    </header>
    <div class="grid grid-cols-1 gap-4 @5xl:grid-cols-2">
      <slot />
    </div>
  </section>
</template>
