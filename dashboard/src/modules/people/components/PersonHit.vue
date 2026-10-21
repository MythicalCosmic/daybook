<script setup lang="ts">
/** A person in the command palette's results (`members.person` search hits). */
import type { SearchHit } from "@/api/types";
import UserAvatar from "@/components/UserAvatar.vue";

defineProps<{ hit: SearchHit }>();
</script>

<template>
  <span class="flex min-w-0 items-center gap-2.5">
    <UserAvatar :name="hit.title" :size="24" />
    <span class="min-w-0 leading-tight">
      <span class="block truncate text-base font-medium text-fg">{{ hit.title }}</span>
      <span v-if="hit.subtitle" class="block truncate text-xs text-muted">{{ hit.subtitle }}</span>
    </span>
  </span>
</template>
