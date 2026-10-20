<script setup lang="ts">
/**
 * A person in a table or list: avatar, name, a second line, optionally a link to their Person 360
 * page (`/c/:id/people/:memberId`) with the hover preview.
 *
 *   <PersonCell :person="row.member" :subtitle="row.position" link />
 */
import { computed } from "vue";
import { RouterLink } from "vue-router";

import { useCompanyStore } from "@/stores/company";

import HoverCard, { type PersonPreview } from "./HoverCard.vue";
import UserAvatar, { type AvatarStatus } from "./UserAvatar.vue";

const props = withDefaults(
  defineProps<{
    person: { id?: number | null; name: string; photo_url?: string | null } | null | undefined;
    subtitle?: string | null;
    /** Link the name to the person's page. */
    link?: boolean;
    /** Hover preview (needs `link` or a preview object). */
    preview?: PersonPreview | boolean;
    size?: "sm" | "md" | "lg";
    status?: AvatarStatus;
  }>(),
  { subtitle: null, link: false, preview: false, size: "md", status: undefined },
);

const company = useCompanyStore();
const to = computed(() => (props.link && props.person?.id && company.currentId ? `/c/${company.currentId}/people/${props.person.id}` : undefined));
const avatar = { sm: 22, md: 28, lg: 36 } as const;
const card = computed<PersonPreview | null>(() => {
  if (!props.person || !props.preview) return null;
  if (typeof props.preview === "object") return props.preview;
  return { name: props.person.name, photo_url: props.person.photo_url, subtitle: props.subtitle ?? undefined };
});
</script>

<template>
  <span v-if="!person" class="text-subtle">—</span>
  <span v-else class="flex min-w-0 items-center gap-2.5">
    <UserAvatar :name="person.name" :src="person.photo_url" :size="avatar[size]" :status="status" />
    <span class="min-w-0 leading-tight">
      <HoverCard v-if="card" :person="card" :to="to">
        <component
          :is="to ? RouterLink : 'span'"
          :to="to"
          :class="['block truncate font-medium text-fg', size === 'sm' ? 'text-sm' : 'text-base', to && 'hover:text-primary hover:underline hover:underline-offset-2']"
          @click.stop
          >{{ person.name }}</component
        >
      </HoverCard>
      <component
        :is="to ? RouterLink : 'span'"
        v-else
        :to="to"
        :class="['block truncate font-medium text-fg', size === 'sm' ? 'text-sm' : 'text-base', to && 'hover:text-primary hover:underline hover:underline-offset-2']"
        @click.stop
        >{{ person.name }}</component
      >
      <span v-if="subtitle" class="mt-0.5 block truncate text-xs text-muted">{{ subtitle }}</span>
    </span>
  </span>
</template>
