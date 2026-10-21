<script setup lang="ts">
/** Overview widget "My projects": the live projects the person leads or works on. */
import { ArrowRight, Flag, FolderKanban } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink } from "vue-router";

import type { Range } from "@/api/types";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import ProgressRing from "@/components/ProgressRing.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { useFormat } from "@/lib/useFormat";

import { useProjects } from "../api";
import HealthDot from "../components/HealthDot.vue";

const props = defineProps<{ companyId: number; range?: Range; compare?: Range | null }>();

const { t } = useI18n();
const fmt = useFormat();
const query = useProjects(() => ({ mine: true, status: ["planning", "active", "on_hold"] }));
const skeleton = useDelayedPending(computed(() => query.isPending.value));
const projects = computed(() => query.data.value?.results ?? []);
</script>

<template>
  <section class="ui-card flex h-full min-w-0 flex-col" :aria-label="t('projects.widget.mine')">
    <header class="flex items-center gap-2 px-4 pb-2 pt-4">
      <FolderKanban :size="16" class="text-subtle" aria-hidden="true" />
      <h3 class="text-sm font-semibold text-fg">{{ t("projects.widget.mine") }}</h3>
      <span class="flex-1" />
      <RouterLink :to="`/c/${props.companyId}/projects?mine=true`" class="inline-flex items-center gap-1 rounded-[6px] px-1.5 py-0.5 text-sm font-semibold text-muted hover:bg-highlight hover:text-fg">
        {{ t("common.viewAll") }}<ArrowRight :size="14" />
      </RouterLink>
    </header>
    <div class="min-h-0 flex-1 px-2 pb-2">
      <div v-if="skeleton" class="flex flex-col gap-1 p-2">
        <div v-for="n in 3" :key="n" class="flex items-center gap-3 py-1.5"><SkeletonBlock circle height="34px" /><div class="flex flex-1 flex-col gap-1.5"><SkeletonBlock width="60%" /><SkeletonBlock width="40%" height="11px" /></div></div>
      </div>
      <ErrorState v-else-if="query.isError.value" compact :error="query.error.value" :retry="() => query.refetch()" class="m-2" />
      <EmptyState v-else-if="query.data.value && !projects.length" size="sm" tone="neutral" :title="t('projects.widget.noMine')" :description="t('projects.widget.noMineBody')" />
      <ul v-else class="flex flex-col">
        <li v-for="project in projects.slice(0, 4)" :key="project.id">
          <RouterLink :to="`/c/${companyId}/projects/${project.id}`" class="flex items-center gap-3 rounded-[10px] px-2 py-2 transition-colors hover:bg-highlight">
            <ProgressRing :value="project.progress.percent" :size="34" show-value :tone="project.health === 'off_track' ? 'danger' : project.health === 'at_risk' ? 'warning' : 'primary'" />
            <div class="min-w-0 flex-1">
              <p class="flex items-center gap-1.5"><span class="truncate text-sm font-semibold text-fg">{{ project.name }}</span><HealthDot :health="project.health" /></p>
              <p v-if="project.next_milestone" class="flex min-w-0 items-center gap-1 text-xs text-muted">
                <Flag :size="11" class="shrink-0" /><span class="truncate">{{ project.next_milestone.name }}</span>
                <span v-if="project.next_milestone.due_on" class="shrink-0">· {{ fmt.day(project.next_milestone.due_on, "short") }}</span>
              </p>
              <p v-else class="text-xs text-muted">{{ t("projects.card.cards", { done: project.progress.done, total: project.progress.total }) }}</p>
            </div>
            <span class="shrink-0 font-mono text-[11px] text-subtle">{{ project.key }}</span>
          </RouterLink>
        </li>
      </ul>
    </div>
  </section>
</template>
