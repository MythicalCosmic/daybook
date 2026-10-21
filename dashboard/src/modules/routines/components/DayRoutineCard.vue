<script setup lang="ts">
/**
 * One routine on a day: its time, branch and proof, progress ("5/7 · 71 %"), what needs a look
 * (late, to confirm), each person's run and who was skipped and why. A routine made after the
 * day's time says when it starts and, today, offers "Give today's task now"; a holiday says so.
 */
import { Camera, ChevronDown, Clock, PartyPopper, Send, ShieldCheck, Store } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import ProgressBar from "@/components/ProgressBar.vue";
import UiButton from "@/components/UiButton.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { useFormat } from "@/lib/useFormat";
import { usePermission } from "@/lib/usePermission";

import { capitalize, runDayWords } from "../lib";
import type { DayRoutine, GiveTarget, RoutineRun } from "../types";
import { useRunWords } from "../useRunWords";
import RunRow from "./RunRow.vue";

const props = withDefaults(defineProps<{ row: DayRoutine; day: string; busy?: Set<number> }>(), { busy: () => new Set() });
const emit = defineEmits<{ give: [target: GiveTarget]; confirm: [run: RoutineRun]; sendBack: [run: RoutineRun] }>();

const FIRST = 9;
const { t } = useI18n();
const fmt = useFormat();
const words = useRunWords();
const { can } = usePermission();

const routine = computed(() => props.row.routine);
const expanded = ref(false);
const runs = computed(() => (expanded.value ? props.row.runs : props.row.runs.slice(0, FIRST)));
const hidden = computed(() => props.row.runs.length - runs.value.length);
const percent = computed(() => (props.row.progress.percent === null ? "—" : fmt.percent(props.row.progress.percent, 0)));
const tone = computed(() => {
  const { counts, progress } = props.row;
  if (counts.late + counts.missed > 0) return "warning" as const;
  return progress.total > 0 && progress.finished === progress.total ? ("success" as const) : ("primary" as const);
});
const attention = computed(() =>
  [
    { key: "late", n: props.row.counts.late + props.row.counts.missed, tone: "bg-danger-soft text-danger" },
    { key: "review", n: props.row.counts.review, tone: "bg-warning-soft text-warning" },
  ].filter((chip) => chip.n > 0),
);

const lateNote = computed(() => {
  if (props.row.reason !== "made_late") return null;
  const time = routine.value.due_time;
  const day = props.row.next_run ? runDayWords(props.row.next_run, words.value) : null;
  return {
    title: day ? capitalize(t("routines.give.title", { day })) : t("routines.give.titleLater"),
    body: props.row.give ? t("routines.give.detailBody", { due: time, n: props.row.give.people }, props.row.give.people) : t("routines.give.detailBodyNobody", { due: time }),
  };
});

function give(): void {
  const { routine: ref_, next_run, give: offer } = props.row;
  emit("give", { id: ref_.id, title: ref_.title, due_time: ref_.due_time, next_run, today: { date: props.day, reason: "made_late", give: offer } });
}
</script>

