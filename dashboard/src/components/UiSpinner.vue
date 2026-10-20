<script setup lang="ts">
/** A small activity ring that inherits the text color. */
withDefaults(defineProps<{ size?: number; label?: string }>(), { size: 16, label: undefined });
</script>

<template>
  <svg
    class="ui-spinner shrink-0"
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    fill="none"
    :role="label ? 'status' : undefined"
    :aria-label="label"
    :aria-hidden="label ? undefined : 'true'"
  >
    <circle cx="12" cy="12" r="9" stroke="currentColor" stroke-opacity="0.2" stroke-width="2.5" />
    <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" />
  </svg>
</template>

<style scoped>
.ui-spinner {
  animation: spin 0.7s linear infinite;
}
</style>
