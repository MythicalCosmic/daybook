<script setup lang="ts">
/**
 * People › Lifecycle › Org chart: the whole company as one tree. The owners on top, then the
 * departments with their heads (or, by branch, the branches with their managers), people under them
 * by job title, open vacancies as dashed places. Fold parts away, zoom to fit, find someone (the
 * chart scrolls to them); hover a person for their card, click for Person 360.
 *
 * Moving someone is a job change waiting for approval, never a change made here: drag them onto
 * another department or branch, or pick them up with Space and choose with the arrows, or use
 * "Move…"; the job change dialog opens filled in. Phones get the same tree as an indented outline.
 */
import { ChevronDown, ChevronUp, ChevronsDownUp, ChevronsUpDown, Maximize2, Minus, Network, Pencil, Plus, Search } from "@lucide/vue";
import { useResizeObserver } from "@vueuse/core";
import { computed, nextTick, onBeforeUnmount, provide, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";

import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import IconButton from "@/components/IconButton.vue";
import PageHeader from "@/components/PageHeader.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import TextInput from "@/components/TextInput.vue";
import UiButton from "@/components/UiButton.vue";
import { useBreakpoints } from "@/lib/useBreakpoints";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useCompanyStore } from "@/stores/company";

import ProposeChangeDialog from "../components/ProposeChangeDialog.vue";
import { useOrgChart } from "./api";
import { ACCENTS, ORG_CONTEXT, type OrgContext } from "./context";
import MoveDialog from "./MoveDialog.vue";
import OrgNode from "./OrgNode.vue";
import OrgOutline from "./OrgOutline.vue";
import { availableViews, buildTree, fitZoom, movePreset, nextTarget, pathTo, sameTarget, searchPeople, moveTargets, walk, type MovePreset, type MoveTarget, type OrgNode as Node } from "./tree";
import { ORG_VIEWS, type OrgCan, type OrgPerson, type OrgView } from "./types";

const { t } = useI18n();
const router = useRouter();
const company = useCompanyStore();
const { isPhone } = useBreakpoints();

const chart = useOrgChart();
const data = computed(() => chart.data.value ?? null);
const skeleton = useDelayedPending(computed(() => chart.isPending.value));

// ─── The view and its tree ───────────────────────────────────────────────────
const views = computed<OrgView[]>(() => (data.value ? availableViews(data.value) : ["department"]));
const asked = useRouteState<OrgView>("view", rs.enum(ORG_VIEWS, "department"));
const view = computed<OrgView>({
  get: () => (views.value.includes(asked.value) ? asked.value : views.value[0]!),
  set: (value) => (asked.value = value),
});
const viewOptions = computed(() => views.value.map((value) => ({ value, label: t(`lifecycle.org.view.${value}`) })));
const tree = computed(() => (data.value ? buildTree(data.value, view.value) : null));
const nodes = computed(() => (tree.value ? walk(tree.value) : []));

const summary = computed(() => {
  const value = data.value;
  if (!value) return [];
  const parts =
    view.value === "department"
      ? [t("lifecycle.org.summary.departments", { n: value.departments.length }, value.departments.length)]
      : [t("lifecycle.org.summary.branches", { n: value.branches.length }, value.branches.length)];
  parts.push(t("lifecycle.org.people", { n: value.people.length }, value.people.length));
  if (value.vacancies.length) parts.push(t("lifecycle.org.openPlaces", { n: value.vacancies.length }, value.vacancies.length));
  return parts;
});

// ─── Folding ─────────────────────────────────────────────────────────────────
const collapsed = reactive(new Set<string>());
const openGroups = reactive(new Set<string>());
const foldable = computed(() => nodes.value.filter((node) => node.kind !== "root" && (node.groups.length || node.vacancies.length || node.children.length)).map((node) => node.key));
const allCollapsed = computed(() => foldable.value.length > 0 && foldable.value.every((key) => collapsed.has(key)));
function foldAll(): void {
  if (allCollapsed.value) collapsed.clear();
  else for (const key of foldable.value) collapsed.add(key);
  void nextTick(() => fit());
}

// ─── Accents: each top part of the tree and everything under it share a colour ──
// The families start where the tree first branches: a company with one top department (the
// management) colours the departments under it, each with its own.
const accents = computed(() => {
  const map = new Map<string, string>();
  if (!tree.value) return map;
  const parts = (node: Node) => node.children.filter((child) => child.kind !== "unplaced");
  let level = tree.value;
  while (parts(level).length === 1 && parts(parts(level)[0]!).length > 1) {
    const only = parts(level)[0]!;
    map.set(only.key, "var(--c-primary)");
    level = only;
  }
  parts(level).forEach((top, index) => {
    for (const node of walk(top)) map.set(node.key, ACCENTS[index % ACCENTS.length]!);
  });
  return map;
});

