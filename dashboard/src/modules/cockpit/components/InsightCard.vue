<script setup lang="ts">
/**
 * One insight: how urgent it is, the title, the plain explanation with its numbers, what to do,
 * a small trend of the numbers behind it, and the three answers: Got it (seen), Make it a task,
 * Dismiss (hidden while it lasts). The words come from the server in the reader's language.
 */
import { Check, EyeOff, Info, Lightbulb, ListTodo, OctagonAlert, TriangleAlert } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink } from "vue-router";

import RelativeTime from "@/components/RelativeTime.vue";
import SparkLine from "@/components/SparkLine.vue";
import StatusPill from "@/components/StatusPill.vue";
import UiButton from "@/components/UiButton.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { useCompanyStore } from "@/stores/company";

import { useInsightAction, useMakeTask, type Insight } from "../api";
import { SEVERITY_TONE } from "../lib";

const props = defineProps<{ insight: Insight; focused?: boolean; boxed?: boolean }>();

const { t } = useI18n();
const company = useCompanyStore();
const confirm = useConfirm();
const act = useInsightAction();
const makeTask = useMakeTask();
const busy = ref<"seen" | "task" | "dismiss" | null>(null);

const ICONS = { critical: OctagonAlert, warning: TriangleAlert, info: Info } as const;
const BAR = { critical: "bg-danger", warning: "bg-warning", info: "bg-info" } as const;
const ICON_TONE = { critical: "bg-danger-soft text-danger", warning: "bg-warning-soft text-warning", info: "bg-info-soft text-info" } as const;
const SPARK = { critical: "var(--c-danger)", warning: "var(--c-warning)", info: "var(--c-info)" } as const;

const seen = computed(() => props.insight.status === "acknowledged");
const series = computed(() => (Array.isArray(props.insight.metrics.series) ? (props.insight.metrics.series as Array<string | null>) : []));
const taskLink = computed(() => (props.insight.task ? `/c/${company.currentId}/tasks?task=${props.insight.task.id}` : null));

async function markSeen(): Promise<void> {
  busy.value = "seen";
  try {
    await act.mutateAsync({ insight: props.insight, action: "acknowledge" });
  } catch {
    // Shown by the HTTP layer.
  } finally {
    busy.value = null;
  }
}

async function toTask(): Promise<void> {
  busy.value = "task";
  try {
    const result = await makeTask.mutateAsync({ insight: props.insight });
    toast.success(t("cockpit.insights.taskMade"), { description: result.task.title });
  } catch {
    // Shown by the HTTP layer.
  } finally {
    busy.value = null;
  }
}

async function dismiss(): Promise<void> {
  const answer = await confirm({ title: t("cockpit.insights.dismissTitle"), message: t("cockpit.insights.dismissBody"), reason: "optional", confirmLabel: t("cockpit.insights.dismiss") });
  if (!answer) return;
  busy.value = "dismiss";
  try {
    await act.mutateAsync({ insight: props.insight, action: "dismiss", reason: answer.reason });
    toast.success(t("cockpit.insights.dismissed"), { description: props.insight.title });
  } catch {
    // Shown by the HTTP layer.
  } finally {
    busy.value = null;
  }
}
</script>

<template>
  <article
    :class="[
      'relative flex gap-3 py-4 pl-5 pr-4 transition-colors',
      boxed && 'lg:overflow-hidden lg:rounded-[12px] lg:border lg:border-line lg:bg-surface lg:hover:border-line-strong',
      focused && 'bg-accent-soft/40 ring-2 ring-[var(--c-primary)]/30',
    ]"
    :data-insight="insight.id"
    :data-severity="insight.severity"
    :data-status="insight.status"
    :aria-label="insight.title"
  >
    <span :class="['absolute inset-y-4 left-0 w-1 rounded-r-full', BAR[insight.severity], seen && 'opacity-40']" aria-hidden="true" />
    <span :class="['grid size-8 shrink-0 place-items-center rounded-[9px]', ICON_TONE[insight.severity], seen && 'opacity-60']" aria-hidden="true">
      <component :is="ICONS[insight.severity]" :size="16" />
    </span>
    <div class="min-w-0 flex-1">
      <div class="flex flex-wrap items-center gap-1.5">
        <StatusPill :tone="SEVERITY_TONE[insight.severity]" :label="t(`cockpit.insights.severity.${insight.severity}`)" size="sm" />
        <StatusPill v-if="seen" tone="neutral" variant="outline" size="sm" :dot="false" :icon="Check" :label="t('cockpit.insights.seen')" />
        <span v-if="insight.branch" class="truncate text-xs font-medium text-muted">{{ insight.branch.name }}</span>
        <RelativeTime :value="insight.detected_at" class="ml-auto shrink-0 text-[11px] text-subtle" />
      </div>
      <div class="mt-1.5 flex items-start gap-3">
        <div class="min-w-0 flex-1">
          <h3 class="text-sm font-semibold leading-5 text-fg">{{ insight.title }}</h3>
          <p v-if="insight.explanation" class="mt-1 text-sm leading-5 text-muted">{{ insight.explanation }}</p>
        </div>
        <SparkLine v-if="series.length > 2" :data="series" :color="SPARK[insight.severity]" :width="88" :height="34" :dot="true" class="mt-1 hidden shrink-0 sm:block" />
      </div>
      <p v-if="insight.suggested_action" class="mt-2.5 flex gap-2 rounded-[10px] bg-surface-2/70 px-3 py-2 text-sm leading-5 text-fg dark:bg-surface-3/50">
        <Lightbulb :size="15" class="mt-0.5 shrink-0 text-accent-fg" aria-hidden="true" />
        <span
          ><span class="font-semibold">{{ t("cockpit.insights.todo") }}:</span> {{ insight.suggested_action }}</span
        >
      </p>
      <div class="mt-3 flex flex-wrap items-center gap-1.5">
        <UiButton v-if="insight.status === 'open'" size="sm" variant="secondary" :icon="Check" :loading="busy === 'seen'" :disabled="!!busy" data-act="seen" @click="markSeen">{{
          t("cockpit.insights.markSeen")
        }}</UiButton>
        <RouterLink
          v-if="taskLink && insight.task"
          :to="taskLink"
          class="inline-flex h-7 max-w-full items-center gap-1.5 rounded-[7px] bg-success-soft px-2.5 text-xs font-semibold text-success transition-opacity hover:opacity-80"
          data-act="open-task"
        >
          <ListTodo :size="13" aria-hidden="true" /><span class="truncate">{{ t("cockpit.insights.task", { title: insight.task.title }) }}</span>
        </RouterLink>
        <UiButton v-else size="sm" variant="secondary" :icon="ListTodo" :loading="busy === 'task'" :disabled="!!busy" data-act="task" @click="toTask">{{ t("cockpit.insights.makeTask") }}</UiButton>
        <UiButton size="sm" variant="ghost" :icon="EyeOff" :loading="busy === 'dismiss'" :disabled="!!busy" data-act="dismiss" @click="dismiss">{{ t("cockpit.insights.dismiss") }}</UiButton>
      </div>
    </div>
  </article>
</template>
