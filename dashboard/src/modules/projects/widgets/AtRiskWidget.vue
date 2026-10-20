<script setup lang="ts">
/** Overview widget "Projects at risk": live projects at risk or off track, worst first. */
import { ArrowRight, FolderKanban } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink } from "vue-router";

import type { Range } from "@/api/types";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import ProgressBar from "@/components/ProgressBar.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import UiBadge from "@/components/UiBadge.vue";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { useFormat } from "@/lib/useFormat";

import { useProjects } from "../api";
import HealthDot from "../components/HealthDot.vue";
import ProjectBadge from "../components/ProjectBadge.vue";

const props = defineProps<{ companyId: number; range?: Range; compare?: Range | null }>();

const { t } = useI18n();
const fmt = useFormat();
const query = useProjects(() => ({ health: ["at_risk", "off_track"], status: ["planning", "active", "on_hold"] }));
const skeleton = useDelayedPending(computed(() => query.isPending.value));
const projects = computed(() =>
  [...(query.data.value?.results ?? [])].sort((a, b) => (a.health === "off_track" ? 0 : 1) - (b.health === "off_track" ? 0 : 1) || (a.due_on ?? "9").localeCompare(b.due_on ?? "9")),
);
const all = computed(() => `/c/${props.companyId}/projects?health=at_risk&health=off_track`);
</script>

<template>
  <section class="ui-card flex h-full min-w-0 flex-col" :aria-label="t('projects.widget.atRisk')">
    <header class="flex items-center gap-2 px-4 pb-2 pt-4">
      <FolderKanban :size="16" class="text-subtle" aria-hidden="true" />
      <h3 class="text-sm font-semibold text-fg">{{ t("projects.widget.atRisk") }}</h3>
      <UiBadge v-if="projects.length" :count="projects.length" tone="warning" />
      <span class="flex-1" />
      <RouterLink :to="all" class="inline-flex items-center gap-1 rounded-[6px] px-1.5 py-0.5 text-sm font-semibold text-muted hover:bg-highlight hover:text-fg">
        {{ t("common.viewAll") }}<ArrowRight :size="14" />
      </RouterLink>
    </header>
    <div class="min-h-0 flex-1 px-2 pb-2">
      <div v-if="skeleton" class="flex flex-col gap-1 p-2">
        <div v-for="n in 3" :key="n" class="flex items-center gap-3 py-1.5"><SkeletonBlock width="30px" height="30px" radius="8px" /><div class="flex flex-1 flex-col gap-1.5"><SkeletonBlock width="70%" /><SkeletonBlock width="40%" height="6px" /></div></div>
      </div>
      <ErrorState v-else-if="query.isError.value" compact :error="query.error.value" :retry="() => query.refetch()" class="m-2" />
      <EmptyState v-else-if="query.data.value && !projects.length" size="sm" tone="success" :title="t('projects.widget.allGood')" :description="t('projects.widget.allGoodBody')" />
      <ul v-else class="flex flex-col">
        <li v-for="project in projects.slice(0, 4)" :key="project.id">
          <RouterLink :to="`/c/${companyId}/projects/${project.id}`" class="flex items-center gap-3 rounded-[10px] px-2 py-2 transition-colors hover:bg-highlight">
            <ProjectBadge :color="project.color" :icon="project.icon" :size="30" />
            <div class="min-w-0 flex-1">
              <p class="flex items-center gap-1.5"><span class="truncate text-sm font-semibold text-fg">{{ project.name }}</span><HealthDot :health="project.health" /></p>
              <div class="mt-1 flex items-center gap-2">
                <ProgressBar :value="project.progress.percent" size="xs" class="flex-1" :tone="project.health === 'off_track' ? 'danger' : 'warning'" />
                <span class="text-[11px] tabular-nums text-muted">{{ project.progress.percent }}%</span>
              </div>
            </div>
            <span v-if="project.due_on" class="shrink-0 text-xs tabular-nums text-muted">{{ fmt.day(project.due_on, "short") }}</span>
          </RouterLink>
        </li>
      </ul>
    </div>
  </section>
</template>
