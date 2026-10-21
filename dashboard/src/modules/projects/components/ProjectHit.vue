<script setup lang="ts">
/** A project in the command palette's results: key chip, name, status and lead. */
import { CornerDownLeft } from "@lucide/vue";
import { computed } from "vue";

import type { SearchHit } from "@/api/types";

const props = defineProps<{ hit: SearchHit }>();

const parts = computed(() => {
  const [key, ...rest] = props.hit.title.split(" · ");
  return { key: rest.length ? key : "", name: rest.length ? rest.join(" · ") : props.hit.title };
});
</script>

<template>
  <span
    class="grid h-[26px] min-w-[26px] shrink-0 place-items-center rounded-[7px] border border-line bg-surface px-1 font-mono text-[10px] font-bold tracking-wide text-muted shadow-xs transition-colors group-data-[highlighted]:border-transparent group-data-[highlighted]:bg-primary group-data-[highlighted]:text-on-primary"
    aria-hidden="true"
    >{{ parts.key || "#" }}</span
  >
  <span class="min-w-0 flex-1 truncate">
    <span class="text-base font-medium text-fg">{{ parts.name }}</span>
    <span v-if="hit.subtitle" class="ml-2 text-sm text-muted">{{ hit.subtitle }}</span>
  </span>
  <CornerDownLeft :size="15" class="hidden shrink-0 text-subtle group-data-[highlighted]:block" aria-hidden="true" />
</template>
