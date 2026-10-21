<script setup lang="ts">
/** A knowledge base page in the command palette: its emoji, title, space and a line of text. */
import { computed } from "vue";

import type { SearchHit } from "@/api/types";

const props = defineProps<{ hit: SearchHit }>();

// The server sends "🔓 Kassani ochish": the emoji goes in the badge.
const parts = computed(() => {
  const match = /^(\p{Extended_Pictographic}[\u{FE0F}\u{200D}\p{Extended_Pictographic}]*)\s+(.*)$/u.exec(props.hit.title);
  return match ? { emoji: match[1], title: match[2] } : { emoji: "📄", title: props.hit.title };
});
</script>

<template>
  <span class="grid size-[26px] shrink-0 place-items-center rounded-[7px] border border-line bg-surface text-[14px] shadow-xs" aria-hidden="true">{{ parts.emoji }}</span>
  <span class="flex min-w-0 flex-1 flex-col leading-tight">
    <span class="truncate text-base font-medium text-fg">{{ parts.title }}</span>
    <span class="truncate text-xs text-muted">{{ hit.subtitle }}</span>
  </span>
</template>
