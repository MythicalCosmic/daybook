<script setup lang="ts">
/**
 * One person on the org chart: photo, name and their most telling status as a small icon. Click
 * (or Enter) opens Person 360; hovering shows the card with "Move…". Someone the viewer may move
 * can be dragged onto another department or branch, or picked up with Space and moved with the
 * arrows (the page runs the move); the rest carry a lock that says why.
 */
import { CalendarClock, DoorOpen, Ellipsis, Lock, Palmtree, PauseCircle, Shuffle } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import DropdownMenu from "@/components/DropdownMenu.vue";
import HoverCard from "@/components/HoverCard.vue";
import type { MenuEntry } from "@/components/menuTypes";
import UiTooltip from "@/components/UiTooltip.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { useFormat } from "@/lib/useFormat";

import { useOrgContext } from "./context";
import OrgPersonCard from "./OrgPersonCard.vue";
import { badges } from "./tree";
import type { OrgPerson } from "./types";

const props = withDefaults(defineProps<{ person: OrgPerson; role?: string | null; size?: "row" | "head" }>(), { role: null, size: "row" });

const { t } = useI18n();
const fmt = useFormat();
const org = useOrgContext();

const ICONS = { suspended: PauseCircle, leaving: DoorOpen, asked: CalendarClock, away: Palmtree, change: Shuffle } as const;
const TONES = { danger: "text-danger", warning: "text-warning", info: "text-info", primary: "text-primary", success: "text-success", neutral: "text-muted" } as const;
const shown = computed(() => badges(props.person).slice(0, 2));
const label = (key: string, day: string | null) => (day ? t(`lifecycle.org.badge.${key}`, { date: fmt.day(day, "short") }) : t(`lifecycle.org.badge.${key}Open`));

const found = computed(() => org.highlight.value === props.person.id);
const lifted = computed(() => org.picked.value?.person.id === props.person.id);
const dragged = computed(() => org.dragging.value?.id === props.person.id);
const locked = computed(() => org.can.value.move && !props.person.may_move);
const position = computed(() => (props.person.position_id !== null ? (org.positions.value.get(props.person.position_id)?.name ?? null) : null));

const menu = computed<MenuEntry[]>(() => [
  { label: t("common.person.open"), onSelect: () => org.openPerson(props.person) },
  ...(org.can.value.move
    ? [
        {
          label: t("lifecycle.org.move"),
          icon: Shuffle,
          disabled: !props.person.may_move,
          description: props.person.may_move ? t("lifecycle.org.moveHint") : props.person.why_not ? t(`lifecycle.org.whyNot.${props.person.why_not}`) : undefined,
          onSelect: () => org.startMove(props.person),
        } satisfies MenuEntry,
      ]
    : []),
]);
</script>

<template>
  <HoverCard side="right" align="start" :open-delay="420" width="300px">
    <div
      role="button"
      tabindex="0"
      :draggable="person.may_move ? 'true' : 'false'"
      :aria-label="t('lifecycle.org.personLabel', { name: person.name, position: role ?? position ?? t('lifecycle.org.noPosition') })"
      :aria-roledescription="person.may_move ? t('lifecycle.org.draggable') : undefined"
      :aria-pressed="lifted ? 'true' : undefined"
      :class="[
        'org-person group/person relative flex min-w-0 cursor-pointer select-none items-center gap-2.5 rounded-[10px] px-2 outline-none transition-[background-color,box-shadow,opacity] duration-150',
        size === 'head' ? 'py-1.5' : 'py-1',
        'hover:bg-surface-2/80 focus-visible:ring-2 focus-visible:ring-[var(--c-ring)] dark:hover:bg-surface-3/60',
        found ? 'org-found bg-accent-soft ring-2 ring-[var(--c-primary)]' : '',
        lifted ? 'bg-surface shadow-[var(--sh-pop)] ring-2 ring-[var(--c-primary)]' : '',
        dragged ? 'opacity-40' : '',
        person.may_move ? 'active:cursor-grabbing' : '',
      ]"
      :data-person-id="person.id"
      :data-movable="person.may_move ? 'true' : undefined"
      @click="org.openPerson(person)"
      @keydown="org.personKey(person, $event)"
      @dragstart="org.dragStart(person, $event)"
      @dragend="org.dragEnd()"
    >
      <UserAvatar :name="person.name" :src="person.photo_url" :size="size === 'head' ? 34 : 26" />
      <span class="min-w-0 flex-1 leading-tight">
        <span :class="['block truncate text-fg', size === 'head' ? 'text-base font-semibold' : 'text-sm font-medium']">{{ person.name }}</span>
        <span v-if="role" class="block truncate text-xs text-muted">{{ role }}</span>
      </span>
      <span class="flex shrink-0 items-center gap-1">
        <UiTooltip v-for="badge in shown" :key="badge.key" :content="label(badge.key, badge.day)">
          <component :is="ICONS[badge.key]" :size="14" :class="TONES[badge.tone]" :aria-label="label(badge.key, badge.day)" role="img" />
        </UiTooltip>
        <UiTooltip v-if="locked && person.why_not" :content="t(`lifecycle.org.whyNot.${person.why_not}`)">
          <Lock :size="12" class="text-subtle opacity-0 transition-opacity group-hover/person:opacity-100 group-focus-visible/person:opacity-100" aria-hidden="true" />
        </UiTooltip>
        <span class="opacity-0 transition-opacity group-hover/person:opacity-100 group-focus-within/person:opacity-100" @click.stop @keydown.stop>
          <DropdownMenu :items="menu" align="start" width="240px">
            <template #trigger>
              <button type="button" class="grid size-6 place-items-center rounded-[6px] text-muted hover:bg-surface-3/70 hover:text-fg" :aria-label="t('lifecycle.org.actionsFor', { name: person.name })" data-person-menu>
                <Ellipsis :size="14" />
              </button>
            </template>
          </DropdownMenu>
        </span>
      </span>
    </div>
    <template #content>
      <OrgPersonCard :person="person" />
    </template>
  </HoverCard>
</template>

<style scoped>
.org-found {
  animation: org-found 1.6s var(--ease-out, ease) 2;
}
@keyframes org-found {
  0%,
  100% {
    box-shadow: 0 0 0 0 color-mix(in srgb, var(--c-primary) 35%, transparent);
  }
  50% {
    box-shadow: 0 0 0 6px color-mix(in srgb, var(--c-primary) 0%, transparent);
  }
}
@media (prefers-reduced-motion: reduce) {
  .org-found {
    animation: none;
  }
}
</style>
