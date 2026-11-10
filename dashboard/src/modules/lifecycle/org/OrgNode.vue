<script setup lang="ts">
/**
 * One part of the org chart and, under it, the parts below (the tree draws its own connectors):
 * the card names the department or branch, its head (or that it has none), how many people it has,
 * then its people grouped by job title and its open vacancies as dashed places. The whole card is
 * where a dragged person lands; the root card is the company with its owners.
 */
import { Building2, ChevronDown, ExternalLink, MapPin, Network, UserRound, UserRoundPlus, Users } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink } from "vue-router";

import UiTooltip from "@/components/UiTooltip.vue";
import UserAvatar from "@/components/UserAvatar.vue";

import { useOrgContext } from "./context";
import OrgPerson from "./OrgPerson.vue";
import { visiblePeople, type OrgNode } from "./tree";
import type { OrgRef } from "./types";

defineOptions({ name: "OrgNode" });
const props = withDefaults(defineProps<{ node: OrgNode; owners?: OrgRef[] }>(), { owners: () => [] });

const { t } = useI18n();
const org = useOrgContext();

const isRoot = computed(() => props.node.kind === "root");
const collapsed = computed(() => org.isCollapsed(props.node.key));
const hasBody = computed(() => props.node.groups.length > 0 || props.node.vacancies.length > 0);
const foldable = computed(() => !isRoot.value && (hasBody.value || props.node.children.length > 0));
const accent = computed(() => (isRoot.value ? "var(--c-primary)" : org.accent(props.node.key)));
const icon = computed(() => (props.node.kind === "branch" ? MapPin : props.node.kind === "root" ? Building2 : props.node.kind === "unplaced" ? Users : Network));
const title = computed(() => {
  if (props.node.kind !== "unplaced") return props.node.name;
  return org.view.value === "department" ? t("lifecycle.org.unplaced") : t("lifecycle.org.noBranch");
});
const headRole = computed(() => (props.node.kind === "branch" ? t("lifecycle.org.manager") : t("lifecycle.org.head")));
const headPosition = computed(() => props.node.head?.position ?? null);

const droppable = computed(() => org.canDrop(props.node));
const over = computed(() => org.over.value === props.node.key || org.picked.value?.over === props.node.key);
const dragging = computed(() => org.dragging.value !== null || org.picked.value !== null);

function onDragOver(event: DragEvent): void {
  if (!droppable.value) return;
  event.preventDefault();
  if (event.dataTransfer) event.dataTransfer.dropEffect = "move";
  org.over.value = props.node.key;
}
function onDragLeave(event: DragEvent): void {
  const next = event.relatedTarget as Node | null;
  if (next && (event.currentTarget as HTMLElement).contains(next)) return;
  if (org.over.value === props.node.key) org.over.value = null;
}
function onDrop(event: DragEvent): void {
  if (!droppable.value) return;
  event.preventDefault();
  org.drop(props.node);
}

const countLabel = computed(() => {
  const node = props.node;
  if (isRoot.value) return t("lifecycle.org.people", { n: node.total }, node.total);
  return t("lifecycle.org.people", { n: node.count }, node.count);
});
const totalLabel = computed(() => {
  const node = props.node;
  return node.children.length && node.total !== node.count ? t("lifecycle.org.inAll", { n: node.total }, node.total) : null;
});
</script>

