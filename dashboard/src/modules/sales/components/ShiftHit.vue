<script setup lang="ts">
/** A shift in the command palette's results: "CHL-1042 · Madina Saidova", branch, day and net. */
import { Receipt } from "@lucide/vue";

import type { SearchHit } from "@/api/types";

defineProps<{ hit: SearchHit }>();
</script>

<template>
  <span
    class="grid size-[26px] shrink-0 place-items-center rounded-[7px] border border-line bg-surface text-muted shadow-xs transition-colors group-data-[highlighted]:border-transparent group-data-[highlighted]:bg-primary group-data-[highlighted]:text-on-primary"
    aria-hidden="true"
  >
    <Receipt :size="15" />
  </span>
  <span class="min-w-0 flex-1 truncate">
    <span class="text-base font-medium text-fg">{{ hit.title }}</span>
    <span class="ml-2 text-sm text-muted">{{ hit.subtitle }}</span>
  </span>
</template>
