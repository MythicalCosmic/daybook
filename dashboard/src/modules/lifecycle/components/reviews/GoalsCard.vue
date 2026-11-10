<script setup lang="ts">
/**
 * A published improvement plan's goals: what to reach and by when, how far it got (when a goal
 * has a measure) and whether it was reached. The reviewer (or an owner) marks them; the person
 * sees the same list in the app.
 */
import { CircleCheck, CircleDashed, CircleX } from "@lucide/vue";
import { useI18n } from "vue-i18n";

import ProgressBar from "@/components/ProgressBar.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import StatusPill from "@/components/StatusPill.vue";
import { toast } from "@/components/useToast";
import { useFormat } from "@/lib/useFormat";
import { useCompanyToday } from "@/stores/company";

import { reviewsApi, useReviewMutation } from "../../reviews/api";
import type { Goal, GoalStatus } from "../../reviews/types";

defineProps<{ goals: Goal[]; editable: boolean }>();

const { t } = useI18n();
const fmt = useFormat();
const today = useCompanyToday();

const TONES = { open: "info", done: "success", missed: "danger" } as const;
const ICONS = { open: CircleDashed, done: CircleCheck, missed: CircleX } as const;
const STATUSES: GoalStatus[] = ["open", "done", "missed"];
const options = () => STATUSES.map((value) => ({ value, label: t(`lifecycle.reviews.goalStatus.${value}`), icon: ICONS[value] }));

const save = useReviewMutation((cid, input: { id: number; status?: GoalStatus; progress?: string | null }) => reviewsApi.updateGoal(cid, input.id, input));
async function mark(goal: Goal, status: GoalStatus): Promise<void> {
  if (status === goal.status) return;
  await save.mutateAsync({ id: goal.id, status });
  toast.success(t("lifecycle.reviews.goalSaved"));
}
async function progress(goal: Goal, event: Event): Promise<void> {
  const value = (event.target as HTMLInputElement).value.trim().replace(",", ".");
  if (value === (goal.progress ?? "")) return;
  await save.mutateAsync({ id: goal.id, progress: value === "" ? null : value });
  toast.success(t("lifecycle.reviews.goalSaved"));
}
const share = (goal: Goal) => {
  const target = Number(goal.target);
  const done = Number(goal.progress);
  if (!(target > 0) || !Number.isFinite(done)) return null;
  return Math.max(0, Math.min(100, Math.round((100 * done) / target)));
};
</script>

<template>
  <ol class="flex flex-col gap-2.5" data-goals-card>
    <li v-for="(goal, index) in goals" :key="goal.id" class="rounded-[12px] border border-line px-3.5 py-3">
      <div class="flex flex-wrap items-start gap-3">
        <span class="mt-0.5 grid size-6 shrink-0 place-items-center rounded-full bg-surface-2 text-xs font-semibold text-muted dark:bg-surface-3">{{ index + 1 }}</span>
        <div class="min-w-0 flex-1">
          <p class="text-sm font-medium text-fg">{{ goal.title }}</p>
          <p class="mt-0.5 text-xs text-muted">
            {{ t("lifecycle.reviews.goalBy", { date: fmt.day(goal.due_on, "medium") }) }}
            <template v-if="goal.target !== null"> · {{ t("lifecycle.reviews.goalTargetLine", { target: fmt.number(goal.target, 2), unit: goal.unit }) }}</template>
            <span v-if="goal.status === 'open' && goal.due_on < today" class="text-danger"> · {{ t("lifecycle.reviews.goalOverdue") }}</span>
          </p>
          <div v-if="goal.target !== null" class="mt-2 flex items-center gap-2">
            <ProgressBar class="flex-1" :value="share(goal) ?? 0" :max="100" size="xs" :tone="goal.status === 'done' ? 'success' : 'primary'" />
            <input
              v-if="editable"
              :value="goal.progress ?? ''"
              inputmode="decimal"
              class="h-7 w-20 rounded-[8px] border border-line bg-surface px-2 text-right text-xs tabular-nums text-fg outline-none focus:border-[var(--c-primary)]"
              :aria-label="t('lifecycle.reviews.goalProgress')"
              @change="(event) => progress(goal, event)"
            />
            <span v-else class="text-xs tabular-nums text-muted">{{ goal.progress ? fmt.number(goal.progress, 2) : "—" }}</span>
          </div>
        </div>
        <SegmentedControl v-if="editable" size="sm" :model-value="goal.status" :options="options()" :aria-label="goal.title" @update:model-value="(value: GoalStatus) => mark(goal, value)" />
        <StatusPill v-else size="sm" :tone="TONES[goal.status]" :label="t(`lifecycle.reviews.goalStatus.${goal.status}`)" />
      </div>
    </li>
  </ol>
</template>