<template>
  <li class="org-li" :data-node="node.key">
    <article
      :class="[
        'org-card relative flex w-[17rem] flex-col rounded-card border bg-surface text-left shadow-[var(--sh-xs)] transition-[border-color,box-shadow,transform] duration-150',
        node.kind === 'unplaced' ? 'border-dashed border-line-strong bg-surface/70' : 'border-line',
        isRoot ? 'w-[19rem]' : '',
        dragging && droppable ? 'org-can-drop' : '',
        over ? 'org-over' : '',
      ]"
      :style="{ '--accent': accent }"
      :data-drop-target="droppable ? node.key : undefined"
      :aria-label="title"
      @dragover="onDragOver"
      @dragenter="onDragOver"
      @dragleave="onDragLeave"
      @drop="onDrop"
    >
      <span v-if="node.kind !== 'unplaced'" class="pointer-events-none absolute inset-x-0 top-0 h-[3px] rounded-t-card" :style="{ background: 'var(--accent)' }" aria-hidden="true" />
      <header class="flex min-w-0 items-start gap-2.5 px-3.5 pb-2.5 pt-3.5">
        <span class="mt-0.5 grid size-7 shrink-0 place-items-center rounded-[8px]" :style="{ background: 'color-mix(in srgb, var(--accent) 14%, transparent)', color: 'var(--accent)' }">
          <component :is="icon" :size="15" aria-hidden="true" />
        </span>
        <div class="min-w-0 flex-1">
          <h3 :class="['break-words leading-snug text-fg', isRoot ? 'text-md font-semibold' : 'text-base font-semibold']">{{ title }}</h3>
          <p class="mt-0.5 flex flex-wrap items-center gap-x-1.5 text-xs text-muted">
            <span class="tabular-nums" data-count>{{ countLabel }}</span>
            <template v-if="totalLabel">
              <span class="text-subtle" aria-hidden="true">·</span>
              <span class="font-medium tabular-nums text-fg">{{ totalLabel }}</span>
            </template>
            <template v-if="node.vacancies.length">
              <span class="text-subtle" aria-hidden="true">·</span>
              <span class="font-medium text-primary">{{ t("lifecycle.org.openPlaces", { n: node.vacancies.length }, node.vacancies.length) }}</span>
            </template>
          </p>
        </div>
        <button
          v-if="foldable"
          type="button"
          class="-mr-1.5 -mt-1 grid size-7 shrink-0 place-items-center rounded-[8px] text-muted transition-colors hover:bg-surface-2 hover:text-fg"
          :aria-expanded="!collapsed"
          :aria-label="collapsed ? t('lifecycle.org.expand', { name: title }) : t('lifecycle.org.collapse', { name: title })"
          data-fold
          @click="org.toggle(node.key)"
        >
          <ChevronDown :size="16" :class="['transition-transform duration-200', collapsed ? '-rotate-90' : '']" aria-hidden="true" />
        </button>
      </header>

      <!-- The root: the owners. Elsewhere: the head or manager. -->
      <div v-if="isRoot" class="flex flex-col gap-1 border-t border-line px-2 py-2">
        <div v-for="owner in owners" :key="owner.id" class="flex min-w-0 items-center gap-2.5 rounded-[10px] px-2 py-1.5">
          <RouterLink :to="org.profileUrl(owner.id)" class="flex min-w-0 flex-1 items-center gap-2.5 rounded-[8px] outline-none focus-visible:ring-2 focus-visible:ring-[var(--c-ring)]">
            <UserAvatar :name="owner.name" :src="owner.photo_url" :size="34" />
            <span class="min-w-0 leading-tight">
              <span class="block truncate text-base font-semibold text-fg">{{ owner.name }}</span>
              <span class="block truncate text-xs text-muted">{{ owner.position ?? t("lifecycle.org.owner") }} · {{ t("lifecycle.org.owner") }}</span>
            </span>
          </RouterLink>
        </div>
      </div>
      <div v-else-if="node.kind !== 'unplaced'" class="border-t border-line px-1.5 py-1.5" data-head>
        <OrgPerson v-if="node.headPerson" :person="node.headPerson" :role="headPosition ? `${headRole} · ${headPosition}` : headRole" size="head" />
        <RouterLink v-else-if="node.head" :to="org.profileUrl(node.head.id)" class="flex min-w-0 items-center gap-2.5 rounded-[10px] px-2 py-1.5 hover:bg-surface-2/80">
          <UserAvatar :name="node.head.name" :src="node.head.photo_url" :size="34" />
          <span class="min-w-0 leading-tight">
            <span class="block truncate text-base font-semibold text-fg">{{ node.head.name }}</span>
            <span class="block truncate text-xs text-muted">{{ headRole }}</span>
          </span>
        </RouterLink>
        <div v-else class="flex min-w-0 items-center gap-2.5 px-2 py-1.5" data-no-head>
          <span class="grid size-[34px] shrink-0 place-items-center rounded-full border border-dashed border-line-strong text-subtle"><UserRound :size="15" aria-hidden="true" /></span>
          <span class="truncate text-sm text-subtle">{{ node.kind === "branch" ? t("lifecycle.org.noManager") : t("lifecycle.org.noHead") }}</span>
        </div>
      </div>

      <!-- People by job title, then the open places. -->
      <div v-if="hasBody && !collapsed" class="flex flex-col gap-2.5 border-t border-line px-1.5 pb-2 pt-2">
        <section v-for="group in node.groups" :key="group.key" class="flex flex-col" :data-group="group.key">
          <h4 class="flex items-center justify-between gap-2 px-2 pb-0.5 text-[11px] font-semibold uppercase tracking-[0.04em] text-subtle">
            <span class="truncate">{{ group.position?.name ?? t("lifecycle.org.noPosition") }}</span>
            <span class="tabular-nums">{{ group.people.length }}</span>
          </h4>
          <template v-for="part in [visiblePeople(group, org.isGroupOpen(`${node.key}:${group.key}`), org.highlight.value)]" :key="part.hidden">
            <OrgPerson v-for="person in part.shown" :key="person.id" :person="person" />
            <button
              v-if="part.hidden"
              type="button"
              class="mx-2 mt-0.5 self-start rounded-[6px] px-1 text-xs font-semibold text-primary hover:underline"
              data-more
              @click="org.openGroup(`${node.key}:${group.key}`)"
            >
              {{ t("lifecycle.org.more", { n: part.hidden }, part.hidden) }}
            </button>
          </template>
        </section>
        <ul v-if="node.vacancies.length" class="flex flex-col gap-1.5 px-0.5" :aria-label="t('lifecycle.org.placesLabel')">
          <li v-for="vacancy in node.vacancies" :key="vacancy.id">
            <component
              :is="org.can.value.hiring ? RouterLink : 'div'"
              :to="org.can.value.hiring ? org.vacancyUrl(vacancy.id) : undefined"
              :class="[
                'org-place group/place flex min-w-0 items-center gap-2.5 rounded-[10px] border border-dashed px-2 py-1.5',
                'border-[color-mix(in_srgb,var(--c-primary)_45%,transparent)] bg-[color-mix(in_srgb,var(--c-primary)_5%,transparent)]',
                org.can.value.hiring ? 'transition-colors hover:bg-accent-soft' : '',
              ]"
              data-vacancy
            >
              <span class="grid size-[26px] shrink-0 place-items-center rounded-full border border-dashed border-[color-mix(in_srgb,var(--c-primary)_55%,transparent)] text-primary">
                <UserRoundPlus :size="13" aria-hidden="true" />
              </span>
              <span class="min-w-0 flex-1 leading-tight">
                <span class="block truncate text-sm font-medium text-fg">{{ vacancy.title }}</span>
                <span class="block truncate text-xs text-muted">
                  {{ t("lifecycle.org.openPlace") }}<template v-if="vacancy.applicants"> · {{ t("lifecycle.org.applicants", { n: vacancy.applicants }, vacancy.applicants) }}</template>
                </span>
              </span>
              <UiTooltip v-if="vacancy.new" :content="t('lifecycle.org.newApplicants', { n: vacancy.new }, vacancy.new)">
                <span class="rounded-full bg-primary px-1.5 text-[11px] font-semibold tabular-nums text-on-primary">{{ vacancy.new }}</span>
              </UiTooltip>
              <ExternalLink v-if="org.can.value.hiring" :size="13" class="shrink-0 text-subtle opacity-0 transition-opacity group-hover/place:opacity-100" aria-hidden="true" />
            </component>
          </li>
        </ul>
      </div>
      <p v-else-if="collapsed && hasBody" class="border-t border-line px-3.5 py-2 text-xs text-muted">{{ t("lifecycle.org.folded", { n: node.count }, node.count) }}</p>
      <p v-else-if="!hasBody && !isRoot && !node.headPerson && !node.head && !node.children.length" class="border-t border-line px-3.5 py-2.5 text-xs text-subtle">{{ t("lifecycle.org.nobody") }}</p>

      <span v-if="over" class="pointer-events-none absolute inset-x-3 -bottom-3 z-[2] flex justify-center" aria-hidden="true">
        <span class="rounded-full bg-primary px-2.5 py-0.5 text-[11px] font-semibold text-on-primary shadow-[var(--sh-pop)]">{{ t("lifecycle.org.dropHere") }}</span>
      </span>
    </article>
    <ul v-if="node.children.length && !collapsed" class="org-ul">
      <OrgNode v-for="child in node.children" :key="child.key" :node="child" />
    </ul>
  </li>
