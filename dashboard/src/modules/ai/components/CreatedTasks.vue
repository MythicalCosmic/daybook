<script setup lang="ts">
/** The tasks a draft became, each a link to the task (its drawer on the Tasks page), and any that failed. */
import { ArrowUpRight, CircleAlert, CircleCheck } from "@lucide/vue";
import { useI18n } from "vue-i18n";
import { RouterLink } from "vue-router";

import { useCompanyStore } from "@/stores/company";

import type { CreatedTask } from "../types";

withDefaults(defineProps<{ tasks: CreatedTask[]; failed?: Array<{ title: string; detail: string }>; celebrate?: boolean }>(), { failed: () => [], celebrate: false });
const emit = defineEmits<{ navigate: [] }>();
const { t } = useI18n();
const company = useCompanyStore();
</script>

<template>
  <div class="flex flex-col gap-4" data-testid="ai-created">
    <div v-if="celebrate && tasks.length" class="flex flex-col items-center gap-2 py-3 text-center">
      <span class="ai-done grid size-16 place-items-center rounded-full bg-success-soft text-success" aria-hidden="true"><CircleCheck :size="32" /></span>
      <p class="font-display text-xl text-fg">{{ t("ai.done.title", { n: tasks.length }, tasks.length) }}</p>
      <p class="max-w-[380px] text-base text-muted">{{ t("ai.done.body") }}</p>
    </div>
    <ul v-if="tasks.length" class="ui-card flex flex-col divide-y divide-line overflow-hidden">
      <li v-for="task in tasks" :key="task.id">
        <RouterLink
          :to="`/c/${company.currentId}/tasks?task=${task.id}`"
          class="group flex min-h-14 items-center gap-3 px-4 py-2.5 hover:bg-surface-2"
          :data-task="task.id"
          @click="emit('navigate')"
        >
          <CircleCheck :size="18" class="shrink-0 text-success" aria-hidden="true" />
          <span class="min-w-0 flex-1">
            <span class="block truncate text-base font-medium text-fg">{{ task.title }}</span>
            <span v-if="task.assignee_name" class="block truncate text-sm text-muted">{{ task.assignee_name }}</span>
          </span>
          <ArrowUpRight :size="16" class="shrink-0 text-subtle transition-transform group-hover:-translate-y-0.5 group-hover:translate-x-0.5" aria-hidden="true" />
        </RouterLink>
      </li>
    </ul>
    <ul v-if="failed.length" class="flex flex-col gap-2">
      <li v-for="(item, index) in failed" :key="index" class="flex items-start gap-2 rounded-[10px] bg-danger-soft px-3 py-2.5 text-sm text-danger">
        <CircleAlert :size="15" class="mt-0.5 shrink-0" aria-hidden="true" />
        <span><span class="font-semibold">{{ item.title }}</span> · {{ item.detail }}</span>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.ai-done {
  animation: enter 360ms var(--ease-out);
  --enter-scale: 0.6;
  --enter-opacity: 0;
}
</style>
