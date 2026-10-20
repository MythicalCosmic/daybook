<script setup lang="ts">
/** The inside of one option row (icon, dot or avatar, label, description), shared by every list. */
import type { SelectOption } from "./options";
import UserAvatar from "./UserAvatar.vue";

withDefaults(defineProps<{ option: SelectOption; compact?: boolean }>(), { compact: false });
</script>

<template>
  <UserAvatar v-if="option.avatar" :name="option.avatar.name" :src="option.avatar.src" :size="option.description && !compact ? 26 : 20" />
  <component :is="option.icon" v-else-if="option.icon" :size="16" class="shrink-0 text-muted" aria-hidden="true" />
  <span v-else-if="option.color" class="size-2 shrink-0 rounded-full" :style="{ background: option.color }" aria-hidden="true" />
  <span class="min-w-0 flex-1">
    <span class="block truncate">{{ option.label }}</span>
    <span v-if="option.description && !compact" class="block truncate text-xs font-normal text-muted">{{ option.description }}</span>
  </span>
</template>
