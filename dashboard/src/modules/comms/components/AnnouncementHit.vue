<script setup lang="ts">
/** An announcement in the command palette's results (`announcements.announcement` hits). */
import { Megaphone } from "@lucide/vue";

import type { SearchHit } from "@/api/types";

defineProps<{ hit: SearchHit }>();
</script>

<template>
  <span class="flex min-w-0 items-center gap-2.5">
    <span class="grid size-6 shrink-0 place-items-center rounded-[7px] bg-accent-soft text-accent-fg"><Megaphone :size="13" aria-hidden="true" /></span>
    <span class="min-w-0 leading-tight">
      <span class="block truncate text-base font-medium text-fg">{{ hit.title }}</span>
      <span v-if="hit.subtitle" class="block truncate text-xs text-muted">{{ hit.subtitle }}</span>
    </span>
  </span>
</template>