<template>
  <article class="ui-card min-w-0 overflow-hidden" :data-routine="routine.id">
    <header class="flex flex-wrap items-center gap-x-5 gap-y-3 p-4">
      <div class="min-w-[min(100%,240px)] flex-1">
        <div class="flex min-w-0 items-center gap-2">
          <RouterLink
            v-if="can('tasks.templates')"
            :to="{ name: 'routines.detail', params: { id: routine.id } }"
            class="min-w-0 truncate text-base font-semibold text-fg hover:underline"
            :title="routine.title"
            >{{ routine.title }}</RouterLink
          >
          <p v-else class="min-w-0 truncate text-base font-semibold text-fg" :title="routine.title">{{ routine.title }}</p>
          <span v-if="!routine.is_active" class="shrink-0 rounded-full bg-surface-2 px-2 py-px text-xs font-medium text-muted">{{ t("routines.paused") }}</span>
        </div>
        <p class="mt-1 flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1 text-sm text-muted">
          <span class="inline-flex items-center gap-1 tabular-nums"><Clock :size="14" aria-hidden="true" />{{ routine.due_time }}</span>
          <span v-if="routine.branch" class="inline-flex items-center gap-1"><Store :size="14" aria-hidden="true" />{{ routine.branch.name }}</span>
          <span v-if="routine.proof !== 'none'" class="inline-flex items-center gap-1"><Camera :size="14" aria-hidden="true" />{{ t(`routines.proof.${routine.proof}`) }}</span>
          <span v-if="routine.needs_confirmation" class="inline-flex items-center gap-1"><ShieldCheck :size="14" aria-hidden="true" />{{ t("routines.today.checked") }}</span>
          <span v-for="chip in attention" :key="chip.key" :class="['rounded-full px-2 py-px text-xs font-semibold', chip.tone]">{{ t(`routines.today.chip.${chip.key}`, { n: chip.n }, chip.n) }}</span>
        </p>
      </div>
      <div v-if="row.progress.total" class="flex w-full items-center gap-3 sm:w-[280px]">
        <ProgressBar :value="row.progress.finished" :max="row.progress.total" :tone="tone" size="md" class="flex-1" :aria-label="t('routines.today.progressLabel')" />
        <p class="shrink-0 whitespace-nowrap text-sm">
          <span class="font-semibold tabular-nums text-fg">{{ t("routines.today.progress", { done: row.progress.finished, total: row.progress.total }) }}</span>
          <span class="text-muted"> · {{ percent }}</span>
        </p>
      </div>
    </header>

    <div v-if="lateNote" class="mx-4 mb-4 flex flex-wrap items-center gap-3 rounded-[10px] border border-[color-mix(in_srgb,var(--c-warning)_28%,transparent)] bg-warning-soft/70 px-3.5 py-3" data-testid="day-late">
      <div class="min-w-0 flex-1">
        <p class="text-sm font-semibold text-fg">{{ lateNote.title }}</p>
        <p class="mt-0.5 text-sm text-muted">{{ lateNote.body }}</p>
      </div>
      <UiButton v-if="row.give" size="sm" variant="primary" :icon="Send" @click="give">{{ t("routines.give.button") }}</UiButton>
    </div>
    <p v-else-if="row.reason === 'holiday'" class="mx-4 mb-4 flex items-center gap-2 rounded-[10px] bg-info-soft px-3 py-2.5 text-sm text-info">
      <PartyPopper :size="15" aria-hidden="true" />{{ t("routines.preview.holiday") }}
    </p>

    <ul v-if="runs.length" class="grid gap-2 px-4 pb-4 sm:grid-cols-2 2xl:grid-cols-3">
      <RunRow v-for="run in runs" :key="run.id" :run="run" :title="routine.title" :busy="busy.has(run.id)" @confirm="emit('confirm', $event)" @send-back="emit('sendBack', $event)" />
    </ul>
    <div v-if="hidden > 0" class="-mt-2 px-4 pb-3">
      <UiButton size="sm" variant="ghost" :icon="ChevronDown" @click="expanded = true">{{ t("routines.today.showAll", { n: row.runs.length }) }}</UiButton>
    </div>

    <footer v-if="row.skipped.length" class="flex flex-wrap items-center gap-x-2 gap-y-1.5 border-t border-line bg-surface-2/40 px-4 py-2.5">
      <span class="mr-1 text-xs font-semibold uppercase tracking-[0.05em] text-subtle">{{ t("routines.today.skipped") }}</span>
      <span
        v-for="skip in row.skipped"
        :key="skip.member.id"
        class="inline-flex max-w-full items-center gap-1.5 rounded-full bg-surface py-0.5 pl-0.5 pr-2.5 text-xs shadow-xs ring-1 ring-line"
        :title="`${skip.member.name} · ${t(`routines.preview.reason.${skip.reason}`)}`"
      >
        <UserAvatar :name="skip.member.name" :src="skip.member.photo_url" :size="18" />
        <span class="truncate font-medium text-fg">{{ skip.member.name }}</span>
        <span class="shrink-0 text-muted">· {{ t(`routines.preview.reason.${skip.reason}`) }}</span>
      </span>
    </footer>
  </article>
</template>
