<script setup lang="ts">
/**
 * Overview card `tasks.branches_now` (research R2 §3.19, T60): every branch right now, in one
 * glance: done today of what's due, late now, waiting for a check, and work that waits for the
 * manager's answer ("can't do it", "more time"). Each number opens that list. All work counts,
 * routines too: a manager looks at the branch, not at where the work came from.
 */
import { useQueries } from "@tanstack/vue-query";
import { AlarmClock, CircleCheck, Hourglass, MessageCircleQuestion, Store } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink } from "vue-router";

import type { Range } from "@/api/types";
import ErrorState from "@/components/ErrorState.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import WidgetCard from "@/components/WidgetCard.vue";
import { useWidgetSkeleton } from "@/components/widgetSkeleton";
import { todayIn } from "@/lib/dates";
import { useCompanyStore } from "@/stores/company";

import { taskKeys, tasksApi } from "../api";

const props = defineProps<{ companyId: number; range?: Range; compare?: Range | null }>();
const { t } = useI18n();
const company = useCompanyStore();

/** The branches in the person's scope; a chain of more than eight reads better on its own page. */
const branches = computed(() => (company.current?.branches ?? []).slice(0, 8));

const summaries = useQueries({
  queries: computed(() =>
    branches.value.map((branch) => {
      const params = { branch: [String(branch.id)] };
      return {
        queryKey: taskKeys.summary(props.companyId, params),
        queryFn: ({ signal }: { signal: AbortSignal }) => tasksApi.summary(props.companyId, params, signal),
        staleTime: 30_000,
      };
    }),
  ),
});
/** "Can't do it" plus "more time" per branch (a backend without them: no number). */
const answers = useQueries({
  queries: computed(() =>
    branches.value.map((branch) => ({
      queryKey: [props.companyId, "tasks", "branch-answers", branch.id] as const,
      queryFn: async ({ signal }: { signal: AbortSignal }) => {
        const [blocked, extension] = await Promise.all([
          tasksApi.list(props.companyId, { blocked: "true", branch: [String(branch.id)], page_size: 1 }, signal),
          tasksApi.list(props.companyId, { extension: "true", branch: [String(branch.id)], page_size: 1 }, signal),
        ]);
        const known = (blocked.results[0]?.blocker ?? true) && (extension.results[0]?.extension ?? true);
        return known ? { blocked: blocked.count, extension: extension.count } : null;
      },
      staleTime: 30_000,
      retry: false,
    })),
  ),
});

const pending = computed(() => summaries.value.some((query) => query.isPending));
const skeleton = useWidgetSkeleton(() => pending.value);
const failed = computed(() => summaries.value.find((query) => query.isError));

const rows = computed(() => {
  const today = todayIn(company.timezone);
  const base = `/c/${props.companyId}/tasks`;
  return branches.value.map((branch, index) => {
    const data = summaries.value[index]?.data;
    const waiting = answers.value[index]?.data ?? null;
    const scope = `branch=${branch.id}&routines=1`;
    return {
      branch,
      done: data ? { value: `${data.done_today}/${data.total_today}`, to: `${base}?sv=today&due_from=${today}&due_to=${today}&${scope}` } : null,
      late: data ? { value: data.late_now, to: `${base}?sv=late&overdue=true&${scope}` } : null,
      review: data ? { value: data.review, to: `${base}?sv=review&status=review&ordering=completed_at&${scope}` } : null,
      answers: waiting ? { value: waiting.blocked + waiting.extension, to: waiting.blocked ? `${base}?sv=blocked&blocked=true&${scope}` : `${base}/reviews` } : null,
    };
  });
});
</script>

<template>
  <WidgetCard :title="t('tasks.widget.branchesNow')" :icon="Store" :to="`/c/${companyId}/tasks`" :link-label="t('tasks.reviews.toTasks')" inset="content">
    <div v-if="skeleton" class="flex flex-col gap-3 pt-2"><SkeletonBlock v-for="n in Math.max(2, branches.length)" :key="n" height="36px" /></div>
    <ErrorState v-else-if="failed" compact :error="failed.error" :retry="() => failed?.refetch()" />
    <ul v-else class="flex flex-col divide-y divide-line" data-testid="branches-now">
      <li v-for="row in rows" :key="row.branch.id" class="flex flex-wrap items-center gap-x-4 gap-y-1.5 py-2.5 first:pt-1" :data-branch="row.branch.id">
        <p class="min-w-[120px] flex-1 truncate text-sm font-semibold text-fg" :title="row.branch.name">{{ row.branch.name }}</p>
        <div class="flex flex-wrap items-center gap-1.5 text-sm tabular-nums">
          <RouterLink v-if="row.done" :to="row.done.to" class="pressable inline-flex h-7 items-center gap-1 rounded-full px-2 text-muted hover:bg-highlight hover:text-fg" :title="t('tasks.kpi.doneToday')">
            <CircleCheck :size="14" class="text-success" aria-hidden="true" /><span class="font-semibold text-fg">{{ row.done.value }}</span><span class="max-sm:hidden">{{ t("tasks.widget.doneShort") }}</span>
          </RouterLink>
          <RouterLink
            v-if="row.late"
            :to="row.late.to"
            :class="['pressable inline-flex h-7 items-center gap-1 rounded-full px-2 hover:brightness-95', row.late.value ? 'bg-danger-soft font-semibold text-danger' : 'text-subtle hover:bg-highlight']"
            :title="t('tasks.kpi.lateNow')"
            data-stat="late"
          >
            <AlarmClock :size="14" aria-hidden="true" />{{ row.late.value }}<span class="max-sm:hidden">{{ t("tasks.widget.lateShort") }}</span>
          </RouterLink>
          <RouterLink
            v-if="row.review"
            :to="row.review.to"
            :class="['pressable inline-flex h-7 items-center gap-1 rounded-full px-2 hover:brightness-95', row.review.value ? 'bg-warning-soft font-semibold text-warning' : 'text-subtle hover:bg-highlight']"
            :title="t('tasks.kpi.review')"
            data-stat="review"
          >
            <Hourglass :size="14" aria-hidden="true" />{{ row.review.value }}<span class="max-sm:hidden">{{ t("tasks.widget.reviewShort") }}</span>
          </RouterLink>
          <RouterLink
            v-if="row.answers"
            :to="row.answers.to"
            :class="['pressable inline-flex h-7 items-center gap-1 rounded-full px-2 hover:brightness-95', row.answers.value ? 'bg-danger-soft font-semibold text-danger' : 'text-subtle hover:bg-highlight']"
            :title="t('tasks.answers.title')"
            data-stat="answers"
          >
            <MessageCircleQuestion :size="14" aria-hidden="true" />{{ row.answers.value }}<span class="max-sm:hidden">{{ t("tasks.widget.answersShort") }}</span>
          </RouterLink>
        </div>
      </li>
    </ul>
  </WidgetCard>
</template>
