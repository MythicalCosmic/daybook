<script setup lang="ts">
/**
 * The Timeline tab (plan §13.3, shared GanttTimeline): each card from its planned start to its
 * deadline, milestones as diamonds on top. Drag a bar to reschedule, its edges to change the start
 * or the deadline, a diamond to move a milestone; click a bar to open the card.
 */
import { GanttChart } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";

import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import GanttTimeline from "@/components/GanttTimeline.vue";
import { PX_PER_DAY, type GanttRow, type GanttZoom } from "@/components/gantt";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import { toast } from "@/components/useToast";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { rs, useRouteState } from "@/lib/useRouteState";

import { scheduleCard, updateMilestone, useCompanyId, useRefreshProjects, useTimeline } from "../api";
import { colorVar, declutterMilestones } from "../lib";
import type { ProjectDetail } from "../types";

const props = defineProps<{ project: ProjectDetail }>();

const { t } = useI18n();
const router = useRouter();
const companyId = useCompanyId();
const refresh = useRefreshProjects();
const query = useTimeline(() => props.project.id);
const skeleton = useDelayedPending(computed(() => query.isPending.value));
const zoom = useRouteState<GanttZoom>("zoom", rs.enum(["day", "week", "month"] as const, "day"));
const group = useRouteState("group", rs.enum(["none", "milestone", "person"] as const, "milestone"));
const showDone = useRouteState("done", rs.boolean(false));

const doneListId = computed(() => props.project.lists.find((l) => l.is_done)?.id ?? null);

const rows = computed<GanttRow[]>(() => {
  const data = query.data.value;
  if (!data) return [];
  const out: GanttRow[] = [];
  if (data.milestones.length) {
    out.push({
      id: "milestones",
      label: t("projects.timeline.milestones"),
      sublabel: props.project.key,
      color: colorVar(props.project.color),
      bars: [{ id: "span", start: data.project.start, end: data.project.end, label: "", color: colorVar(props.project.color), editable: false }],
      milestones: declutterMilestones(
        data.milestones.map((m) => ({ id: m.id, date: m.date, label: m.name, done: m.done, color: m.done ? "var(--c-success)" : "var(--c-text)", editable: props.project.capabilities.manage })),
        PX_PER_DAY[zoom.value],
      ),
    });
  }
  const cards = data.rows.filter((row) => showDone.value || row.status !== "done");
  const keyOf = (row: (typeof cards)[number]) =>
    group.value === "milestone" ? String(row.milestone_id ?? "~") : group.value === "person" ? (row.assignee?.name ?? "~") : "";
  const sorted = [...cards].sort((a, b) => keyOf(a).localeCompare(keyOf(b)) || a.start.localeCompare(b.start) || a.id - b.id);
  for (const row of sorted) {
    const done = row.status === "done" || row.list_id === doneListId.value;
    out.push({
      id: row.id,
      label: row.title,
      sublabel: [row.key, group.value === "milestone" ? props.project.milestones.find((m) => m.id === row.milestone_id)?.name : row.assignee?.name].filter(Boolean).join(" · "),
      avatar: row.assignee ? { name: row.assignee.name, src: row.assignee.photo_url } : null,
      bars: [
        {
          id: row.id,
          start: row.start,
          end: row.end,
          label: row.key,
          progress: row.progress,
          color: done ? "var(--c-success)" : row.overdue ? "var(--c-danger)" : colorVar(props.project.color),
          editable: row.editable,
        },
      ],
    });
  }
  return out;
});

async function reschedule(change: { barId: string | number; start: string; end: string }): Promise<void> {
  if (typeof change.barId !== "number") return;
  try {
    const card = await scheduleCard(companyId.value, props.project.id, change.barId, change.start, change.end);
    toast.success(t("projects.timeline.moved", { key: card.key }));
  } catch {
    // The HTTP layer showed why.
  } finally {
    await query.refetch();
    void refresh();
  }
}

async function moveMilestone(change: { milestoneId: string | number; date: string }): Promise<void> {
  try {
    await updateMilestone(companyId.value, props.project.id, Number(change.milestoneId), { due_on: change.date });
    toast.success(t("projects.timeline.milestoneMoved"));
  } finally {
    await query.refetch();
    void refresh();
  }
}

function openBar(target: { row: GanttRow }): void {
  if (typeof target.row.id !== "number") return;
  void router.replace({ query: { ...router.currentRoute.value.query, card: String(target.row.id) } });
}

const groupOptions = computed(() => [
  { value: "milestone" as const, label: t("projects.timeline.byMilestone") },
  { value: "person" as const, label: t("projects.timeline.byPerson") },
  { value: "none" as const, label: t("projects.timeline.byDate") },
]);
</script>

<template>
  <div class="flex flex-col gap-3">
    <div class="flex flex-wrap items-center gap-2">
      <SegmentedControl v-model="group" :options="groupOptions" size="sm" :aria-label="t('projects.timeline.group')" />
      <button type="button" class="h-7 rounded-full border px-2.5 text-xs font-semibold transition-colors" :class="showDone ? 'border-primary bg-accent-soft text-accent-fg' : 'border-line text-muted hover:bg-highlight'" @click="showDone = !showDone">
        {{ t("projects.timeline.showDone") }}
      </button>
    </div>
    <div v-if="skeleton" class="ui-card flex flex-col gap-3 p-4">
      <SkeletonBlock v-for="n in 7" :key="n" height="28px" :width="`${40 + ((n * 17) % 50)}%`" />
    </div>
    <ErrorState v-else-if="query.isError.value" :error="query.error.value" :retry="() => query.refetch()" />
    <EmptyState v-else-if="query.data.value && !rows.length" :icon="GanttChart" :title="t('projects.timeline.emptyTitle')" :description="t('projects.timeline.emptyBody')" />
    <GanttTimeline
      v-else-if="query.data.value"
      v-model:zoom="zoom"
      :rows="rows"
      :label="t('projects.timeline.cards')"
      :editable="project.capabilities.edit_cards"
      @change="reschedule"
      @milestone-change="moveMilestone"
      @bar-click="openBar"
      @row-click="(row) => openBar({ row })"
    />
  </div>
</template>
