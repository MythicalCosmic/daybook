<script setup lang="ts">
/**
 * One row of a settings card: the label and its explanation on the left, taking the room they need,
 * and the control on the right at a fixed width, so every number in a card lines up (the toggles of
 * ToggleSwitch rows sit on the same edge). Below 640 px the control drops under the text.
 * The slot gets `id` and `describedBy` for the control.
 */
import { useId } from "vue";

defineProps<{ label: string; hint?: string }>();

const id = useId();
const hintId = `${id}-hint`;
</script>

<template>
  <div class="flex flex-col gap-2 p-3 sm:flex-row sm:items-center sm:gap-6">
    <div class="min-w-0 flex-1">
      <label :for="id" class="text-sm font-medium text-fg">{{ label }}</label>
      <p v-if="hint" :id="hintId" class="mt-0.5 text-xs text-muted">{{ hint }}</p>
    </div>
    <div class="w-full shrink-0 sm:w-40">
      <slot :id="id" :described-by="hint ? hintId : undefined" />
    </div>
  </div>
</template>
