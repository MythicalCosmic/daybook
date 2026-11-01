<script setup lang="ts">
/** An agent's icon in its circle: warm while on, quiet while off, breathing while it works. */
import { computed } from "vue";

import { agentIcon } from "../meta";

const props = withDefaults(defineProps<{ name: string | null | undefined; size?: "sm" | "md" | "lg"; on?: boolean; busy?: boolean }>(), {
  size: "md",
  on: true,
  busy: false,
});

const icon = computed(() => agentIcon(props.name));
const box = { sm: "size-7", md: "size-10", lg: "size-12" } as const;
const glyph = { sm: 14, md: 19, lg: 22 } as const;
</script>

<template>
  <span
    :class="[
      'ai-agent-icon relative grid shrink-0 place-items-center rounded-full',
      box[size],
      on ? 'bg-accent-soft text-accent-fg' : 'bg-surface-2 text-subtle dark:bg-surface-3',
      busy && 'is-busy',
    ]"
    aria-hidden="true"
  >
    <component :is="icon" :size="glyph[size]" />
  </span>
</template>

<style scoped>
.ai-agent-icon.is-busy::after {
  content: "";
  position: absolute;
  inset: -3px;
  border-radius: 999px;
  border: 2px solid color-mix(in srgb, var(--c-primary) 55%, transparent);
  animation: ai-ring 1.6s var(--ease-standard) infinite;
}
@keyframes ai-ring {
  0% {
    opacity: 0.9;
    transform: scale(0.92);
  }
  100% {
    opacity: 0;
    transform: scale(1.22);
  }
}
</style>