</template>

<style scoped>
/*
 * The connectors (one recursive component, so these reach every level): each child draws its half
 * of the bar above it and its drop into its card; the list draws the stem under the parent card.
 */
.org-li {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
}
.org-ul {
  position: relative;
  display: flex;
  justify-content: center;
  padding-top: 22px;
}
.org-ul::before {
  content: "";
  position: absolute;
  top: 0;
  left: 50%;
  height: 22px;
  border-left: 1.5px solid var(--c-border-strong);
}
.org-ul > .org-li {
  padding: 22px 10px 0;
}
.org-ul > .org-li::before,
.org-ul > .org-li::after {
  content: "";
  position: absolute;
  top: 0;
  width: 50%;
  height: 22px;
  border-top: 1.5px solid var(--c-border-strong);
}
.org-ul > .org-li::before {
  right: 50%;
}
.org-ul > .org-li::after {
  left: 50%;
  border-left: 1.5px solid var(--c-border-strong);
}
.org-ul > .org-li:first-child::before,
.org-ul > .org-li:last-child::after {
  border-top: 0;
}
.org-ul > .org-li:last-child::before {
  border-right: 1.5px solid var(--c-border-strong);
  border-top-right-radius: 10px;
}
.org-ul > .org-li:first-child::after {
  border-top-left-radius: 10px;
}
.org-ul > .org-li:only-child::before {
  display: none;
}
.org-ul > .org-li:only-child::after {
  border-top: 0;
  border-radius: 0;
}
.org-ul > .org-li:last-child:not(:only-child)::after {
  display: none;
}

.org-can-drop {
  border-style: dashed;
  border-color: color-mix(in srgb, var(--c-primary) 45%, var(--c-border));
}
.org-over {
  border-color: var(--c-primary);
  box-shadow:
    0 0 0 3px color-mix(in srgb, var(--c-primary) 22%, transparent),
    var(--sh-pop);
  transform: translateY(-1px);
}
</style>
