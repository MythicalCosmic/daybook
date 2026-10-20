<script setup lang="ts">
/**
 * Roadmap (plan §13.3 "Other pages"): every project on one timeline, its bar filled to the share of
 * cards done and coloured by health, milestones as diamonds. Drag a bar to move a project's dates,
 * its edges to change the start or the due date (for people who manage it); click opens the board.
 */
import { FolderKanban, FolderPlus } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";

import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import GanttTimeline from "@/components/GanttTimeline.vue";
import { PX_PER_DAY, type GanttRow, type GanttZoom } from "@/components/gantt";
import PageHeader from "@/components/PageHeader.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import UiButton from "@/components/UiButton.vue";
import { toast } from "@/components/useToast";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { useFormat } from "@/lib/useFormat";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useCompanyStore } from "@/stores/company";

import { scheduleProject, useCompanyId, useRefreshProjects, useRoadmap } from "../api";
import HealthDot from "../components/HealthDot.vue";
import ProjectBadge from "../components/ProjectBadge.vue";
import { colorVar, declutterMilestones, healthVar } from "../lib";
import type { RoadmapRow } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const router = useRouter();
const company = useCompanyStore();
const companyId = useCompanyId();
const refresh = useRefreshProjects();

const all = useRouteState("all", rs.boolean(false));
const zoom = useRouteState<GanttZoom>("zoom", rs.enum(["day", "week", "month"] as const, "week"));
const query = useRoadmap(all);
const skeleton = useDelayedPending(computed(() => query.isPending.value));
const projects = computed(() => query.data.value?.rows ?? []);

const rows = computed<GanttRow[]>(() =>
  projects.value.map((p: RoadmapRow) => ({
    id: p.id,
    label: p.name,
    sublabel: `${p.key}${p.lead ? ` · ${p.lead.name}` : ""}`,
    color: colorVar(p.color),
    bars: [
      {
        id: p.id,
        start: p.start,
        end: p.end,
        label: `${p.key} · ${p.progress.percent}%`,
        progress: p.progress.percent,
        color: p.status === "completed" ? "var(--c-success)" : p.health && p.health !== "on_track" ? healthVar(p.health) : colorVar(p.color),
        editable: p.editable,
      },
    ],
    milestones: declutterMilestones(
      p.milestones.map((m) => ({ id: m.id, date: m.date, label: m.name, done: m.done, color: m.done ? "var(--c-success)" : "var(--c-text)", editable: false })),
      PX_PER_DAY[zoom.value],
    ),
  })),
);

async function reschedule(change: { rowId: string | number; start: string; end: string }): Promise<void> {
  try {
    const saved = await scheduleProject(companyId.value, Number(change.rowId), change.start, change.end);
    toast.success(t("projects.roadmap.moved", { key: saved.key, start: fmt.day(change.start, "short"), end: fmt.day(change.end, "short") }));
  } catch {
    // The HTTP layer showed why.
  } finally {
    await query.refetch();
    void refresh();
  }
}

function open(id: string | number): void {
  void router.push(`/c/${company.currentId}/projects/${id}`);
}

const counts = computed(() => ({
  risk: projects.value.filter((p) => p.health === "at_risk").length,
  off: projects.value.filter((p) => p.health === "off_track").length,
}));
</script>

<template>
  <div>
    <PageHeader :title="t('projects.roadmap.title')" :description="t('projects.roadmap.description')" :back="`/c/${company.currentId}/projects`" :back-label="t('projects.title')">
      <template #actions>
        <ToggleSwitch v-model="all" :label="t('projects.roadmap.showFinished')" size="sm" />
      </template>
      <template #meta>
        <span class="inline-flex items-center gap-1.5 text-xs text-muted"><span class="size-2 rounded-full" :style="{ background: healthVar('on_track') }" />{{ t("projects.health.on_track") }}</span>
        <span class="inline-flex items-center gap-1.5 text-xs text-muted"><span class="size-2 rounded-full" :style="{ background: healthVar('at_risk') }" />{{ t("projects.health.at_risk") }} · {{ counts.risk }}</span>
        <span class="inline-flex items-center gap-1.5 text-xs text-muted"><span class="size-2 rounded-full" :style="{ background: healthVar('off_track') }" />{{ t("projects.health.off_track") }} · {{ counts.off }}</span>
        <span class="inline-flex items-center gap-1.5 text-xs text-muted"><span class="size-2.5 rotate-45 rounded-[2px] border-2 border-fg" />{{ t("projects.roadmap.milestone") }}</span>
      </template>
    </PageHeader>

    <div v-if="skeleton" class="ui-card flex flex-col gap-3 p-4">
      <div v-for="n in 5" :key="n" class="flex items-center gap-4"><SkeletonBlock width="200px" height="28px" /><SkeletonBlock :width="`${30 + n * 9}%`" height="28px" radius="7px" /></div>
    </div>
    <ErrorState v-else-if="query.isError.value" :error="query.error.value" :retry="() => query.refetch()" />
    <EmptyState v-else-if="query.data.value && !rows.length" :icon="FolderKanban" size="lg" :title="t('projects.roadmap.emptyTitle')" :description="t('projects.roadmap.emptyBody')">
      <UiButton variant="primary" :icon="FolderPlus" :to="`/c/${company.currentId}/projects?new=1`">{{ t("projects.new") }}</UiButton>
    </EmptyState>
    <GanttTimeline
      v-else-if="query.data.value"
      v-model:zoom="zoom"
      :rows="rows"
      :label="t('projects.roadmap.projects')"
      :label-width="260"
      max-height="calc(100dvh - 250px)"
      :row-height="52"
      @change="reschedule"
      @bar-click="({ row }) => open(row.id)"
      @row-click="(row) => open(row.id)"
    >
      <template #label="{ row }">
        <ProjectBadge :color="projects.find((p) => p.id === row.id)?.color" :icon="projects.find((p) => p.id === row.id)?.icon" :size="28" />
        <span class="min-w-0 flex-1 leading-tight">
          <span class="block truncate text-sm font-semibold text-fg">{{ row.label }}</span>
          <span class="block truncate text-xs text-muted">{{ row.sublabel }}</span>
        </span>
        <HealthDot :health="projects.find((p) => p.id === row.id)?.health ?? null" />
      </template>
    </GanttTimeline>
  </div>
</template>
