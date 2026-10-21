<script setup lang="ts">
/** A company event in the command palette: its kind mark, title and when/where. */
import { computed } from "vue";

import type { SearchHit } from "@/api/types";

const props = defineProps<{ hit: SearchHit }>();

const parts = computed(() => {
  const match = /^(\p{Extended_Pictographic}\u{FE0F}?)\s+(.*)$/u.exec(props.hit.title);
  return match ? { mark: match[1], title: match[2] } : { mark: "🗓", title: props.hit.title };
});
</script>

<template>
  <span class="grid size-[26px] shrink-0 place-items-center rounded-[7px] border border-line bg-surface text-[13px] shadow-xs" aria-hidden="true">{{ parts.mark }}</span>
  <span class="flex min-w-0 flex-1 flex-col leading-tight">
    <span class="truncate text-base font-medium text-fg">{{ parts.title }}</span>
    <span class="truncate text-xs text-muted">{{ hit.subtitle }}</span>
  </span>
</template>
