<script setup lang="ts">
/** A company event in the command palette: a calendar mark, the title and when/where. */
import { CalendarDays } from "@lucide/vue";
import { computed } from "vue";

import type { SearchHit } from "@/api/types";

const props = defineProps<{ hit: SearchHit }>();

// Older servers put a pictogram before the title ("🗓 Inventarizatsiya"): the texts carry no emoji,
// so it is dropped and the mark is an icon.
const title = computed(() => props.hit.title.replace(/^\p{Extended_Pictographic}\u{FE0F}?\s+/u, ""));
</script>

<template>
  <span class="grid size-[26px] shrink-0 place-items-center rounded-[7px] border border-line bg-surface text-muted shadow-xs" aria-hidden="true"><CalendarDays :size="14" /></span>
  <span class="flex min-w-0 flex-1 flex-col leading-tight">
    <span class="truncate text-base font-medium text-fg">{{ title }}</span>
    <span class="truncate text-xs text-muted">{{ hit.subtitle }}</span>
  </span>
</template>
