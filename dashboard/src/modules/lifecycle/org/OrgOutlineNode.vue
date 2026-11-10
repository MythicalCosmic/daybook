<script setup lang="ts">
/**
 * One part of the phone outline: a row that folds open (the top level starts open, deeper parts
 * folded), then its head, people by job title, open places, and the parts below, indented.
 */
import { ChevronRight, Ellipsis, MapPin, Network, Shuffle, UserRoundPlus, Users } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink } from "vue-router";

import DropdownMenu from "@/components/DropdownMenu.vue";
import type { MenuEntry } from "@/components/menuTypes";
import StatusPill from "@/components/StatusPill.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { useFormat } from "@/lib/useFormat";

import { useOrgContext } from "./context";
import { badges, type OrgNode } from "./tree";
import type { OrgPerson } from "./types";

defineOptions({ name: "OrgOutlineNode" });
const props = defineProps<{ node: OrgNode; depth: number }>();

const { t } = useI18n();
const fmt = useFormat();
const org = useOrgContext();

// Folded keys are shared with the canvas; deeper parts start folded on a phone ("~" marks open).
const openKey = computed(() => `~${props.node.key}`);
const open = computed(() => (props.depth === 0 ? !org.isCollapsed(props.node.key) : org.isCollapsed(openKey.value)));
function toggle(): void {
  org.toggle(props.depth === 0 ? props.node.key : openKey.value);
}
const title = computed(() => (props.node.kind === "unplaced" ? (org.view.value === "department" ? t("lifecycle.org.unplaced") : t("lifecycle.org.noBranch")) : props.node.name));
const icon = computed(() => (props.node.kind === "branch" ? MapPin : props.node.kind === "unplaced" ? Users : Network));
const headRole = computed(() => (props.node.kind === "branch" ? t("lifecycle.org.manager") : t("lifecycle.org.head")));

const label = (key: string, day: string | null) => (day ? t(`lifecycle.org.badge.${key}`, { date: fmt.day(day, "short") }) : t(`lifecycle.org.badge.${key}Open`));
function menu(person: OrgPerson): MenuEntry[] {
  const items: MenuEntry[] = [{ label: t("common.person.open"), onSelect: () => org.openPerson(person) }];
  if (org.can.value.move)
    items.push({
      label: t("lifecycle.org.move"),
      icon: Shuffle,
      disabled: !person.may_move,
      description: person.may_move ? undefined : person.why_not ? t(`lifecycle.org.whyNot.${person.why_not}`) : undefined,
      onSelect: () => org.startMove(person),
    });
  return items;
}
</script>