// ─── Names for the hover card ───────────────────────────────────────────────
const departmentNames = computed(() => new Map((data.value?.departments ?? []).map((row) => [row.id, row.name])));
const branchNames = computed(() => new Map((data.value?.branches ?? []).map((row) => [row.id, row.name])));
const personNames = computed(() => {
  const map = new Map<number, string>();
  for (const row of data.value?.departments ?? []) if (row.head) map.set(row.head.id, row.head.name);
  for (const row of data.value?.owners ?? []) map.set(row.id, row.name);
  for (const row of data.value?.people ?? []) map.set(row.id, row.name);
  return map;
});
const positions = computed(() => new Map((data.value?.positions ?? []).map((row) => [row.id, row])));

// ─── Search ──────────────────────────────────────────────────────────────────
const query = ref("");
const matches = computed(() => (tree.value && data.value ? searchPeople(tree.value, data.value.positions, query.value) : []));
const matchIndex = ref(0);
const highlight = ref<number | null>(null);
watch(matches, (list) => {
  matchIndex.value = 0;
  void reveal(list[0]?.id ?? null);
});
function stepMatch(direction: 1 | -1): void {
  const list = matches.value;
  if (!list.length) return;
  matchIndex.value = (matchIndex.value + direction + list.length) % list.length;
  void reveal(list[matchIndex.value]!.id);
}
/** Open what hides someone, then scroll the chart to them and ring them. */
async function reveal(personId: number | null): Promise<void> {
  highlight.value = personId;
  if (personId === null || !tree.value) return;
  const path = pathTo(tree.value, personId);
  if (!path) return;
  // Open the way: on the canvas nothing on it folded, in the phone outline every part on it open.
  for (const key of path.nodes) {
    collapsed.delete(key);
    collapsed.add(`~${key}`);
  }
  if (path.group) openGroups.add(`${path.nodes[path.nodes.length - 1]}:${path.group}`);
  await nextTick();
  const element = document.querySelector<HTMLElement>(`[data-org-chart] [data-person-id="${personId}"]`);
  const still = typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
  const behavior: ScrollBehavior = still ? "auto" : "smooth";
  const box = viewport.value;
  if (element && box?.contains(element)) {
    // The canvas scrolls to them; the page itself stays where it is.
    const frame = box.getBoundingClientRect();
    const spot = element.getBoundingClientRect();
    box.scrollTo?.({
      left: box.scrollLeft + spot.left - frame.left - frame.width / 2 + spot.width / 2,
      top: box.scrollTop + spot.top - frame.top - frame.height / 2 + spot.height / 2,
      behavior,
    });
  } else element?.scrollIntoView?.({ block: "center", inline: "center", behavior });
}

// ─── Zoom and pan ────────────────────────────────────────────────────────────
const viewport = ref<HTMLElement | null>(null);
const stage = ref<HTMLElement | null>(null);
const zoom = ref(1);
const zoomLabel = computed(() => `${Math.round(zoom.value * 100)}%`);
const setZoom = (value: number) => (zoom.value = Math.min(1.5, Math.max(0.3, Math.round(value * 100) / 100)));
/** Zoom so the whole tree shows ("Fit"), or (`widthOnly`, when it opens) so its width does and it
 * scrolls down: names stay readable. */
