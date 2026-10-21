<script setup lang="ts">
/** Overview widget "Projects at risk": live projects at risk or off track, worst first. */
import { FolderKanban } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink } from "vue-router";

import type { Range } from "@/api/types";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import ProgressBar from "@/components/ProgressBar.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import WidgetCard from "@/components/WidgetCard.vue";
import { useWidgetSkeleton } from "@/components/widgetSkeleton";
import { useFormat } from "@/lib/useFormat";

import { useProjects } from "../api";
import HealthDot from "../components/HealthDot.vue";
import ProjectBadge from "../components/ProjectBadge.vue";

const props = defineProps<{ companyId: number; range?: Range; compare?: Range | null }>();

const { t, locale } = useI18n();
// Quotes as each language writes them: “…” in English, «…» in Uzbek and Russian.
const quoted = (text: string) => (locale.value === "en" ? `“${text}”` : `«${text}»`);
const fmt = useFormat();
const query = useProjects(() => ({ health: ["at_risk", "off_track"], status: ["planning", "active", "on_hold"] }));
const skeleton = useWidgetSkeleton(() => query.isPending.value);
const projects = computed(() =>
  [...(query.data.value?.results ?? [])].sort((a, b) => (a.health === "off_track" ? 0 : 1) - (b.health === "off_track" ? 0 : 1) || (a.due_on ?? "9").localeCompare(b.due_on ?? "9")),
);
const all = computed(() => `/c/${props.companyId}/projects?health=at_risk&health=off_track`);
</script>

<template>
  <WidgetCard :title="t('projects.widget.atRisk')" :icon="FolderKanban" :count="projects.length" count-tone="warning" :to="all">
    <div v-if="skeleton" class="flex flex-col gap-1 p-2">
      <div v-for="n in 3" :key="n" class="flex items-center gap-3 py-1.5"><SkeletonBlock width="30px" height="30px" radius="8px" /><div class="flex flex-1 flex-col gap-1.5"><SkeletonBlock width="70%" /><SkeletonBlock width="40%" height="6px" /></div></div>
    </div>
    <ErrorState v-else-if="query.isError.value" compact :error="query.error.value" :retry="() => query.refetch()" class="m-2" />
    <EmptyState v-else-if="query.data.value && !projects.length" class="my-auto" size="sm" tone="success" :title="t('projects.widget.allGood')" :description="t('projects.widget.allGoodBody')" />
    <ul v-else class="flex flex-col">
      <li v-for="project in projects.slice(0, 8)" :key="project.id">
        <RouterLink :to="`/c/${companyId}/projects/${project.id}`" class="flex items-start gap-3 rounded-[10px] px-2 py-2 transition-colors hover:bg-highlight">
          <ProjectBadge :color="project.color" :icon="project.icon" :size="30" />
          <div class="min-w-0 flex-1">
            <p class="flex min-w-0 items-center gap-1.5">
              <span class="truncate text-sm font-semibold text-fg" :title="project.name">{{ project.name }}</span><HealthDot :health="project.health" />
              <span class="flex-1" />
              <span v-if="project.due_on" class="shrink-0 text-xs tabular-nums text-muted">{{ fmt.day(project.due_on, "short") }}</span>
            </p>
            <div class="mt-1.5 flex items-center gap-2">
              <ProgressBar :value="project.progress.percent" size="xs" class="flex-1" :tone="project.health === 'off_track' ? 'danger' : 'warning'" />
              <span class="w-8 shrink-0 text-right text-[11px] tabular-nums text-muted">{{ project.progress.percent }}%</span>
            </div>
            <!-- Why it is at risk, in the project's own words where the lead wrote some. -->
            <p class="mt-1 truncate text-xs text-muted">
              {{ t("projects.card.cards", { done: project.progress.done, total: project.progress.total }) }}<template v-if="project.progress.overdue">
                · <span class="font-medium text-danger">{{ t("projects.card.overdue", { n: project.progress.overdue }) }}</span></template
              ><template v-if="project.burn !== undefined && project.burn !== null"> · {{ t("projects.card.burn", { n: project.burn }) }}</template>
            </p>
            <p v-if="project.reported?.text" class="mt-0.5 truncate text-xs italic text-subtle" :title="project.reported.text">{{ quoted(project.reported.text) }}</p>
          </div>
        </RouterLink>
      </li>
    </ul>
  </WidgetCard>
</template>
