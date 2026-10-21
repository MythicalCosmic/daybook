<script setup lang="ts">
/**
 * In the task drawer (extension point `tasks.drawer.actions`): "How to do this", the knowledge base
 * pages linked to this task or its routine. Shows nothing when there are none. The host passes the
 * task in `context` (`{ task: { id, template_id? } }`, or `{ taskId }`); both shapes are read.
 */
import { BookOpen } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink } from "vue-router";

import { useCompanyStore } from "@/stores/company";

import { useLinked } from "../api";

const props = withDefaults(defineProps<{ context?: Record<string, unknown> }>(), { context: () => ({}) });

const { t } = useI18n();
const company = useCompanyStore();

const task = computed(() => (props.context.task ?? {}) as Record<string, unknown>);
const taskId = computed(() => Number(task.value.id ?? props.context.taskId ?? props.context.id) || null);
const routineId = computed(() => Number(task.value.template_id ?? task.value.routine_id ?? props.context.routineId) || null);

const byTask = useLinked("task", taskId);
const byRoutine = useLinked(computed(() => (routineId.value ? "routine" : null)), routineId);
const pages = computed(() => {
  const seen = new Set<number>();
  return [...(byTask.data.value ?? []), ...(byRoutine.data.value ?? [])]
    .map((link) => link.page)
    .filter((page) => (seen.has(page.id) ? false : (seen.add(page.id), true)));
});
</script>

<template>
  <div v-if="pages.length" class="rounded-[10px] border border-line bg-surface-2/50 p-2 dark:bg-surface-2">
    <p class="flex items-center gap-1.5 px-1 pb-1 text-xs font-semibold text-muted"><BookOpen :size="13" />{{ t("knowledge.howTo") }}</p>
    <RouterLink
      v-for="page in pages"
      :key="page.id"
      :to="`/c/${company.currentId}/knowledge/p/${page.id}`"
      class="flex items-center gap-2 rounded-[7px] px-1.5 py-1 text-sm font-medium text-fg hover:bg-highlight"
    >
      <span aria-hidden="true">{{ page.emoji || "📄" }}</span>
      <span class="truncate">{{ page.title }}</span>
    </RouterLink>
  </div>
</template>