function fit(widthOnly = false): void {
  const box = viewport.value;
  const content = stage.value;
  if (!box || !content) return;
  const rect = content.getBoundingClientRect();
  const natural = { width: rect.width / zoom.value, height: widthOnly ? 1 : rect.height / zoom.value };
  setZoom(fitZoom({ width: box.clientWidth - 48, height: widthOnly ? 1 : box.clientHeight - 48 }, natural, widthOnly ? 0.5 : 0.3));
  void nextTick(() => {
    if (!viewport.value) return;
    viewport.value.scrollLeft = (viewport.value.scrollWidth - viewport.value.clientWidth) / 2;
    viewport.value.scrollTop = 0;
  });
}
// A wide company opens fitted to the page (a small one at its natural size), once the tree has
// its size: fonts and avatars may still be loading when the data arrives.
let fitted = false;
useResizeObserver(stage, (entries) => {
  const rect = entries[0]?.contentRect;
  if (fitted || !rect || rect.width < 10 || isPhone.value) return;
  fitted = true;
  fit(true);
  if (zoom.value > 0.9) setZoom(1);
});
function onWheel(event: WheelEvent): void {
  if (!event.ctrlKey && !event.metaKey) return;
  event.preventDefault();
  setZoom(zoom.value * (event.deltaY > 0 ? 0.9 : 1.1));
}
let pan: { x: number; y: number; left: number; top: number; id: number } | null = null;
const panning = ref(false);
function onPointerDown(event: PointerEvent): void {
  const target = event.target as HTMLElement;
  if (event.button !== 0 || event.pointerType !== "mouse" || target.closest(".org-card, button, a, input, [role='button']")) return;
  pan = { x: event.clientX, y: event.clientY, left: viewport.value!.scrollLeft, top: viewport.value!.scrollTop, id: event.pointerId };
  viewport.value!.setPointerCapture(event.pointerId);
  panning.value = true;
}
function onPointerMove(event: PointerEvent): void {
  if (!pan || !viewport.value) return;
  viewport.value.scrollLeft = pan.left - (event.clientX - pan.x);
  viewport.value.scrollTop = pan.top - (event.clientY - pan.y);
}
function onPointerUp(): void {
  if (pan && viewport.value?.hasPointerCapture(pan.id)) viewport.value.releasePointerCapture(pan.id);
  pan = null;
  panning.value = false;
}

// ─── Moving people ───────────────────────────────────────────────────────────
const dragging = ref<OrgPerson | null>(null);
const over = ref<string | null>(null);
const picked = ref<{ person: OrgPerson; over: string | null } | null>(null);
const announcement = ref("");
function announce(text: string): void {
  announcement.value = "";
  void nextTick(() => (announcement.value = text));
}
const targets = computed(() => (tree.value ? moveTargets(tree.value) : []));
const targetName = (target: MoveTarget) => (target.part === "department" && target.id === null ? t("lifecycle.org.unplaced") : target.name);

/** The job change dialog, filled in for a drop; the picker for "Move…". */
const proposal = ref<{ person: OrgPerson; preset: MovePreset; key: number } | null>(null);
let proposalKey = 0;
const proposalOpen = computed({
  get: () => proposal.value !== null,
  set: (value: boolean) => {
    if (!value) proposal.value = null;
  },
});
const choosing = ref<OrgPerson | null>(null);

function reasonFor(target: MoveTarget): string {
  if (target.part === "branch") return t("lifecycle.org.reason.branch", { name: target.name });
  return target.id === null ? t("lifecycle.org.reason.noDepartment") : t("lifecycle.org.reason.department", { name: target.name });
}
function propose(person: OrgPerson, target: MoveTarget): void {
  if (!person.may_move || sameTarget(person, target)) return;
  proposal.value = { person, preset: movePreset(target, reasonFor(target)), key: ++proposalKey };
}

function personKey(person: OrgPerson, event: KeyboardEvent): void {
  const lifted = picked.value?.person.id === person.id ? picked.value : null;
  if (lifted) {
    if (["ArrowDown", "ArrowRight", "ArrowUp", "ArrowLeft"].includes(event.key)) {
      event.preventDefault();
      const direction = event.key === "ArrowDown" || event.key === "ArrowRight" ? 1 : -1;
      const next = nextTarget(targets.value, person, lifted.over, direction);
      if (!next) return;
      picked.value = { person, over: next.key };
      document.querySelector(`[data-org-chart] [data-node="${next.key}"] > .org-card`)?.scrollIntoView?.({ block: "nearest", inline: "nearest" });
      announce(t("lifecycle.org.kb.over", { name: targetName(next.target!) }));
    } else if (event.key === " " || event.key === "Enter") {
      event.preventDefault();
      const node = targets.value.find((each) => each.key === lifted.over);
      picked.value = null;
      if (node?.target) {
        announce(t("lifecycle.org.kb.dropped", { name: person.name, target: targetName(node.target) }));
        propose(person, node.target);
      } else announce(t("lifecycle.org.kb.cancelled"));
    } else if (event.key === "Escape") {
      event.preventDefault();
      picked.value = null;
      announce(t("lifecycle.org.kb.cancelled"));
    }
    return;
  }
  if (event.key === "Enter") {
    event.preventDefault();
    openPerson(person);
  } else if (event.key === " ") {
    event.preventDefault();
    if (person.may_move) {
      picked.value = { person, over: null };
      announce(t("lifecycle.org.kb.lifted", { name: person.name }));
    } else if (data.value?.can.move && person.why_not) announce(t(`lifecycle.org.whyNot.${person.why_not}`));
    else openPerson(person);
  } else if ((event.key === "m" || event.key === "M") && person.may_move) {
    event.preventDefault();
    choosing.value = person;
  }
}

