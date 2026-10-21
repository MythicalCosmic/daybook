<script setup lang="ts">
/**
 * Overlapping avatars for a group (assignees, who's in, project members): the first `max` and a
 * "+N" chip whose tooltip lists the rest.
 */
import { computed } from "vue";

import UiTooltip from "./UiTooltip.vue";
import UserAvatar from "./UserAvatar.vue";

export interface StackPerson {
  id?: number | string;
  name: string;
  photo_url?: string | null;
}

const props = withDefaults(defineProps<{ people: StackPerson[]; max?: number; size?: number; tooltips?: boolean }>(), {
  max: 4,
  size: 24,
  tooltips: true,
});

const shown = computed(() => props.people.slice(0, props.max));
const rest = computed(() => props.people.slice(props.max));
// 15 % of the size: enough to read as a stack while the next ring stays clear of the initials.
const overlap = computed(() => Math.round(props.size * 0.15));
</script>

<template>
  <span class="inline-flex items-center" :aria-label="people.map((p) => p.name).join(', ')" role="group">
    <template v-for="(person, index) in shown" :key="person.id ?? person.name">
      <UiTooltip :content="person.name" :disabled="!tooltips">
        <span
          class="relative inline-flex rounded-full ring-2 ring-[var(--avatar-ring,var(--c-surface))]"
          :style="{ marginLeft: index ? `-${overlap}px` : undefined, zIndex: shown.length - index }"
        >
          <UserAvatar :name="person.name" :src="person.photo_url" :size="size" />
        </span>
      </UiTooltip>
    </template>
    <UiTooltip v-if="rest.length" :content="rest.map((p) => p.name).join(', ')" :disabled="!tooltips">
      <span
        class="relative grid shrink-0 place-items-center rounded-full bg-surface-2 px-1.5 font-semibold tabular-nums text-muted ring-2 ring-[var(--avatar-ring,var(--c-surface))] dark:bg-surface-3"
        :style="{ marginLeft: `-${overlap}px`, height: `${size}px`, minWidth: `${size}px`, fontSize: `${Math.max(10, Math.round(size * 0.4))}px` }"
        >+{{ rest.length }}</span
      >
    </UiTooltip>
  </span>
</template>