<template>
  <li :class="depth === 0 ? 'ui-card overflow-hidden' : ''" :data-node="node.key">
    <button
      type="button"
      class="flex w-full min-w-0 items-center gap-2.5 px-3.5 py-3 text-left active:bg-surface-2"
      :aria-expanded="open"
      data-outline-toggle
      @click="toggle"
    >
      <ChevronRight :size="16" :class="['shrink-0 text-subtle transition-transform duration-200', open ? 'rotate-90' : '']" aria-hidden="true" />
      <span class="grid size-7 shrink-0 place-items-center rounded-[8px]" :style="{ background: `color-mix(in srgb, ${org.accent(node.key)} 14%, transparent)`, color: org.accent(node.key) }">
        <component :is="icon" :size="14" aria-hidden="true" />
      </span>
      <span class="min-w-0 flex-1">
        <span class="block truncate text-base font-semibold text-fg">{{ title }}</span>
        <span class="block truncate text-xs text-muted">
          {{ node.head ? `${headRole}: ${node.head.name}` : t("lifecycle.org.people", { n: node.count }, node.count) }}
        </span>
      </span>
      <span class="shrink-0 rounded-full bg-surface-2 px-2 py-0.5 text-xs font-semibold tabular-nums text-muted dark:bg-surface-3">{{ node.total }}</span>
    </button>
    <div v-if="open" :class="['flex flex-col gap-2 pb-3', depth === 0 ? 'border-t border-line pt-2' : '']" :style="{ paddingLeft: depth === 0 ? '8px' : '20px', paddingRight: '8px' }">
      <div v-if="node.head" class="flex min-w-0 items-center gap-1" :data-person-id="node.head.id" data-head>
        <RouterLink
          :to="org.profileUrl(node.head.id)"
          :class="['flex min-w-0 flex-1 items-center gap-2.5 rounded-[10px] px-2 py-1.5 active:bg-surface-2', org.highlight.value === node.head.id ? 'bg-accent-soft ring-2 ring-[var(--c-primary)]' : '']"
        >
          <UserAvatar :name="node.head.name" :src="node.head.photo_url" :size="32" />
          <span class="min-w-0 flex-1 leading-tight">
            <span class="block truncate text-base font-semibold text-fg">{{ node.head.name }}</span>
            <span class="block truncate text-xs text-muted">{{ node.head.position ? `${headRole} · ${node.head.position}` : headRole }}</span>
          </span>
        </RouterLink>
        <DropdownMenu v-if="node.headPerson" :items="menu(node.headPerson)" align="end" width="240px">
          <template #trigger>
            <button type="button" class="grid size-9 shrink-0 place-items-center rounded-[8px] text-muted active:bg-surface-2" :aria-label="t('lifecycle.org.actionsFor', { name: node.head.name })" data-person-menu>
              <Ellipsis :size="16" />
            </button>
          </template>
        </DropdownMenu>
      </div>
      <section v-for="group in node.groups" :key="group.key">
        <h4 class="flex items-center justify-between px-2 pb-0.5 pt-1 text-[11px] font-semibold uppercase tracking-[0.04em] text-subtle">
          <span class="truncate">{{ group.position?.name ?? t("lifecycle.org.noPosition") }}</span>
          <span class="tabular-nums">{{ group.people.length }}</span>
        </h4>
        <ul>
          <li v-for="person in group.people" :key="person.id" class="flex min-w-0 items-center gap-1" :data-person-id="person.id">
            <RouterLink
              :to="org.profileUrl(person.id)"
              :class="['flex min-w-0 flex-1 items-center gap-2.5 rounded-[10px] px-2 py-1.5 active:bg-surface-2', org.highlight.value === person.id ? 'bg-accent-soft ring-2 ring-[var(--c-primary)]' : '']"
            >
              <UserAvatar :name="person.name" :src="person.photo_url" :size="28" />
              <span class="min-w-0 flex-1">
                <span class="block truncate text-sm font-medium text-fg">{{ person.name }}</span>
                <span v-if="badges(person).length" class="mt-0.5 flex flex-wrap gap-1">
                  <StatusPill v-for="badge in badges(person).slice(0, 2)" :key="badge.key" size="sm" :tone="badge.tone" :label="label(badge.key, badge.day)" />
                </span>
              </span>
            </RouterLink>
            <DropdownMenu :items="menu(person)" align="end" width="240px">
              <template #trigger>
                <button type="button" class="grid size-9 shrink-0 place-items-center rounded-[8px] text-muted active:bg-surface-2" :aria-label="t('lifecycle.org.actionsFor', { name: person.name })" data-person-menu>
                  <Ellipsis :size="16" />
                </button>
              </template>
            </DropdownMenu>
          </li>
        </ul>
      </section>
      <ul v-if="node.vacancies.length" class="flex flex-col gap-1.5 px-1">
        <li v-for="vacancy in node.vacancies" :key="vacancy.id">
          <component
            :is="org.can.value.hiring ? RouterLink : 'div'"
            :to="org.can.value.hiring ? org.vacancyUrl(vacancy.id) : undefined"
            class="flex min-w-0 items-center gap-2.5 rounded-[10px] border border-dashed border-[color-mix(in_srgb,var(--c-primary)_45%,transparent)] bg-[color-mix(in_srgb,var(--c-primary)_5%,transparent)] px-2.5 py-2"
            data-vacancy
          >
            <UserRoundPlus :size="15" class="shrink-0 text-primary" aria-hidden="true" />
            <span class="min-w-0 flex-1 leading-tight">
              <span class="block truncate text-sm font-medium text-fg">{{ vacancy.title }}</span>
              <span class="block truncate text-xs text-muted">{{ t("lifecycle.org.openPlace") }}<template v-if="vacancy.applicants"> · {{ t("lifecycle.org.applicants", { n: vacancy.applicants }, vacancy.applicants) }}</template></span>
            </span>
          </component>
        </li>
      </ul>
      <ul v-if="node.children.length" class="flex flex-col border-l border-line" :style="{ marginLeft: '14px' }">
        <OrgOutlineNode v-for="child in node.children" :key="child.key" :node="child" :depth="depth + 1" />
      </ul>
      <p v-if="!node.groups.length && !node.vacancies.length && !node.children.length" class="px-2 py-1 text-xs text-subtle">{{ t("lifecycle.org.nobody") }}</p>
    </div>
  </li>
</template>