function openPerson(person: OrgPerson): void {
  if (picked.value) return;
  void router.push(profileUrl(person.id));
}
const profileUrl = (id: number) => `/c/${company.currentId}/people/${id}`;
const vacancyUrl = (id: number) => `/c/${company.currentId}/hr/hiring/${id}`;

function onDocumentPointer(event: PointerEvent): void {
  // A click away puts down whoever was picked up.
  if (picked.value && !(event.target as HTMLElement).closest(`[data-person-id="${picked.value.person.id}"]`)) picked.value = null;
}
document.addEventListener("pointerdown", onDocumentPointer, true);
onBeforeUnmount(() => document.removeEventListener("pointerdown", onDocumentPointer, true));

const emptyCan: OrgCan = { move: false, decide: false, hiring: false, structure: false };
const context: OrgContext = {
  today: computed(() => data.value?.today ?? ""),
  can: computed(() => data.value?.can ?? emptyCan),
  view,
  positions,
  departmentName: (id) => (id !== null ? (departmentNames.value.get(id) ?? null) : null),
  branchName: (id) => (id !== null ? (branchNames.value.get(id) ?? null) : null),
  personName: (id) => (id !== null ? (personNames.value.get(id) ?? null) : null),
  isCollapsed: (key) => collapsed.has(key),
  toggle: (key) => (collapsed.has(key) ? collapsed.delete(key) : collapsed.add(key)),
  isGroupOpen: (key) => openGroups.has(key),
  openGroup: (key) => openGroups.add(key),
  accent: (key) => accents.value.get(key) ?? "var(--c-primary)",
  highlight,
  picked,
  dragging,
  over,
  profileUrl,
  vacancyUrl,
  openPerson,
  startMove: (person) => (choosing.value = person),
  dragStart: (person, event) => {
    if (!person.may_move) {
      event.preventDefault();
      return;
    }
    dragging.value = person;
    if (event.dataTransfer) {
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", String(person.id));
    }
  },
  dragEnd: () => {
    dragging.value = null;
    over.value = null;
  },
  canDrop: (node: Node) => {
    const person = dragging.value ?? picked.value?.person ?? null;
    return !!person && !!node.target && !sameTarget(person, node.target);
  },
  drop: (node: Node) => {
    const person = dragging.value;
    dragging.value = null;
    over.value = null;
    if (person && node.target) propose(person, node.target);
  },
  personKey,
};
provide(ORG_CONTEXT, context);

function chosen(target: MoveTarget): void {
  const person = choosing.value;
  choosing.value = null;
  if (person) propose(person, target);
}
</script>

