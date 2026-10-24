<script setup lang="ts">
/**
 * A task as a card: on the board, in phone lists and in the person's tab. Title with its project
 * key or routine, who and when, checklist progress, reward and a small proof preview.
 */
import { CheckCheck, Gift, ImageIcon, Repeat } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import MoneyText from "@/components/MoneyText.vue";
import UserAvatar from "@/components/UserAvatar.vue";

import { cardKey } from "../meta";
import type { TaskRow } from "../types";
import DueLabel from "./DueLabel.vue";
import PriorityFlag from "./PriorityFlag.vue";
import TaskFlags from "./TaskFlags.vue";
import TaskStatusPill from "./TaskStatusPill.vue";

const props = withDefaults(defineProps<{ task: TaskRow; showStatus?: boolean; showAssignee?: boolean }>(), { showStatus: false, showAssignee: true });

const { t } = useI18n();
const done = computed(() => props.task.status === "done");
</script>

<template>
  <div class="flex min-w-0 flex-col gap-2">
    <div class="flex min-w-0 items-start gap-2">
      <div class="min-w-0 flex-1">
        <p class="flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-xs text-muted">
          <span v-if="task.project" class="font-mono text-[11px] font-semibold text-subtle" :title="task.project.name">{{ cardKey(task.project) }}</span>
          <span v-if="task.routine" class="inline-flex min-w-0 items-center gap-1"><Repeat :size="11" aria-hidden="true" /><span class="truncate">{{ task.routine.onboarding ? t("tasks.kind.onboarding") : t("tasks.kind.routine") }}</span></span>
          <span v-else-if="task.kind === 'personal'" class="truncate">{{ t("tasks.kind.personal") }}</span>
          <PriorityFlag :priority="task.priority" :size="11" />
          <TaskFlags :task="task" />
        </p>
        <p :class="['mt-0.5 line-clamp-2 text-sm font-semibold leading-5', done ? 'text-muted' : 'text-fg']">{{ task.title }}</p>
      </div>
      <img v-if="task.proof_thumb" :src="task.proof_thumb" alt="" loading="lazy" class="size-10 shrink-0 rounded-[7px] border border-line object-cover" />
    </div>
    <div class="flex min-w-0 flex-wrap items-center gap-x-2.5 gap-y-1 text-xs text-muted">
      <TaskStatusPill v-if="showStatus" :status="task.status" :overdue="task.is_overdue" />
      <DueLabel :due="task.due_at" :overdue="task.is_overdue" icon compact />
      <span v-if="task.checklist.total" :class="['inline-flex items-center gap-1 tabular-nums', task.checklist.done === task.checklist.total && 'text-success']">
        <CheckCheck :size="13" aria-hidden="true" />{{ task.checklist.done }}/{{ task.checklist.total }}
      </span>
      <span v-if="task.proof === 'photo' && !task.proof_thumb && task.status !== 'done'" class="inline-flex items-center gap-1" :title="t('tasks.proof.photo')"><ImageIcon :size="13" aria-hidden="true" /></span>
      <span v-if="task.reward" class="inline-flex items-center gap-1 font-medium text-success"><Gift :size="13" aria-hidden="true" /><MoneyText :value="task.reward" compact /></span>
      <span class="flex-1" />
      <span v-if="showAssignee" class="inline-flex min-w-0 items-center gap-1.5">
        <span class="truncate max-sm:hidden">{{ task.assignee.name.split(" ")[0] }}</span>
        <UserAvatar :name="task.assignee.name" :src="task.assignee.photo_url" :size="20" />
      </span>
    </div>
  </div>
</template>
