<script setup lang="ts">
/** A branch in the command palette's results ("companies.branches"): name, address, a shop icon. */
import { Store } from "@lucide/vue";

import type { SearchHit } from "@/api/types";

defineProps<{ hit: SearchHit }>();
</script>

<template>
  <span
    class="grid size-[26px] shrink-0 place-items-center rounded-[7px] border border-line bg-surface text-muted shadow-xs transition-colors group-data-[highlighted]:border-transparent group-data-[highlighted]:bg-primary group-data-[highlighted]:text-on-primary"
  >
    <Store :size="15" aria-hidden="true" />
  </span>
  <span class="min-w-0 flex-1">
    <span class="block truncate text-base font-medium text-fg">{{ hit.title }}</span>
    <span v-if="hit.subtitle" class="block truncate text-xs text-muted">{{ hit.subtitle }}</span>
  </span>
</template>