<template>
  <div class="flex flex-col gap-4">
    <PageHeader class="!mb-0" :title="t('lifecycle.nav.org')" :description="t('lifecycle.org.description')">
      <template v-if="data?.can.structure" #actions>
        <UiButton variant="secondary" :icon="Pencil" :to="`/c/${company.currentId}/people/departments`" data-edit-departments>{{ t("lifecycle.org.editDepartments") }}</UiButton>
      </template>
    </PageHeader>

    <div v-if="skeleton" class="ui-card flex flex-col items-center gap-6 p-8" aria-hidden="true">
      <SkeletonBlock width="300px" height="120px" radius="14px" />
      <div class="flex flex-wrap justify-center gap-5">
        <SkeletonBlock v-for="n in 3" :key="n" width="260px" height="220px" radius="14px" />
      </div>
    </div>
    <ErrorState v-else-if="chart.isError.value" class="ui-card" :error="chart.error.value" :retry="() => chart.refetch()" />

    <template v-else-if="data && tree">
      <!-- The bar: the view, the summary, search, folding and zoom. -->
      <div class="flex flex-wrap items-center gap-x-3 gap-y-2.5" data-org-toolbar>
        <SegmentedControl v-if="viewOptions.length > 1" v-model="view" :options="viewOptions" size="sm" :aria-label="t('lifecycle.org.viewLabel')" />
        <p class="flex flex-wrap items-center gap-x-1.5 text-sm text-muted" data-org-summary>
          <template v-for="(part, index) in summary" :key="index">
            <span v-if="index" class="text-subtle" aria-hidden="true">·</span>
            <span class="tabular-nums">{{ part }}</span>
          </template>
        </p>
        <span class="hidden flex-1 md:block" />
        <div class="flex w-full items-center gap-1.5 md:w-auto">
          <TextInput
            v-model="query"
            type="search"
            size="sm"
            :icon="Search"
            clearable
            class="min-w-0 flex-1 md:w-60 md:flex-none"
            :placeholder="t('lifecycle.org.search')"
            :aria-label="t('lifecycle.org.search')"
            data-org-search
            @keydown.enter.prevent="stepMatch(1)"
          />
          <template v-if="query.trim()">
            <span class="shrink-0 px-1 text-xs tabular-nums text-muted" aria-live="polite" data-org-found>
              {{ matches.length ? t("lifecycle.org.found", { at: matchIndex + 1, n: matches.length }) : t("lifecycle.org.notFound") }}
            </span>
            <IconButton :icon="ChevronUp" size="sm" variant="ghost" :label="t('lifecycle.org.previous')" :disabled="matches.length < 2" @click="stepMatch(-1)" />
            <IconButton :icon="ChevronDown" size="sm" variant="ghost" :label="t('lifecycle.org.next')" :disabled="matches.length < 2" @click="stepMatch(1)" />
          </template>
        </div>
        <div v-if="!isPhone" class="flex items-center gap-1 rounded-[10px] border border-line bg-surface p-0.5" data-org-zoom>
          <IconButton :icon="allCollapsed ? ChevronsUpDown : ChevronsDownUp" size="sm" variant="ghost" :label="allCollapsed ? t('lifecycle.org.expandAll') : t('lifecycle.org.collapseAll')" @click="foldAll" />
          <span class="mx-0.5 h-5 w-px bg-line" aria-hidden="true" />
          <IconButton :icon="Minus" size="sm" variant="ghost" :label="t('lifecycle.org.zoomOut')" @click="setZoom(zoom - 0.1)" />
          <button type="button" class="min-w-[3.25rem] rounded-[6px] px-1 text-xs font-semibold tabular-nums text-muted hover:text-fg" :aria-label="t('lifecycle.org.zoomReset')" @click="setZoom(1)">{{ zoomLabel }}</button>
          <IconButton :icon="Plus" size="sm" variant="ghost" :label="t('lifecycle.org.zoomIn')" @click="setZoom(zoom + 0.1)" />
          <IconButton :icon="Maximize2" size="sm" variant="ghost" :label="t('lifecycle.org.fit')" data-org-fit @click="fit()" />
        </div>
      </div>

      <!-- Phones: the outline. -->
      <OrgOutline v-if="isPhone" :root="tree" :owners="data.owners" data-org-chart />

      <!-- Wider screens: the canvas. -->
      <div
        v-else
        ref="viewport"
        :class="['org-viewport ui-card relative overflow-auto', panning ? 'cursor-grabbing' : 'cursor-grab']"
        data-org-chart
        @wheel="onWheel"
        @pointerdown="onPointerDown"
        @pointermove="onPointerMove"
        @pointerup="onPointerUp"
        @pointercancel="onPointerUp"
      >
        <!-- Centred while it fits; wider than the canvas, it starts at the left and scrolls (a
             centred flex child would hide its left part). -->
        <div class="flex min-h-full w-max min-w-full p-8">
          <div ref="stage" class="org-stage mx-auto" :style="{ zoom }">
            <ul class="org-tree">
              <OrgNode :node="tree" :owners="data.owners" />
            </ul>
          </div>
        </div>
      </div>
      <p v-if="data.can.move && !isPhone" class="-mt-1 text-xs text-muted" data-org-hint>{{ t("lifecycle.org.hint") }}</p>
      <EmptyState v-if="!data.people.length" :icon="Network" :title="t('lifecycle.org.emptyTitle')" :description="t('lifecycle.org.emptyBody')" />
    </template>

    <p class="sr-only" aria-live="assertive" data-org-announce>{{ announcement }}</p>

    <MoveDialog v-if="choosing && tree" :person="choosing" :root="tree" :open="!!choosing" @update:open="(value: boolean) => !value && (choosing = null)" @chosen="chosen" />
    <ProposeChangeDialog
      v-if="proposal"
      :key="proposal.key"
      v-model:open="proposalOpen"
      :member="{ id: proposal.person.id, name: proposal.person.name }"
      :preset="proposal.preset"
    />
  </div>
</template>

<style scoped>
.org-viewport {
  height: max(28rem, calc(100dvh - 15.5rem));
  background-color: var(--c-canvas);
  background-image: radial-gradient(circle at 1px 1px, color-mix(in srgb, var(--c-text) 9%, transparent) 1px, transparent 0);
  background-size: 22px 22px;
  touch-action: pan-x pan-y;
}
.org-tree {
  display: flex;
  justify-content: center;
}
</style>
