<script setup lang="ts">
/** One section of the component kitchen: an anchor, a title, a line about what is here, specimens. */
defineProps<{ id: string; title: string; description?: string }>();
</script>

<template>
  <section :id="id" class="scroll-mt-24">
    <header class="mb-4 flex flex-col gap-x-3 gap-y-1 border-b border-line pb-3 sm:flex-row sm:items-baseline">
      <h2 class="shrink-0 text-lg font-semibold tracking-[-0.01em] text-fg">{{ title }}</h2>
      <p v-if="description" class="min-w-0 text-sm text-muted sm:truncate">{{ description }}</p>
    </header>
    <div class="grid grid-cols-1 items-start gap-4 @5xl:grid-cols-2">
      <slot />
    </div>
  </section>
</template>
