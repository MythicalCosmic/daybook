<script setup lang="ts">
/**
 * Regular checks (Muntazam tekshiruvlar): a quiz sent to an audience every week or month at a
 * time, answered within some hours; reminders at half time and two hours before the end; the
 * managers hear the results. Each check with its schedule, audience, state and its latest round;
 * a check's rounds (who answered, passed, the hardest question) in a drawer.
 */
import { CalendarClock, Pause, Pencil, Play, Plus, Archive } from "@lucide/vue";
import { computed, reactive, ref } from "vue";
import { useI18n } from "vue-i18n";

import { isApiError } from "@/api/http";
import BranchPicker from "@/components/BranchPicker.vue";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import FormField from "@/components/FormField.vue";
import NumberInput from "@/components/NumberInput.vue";
import PageHeader from "@/components/PageHeader.vue";
import PersonCell from "@/components/PersonCell.vue";
import PositionPicker from "@/components/PositionPicker.vue";
import ProgressBar from "@/components/ProgressBar.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SelectBox from "@/components/SelectBox.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import TextInput from "@/components/TextInput.vue";
import TimePicker from "@/components/TimePicker.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import UiDrawer from "@/components/UiDrawer.vue";
import { toast } from "@/components/useToast";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { quizzesApi, useChecks, useQuizzes, useRefresh, useRound, useRounds } from "../api";
import AttemptDrawer from "../components/AttemptDrawer.vue";
import { percent, scheduleText } from "../lib";
import type { Check, CheckEvery, CheckState } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const refresh = useRefresh();
const canManage = computed(() => company.can("learning.manage"));
const checks = useChecks();
const quizzes = useQuizzes();

const STATE_TONES: Record<CheckState, "success" | "warning" | "neutral"> = { active: "success", paused: "warning", archived: "neutral" };

// The form ---------------------------------------------------------------------------------------

const editing = ref<Check | null>(null);
const formOpen = ref(false);
const saving = ref(false);
const errors = ref<Record<string, string>>({});
const form = reactive({
  title: "",
  quiz_id: null as number | null,
  every: "week" as CheckEvery,
  weekday: 0,
  month_day: 1,
  at: "10:00" as string | null,
  answer_within_hours: 48,
  audience_all: true,
  position_ids: [] as number[],
  branch_ids: [] as number[],
});

function edit(row: Check | null): void {
  editing.value = row;
  errors.value = {};
  Object.assign(form, {
    title: row?.title ?? "",
    quiz_id: row?.quiz.id ?? null,
    every: row?.every ?? "week",
    weekday: row?.weekday ?? 0,
    month_day: row?.month_day ?? 1,
    at: row?.at.slice(0, 5) ?? "10:00",
    answer_within_hours: row?.answer_within_hours ?? 48,
    audience_all: row?.audience_all ?? true,
    position_ids: [...(row?.position_ids ?? [])],
    branch_ids: [...(row?.branch_ids ?? [])],
  });
  formOpen.value = true;
}

const quizOptions = computed(() => (quizzes.data.value ?? []).filter((quiz) => quiz.status !== "archived").map((quiz) => ({ value: quiz.id, label: quiz.title, description: t(`quizzes.status.${quiz.status}`) })));
const weekdayOptions = computed(() => [0, 1, 2, 3, 4, 5, 6].map((value) => ({ value, label: t(`quizzes.weekday.${value}`) })));
const everyOptions = computed(() => [
  { value: "week" as CheckEvery, label: t("quizzes.checks.everyWeek") },
  { value: "month" as CheckEvery, label: t("quizzes.checks.everyMonth") },
]);

async function save(): Promise<void> {
  errors.value = {};
  if (!form.title.trim()) errors.value.title = t("quizzes.checks.errTitle");
  if (!form.quiz_id) errors.value.quiz_id = t("quizzes.checks.errQuiz");
  if (Object.keys(errors.value).length) return;
  saving.value = true;
  const input = {
    title: form.title.trim(),
    quiz_id: form.quiz_id ?? undefined,
    every: form.every,
    weekday: form.every === "week" ? form.weekday : null,
    month_day: form.every === "month" ? form.month_day : null,
    at: form.at ?? "10:00",
    answer_within_hours: form.answer_within_hours,
    audience_all: form.audience_all,
    position_ids: form.audience_all ? [] : form.position_ids,
    branch_ids: form.branch_ids,
  };
  try {
    if (editing.value) await quizzesApi.updateCheck(company.currentId ?? 0, editing.value.id, input);
    else await quizzesApi.createCheck(company.currentId ?? 0, input);
    toast.success(t("quizzes.checks.saved"));
    refresh();
    formOpen.value = false;
  } catch (failure) {
    if (isApiError(failure)) {
      errors.value = Object.fromEntries(Object.entries(failure.fieldErrors).map(([key, messages]) => [key, messages[0] ?? ""]));
      if (failure.detail) errors.value.form = failure.detail;
    }
  } finally {
    saving.value = false;
  }
}

async function act(row: Check, action: "pause" | "resume" | "archive"): Promise<void> {
  await quizzesApi.checkAction(company.currentId ?? 0, row.id, action);
  toast.success(t(`quizzes.checks.done.${action}`));
  refresh();
}

// Rounds -------------------------------------------------------------------------------------------

const roundsOf = ref<Check | null>(null);
const roundsOpen = ref(false);
const rounds = useRounds(() => (roundsOpen.value ? (roundsOf.value?.id ?? null) : null));
const roundId = ref<number | null>(null);
const round = useRound(() => roundsOf.value?.id ?? null, roundId);
function showRounds(row: Check): void {
  roundsOf.value = row;
  roundId.value = row.last_round?.id ?? null;
  roundsOpen.value = true;
}
const reviewing = ref<number | null>(null);
const reviewOpen = ref(false);
function review(attemptId: number | null): void {
  if (!attemptId) return;
  reviewing.value = attemptId;
  reviewOpen.value = true;
}
</script>

<template>
  <div>
    <PageHeader :title="t('quizzes.nav.checks')" :description="t('quizzes.checks.description')">
      <template #actions>
        <UiButton v-if="canManage" variant="primary" :icon="Plus" @click="edit(null)">{{ t("quizzes.checks.new") }}</UiButton>
      </template>
    </PageHeader>

    <div v-if="checks.isPending.value" class="grid gap-3"><SkeletonBlock v-for="n in 3" :key="n" height="88px" radius="12px" /></div>
    <ErrorState v-else-if="checks.error.value" :error="checks.error.value" :retry="() => checks.refetch()" />
    <div v-else-if="!checks.data.value?.length" class="ui-card">
      <EmptyState :icon="CalendarClock" :title="t('quizzes.checks.emptyTitle')" :description="t('quizzes.checks.emptyBody')">
        <UiButton v-if="canManage" variant="primary" :icon="Plus" @click="edit(null)">{{ t("quizzes.checks.new") }}</UiButton>
      </EmptyState>
    </div>
    <ul v-else class="grid gap-3" data-testid="checks">
      <li v-for="row in checks.data.value" :key="row.id" class="ui-card flex flex-wrap items-center gap-4 p-4">
        <CalendarClock :size="20" class="shrink-0 text-muted" aria-hidden="true" />
        <button type="button" class="min-w-0 flex-1 text-left" @click="showRounds(row)">
          <p class="truncate font-medium text-fg">{{ row.title }}</p>
          <p class="truncate text-xs text-muted">
            {{ scheduleText(row, t) }} · {{ t("quizzes.checks.within", { n: row.answer_within_hours }, row.answer_within_hours) }} · {{ row.quiz.title }}
          </p>
          <p v-if="row.next_run_at" class="truncate text-xs text-muted">{{ t("quizzes.checks.next", { when: fmt.instant(row.next_run_at) }) }}</p>
        </button>
        <div v-if="row.last_round" class="flex w-full flex-col gap-1 sm:w-60">
          <p class="text-xs text-muted">{{ t("quizzes.checks.lastRound", { done: row.last_round.done, people: row.last_round.people }) }}</p>
          <ProgressBar :value="percent(row.last_round.done, row.last_round.people) ?? 0" :max="100" size="sm" tone="auto" />
        </div>
        <StatusPill size="sm" :tone="STATE_TONES[row.state]" :label="t(`quizzes.checkState.${row.state}`)" />
        <div v-if="canManage" class="flex gap-1">
          <UiButton size="sm" variant="ghost" :icon="Pencil" :aria-label="t('quizzes.checks.edit')" @click="edit(row)" />
          <UiButton v-if="row.state === 'active'" size="sm" variant="ghost" :icon="Pause" :aria-label="t('quizzes.checks.pause')" @click="act(row, 'pause')" />
          <UiButton v-else-if="row.state === 'paused'" size="sm" variant="ghost" :icon="Play" :aria-label="t('quizzes.checks.resume')" @click="act(row, 'resume')" />
          <UiButton v-if="row.state !== 'archived'" size="sm" variant="ghost" :icon="Archive" :aria-label="t('quizzes.checks.archive')" @click="act(row, 'archive')" />
        </div>
      </li>
    </ul>

    <UiDialog v-model:open="formOpen" :title="editing ? t('quizzes.checks.edit') : t('quizzes.checks.new')" :description="t('quizzes.checks.formBody')" size="md">
      <div class="flex flex-col gap-3">
        <p v-if="errors.form" class="text-sm text-danger">{{ errors.form }}</p>
        <FormField :label="t('quizzes.checks.name')" :error="errors.title" required>
          <TextInput v-model="form.title" :maxlength="200" :placeholder="t('quizzes.checks.namePlaceholder')" />
        </FormField>
        <FormField :label="t('quizzes.checks.quiz')" :error="errors.quiz_id" required>
          <SelectBox v-model="form.quiz_id" :options="quizOptions" :placeholder="t('quizzes.checks.pickQuiz')" />
        </FormField>
        <FormField :label="t('quizzes.checks.every')">
          <SegmentedControl v-model="form.every" :options="everyOptions" />
        </FormField>
        <div class="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <FormField v-if="form.every === 'week'" :label="t('quizzes.checks.weekday')" :error="errors.weekday">
            <SelectBox :model-value="form.weekday" :options="weekdayOptions" @update:model-value="(value) => (form.weekday = (value as number) ?? 0)" />
          </FormField>
          <FormField v-else :label="t('quizzes.checks.monthDay')" :hint="t('quizzes.checks.monthDayHint')" :error="errors.month_day">
            <NumberInput :model-value="form.month_day" :min="1" :max="28" @update:model-value="(value) => (form.month_day = value ?? 1)" />
          </FormField>
          <FormField :label="t('quizzes.checks.at')" :error="errors.at">
            <TimePicker v-model="form.at" />
          </FormField>
          <FormField :label="t('quizzes.checks.window')" :error="errors.answer_within_hours">
            <NumberInput :model-value="form.answer_within_hours" :min="1" :max="168" :suffix="t('quizzes.checks.hours')" @update:model-value="(value) => (form.answer_within_hours = value ?? 48)" />
          </FormField>
        </div>
        <ToggleSwitch v-model="form.audience_all" :label="t('quizzes.checks.everyone')" />
        <FormField v-if="!form.audience_all" :label="t('quizzes.checks.positions')">
          <PositionPicker v-model="form.position_ids" multiple />
        </FormField>
        <FormField :label="t('quizzes.checks.branches')" :hint="t('quizzes.checks.branchesHint')" optional>
          <BranchPicker v-model="form.branch_ids" multiple />
        </FormField>
      </div>
      <template #footer>
        <UiButton variant="ghost" @click="formOpen = false">{{ t("common.cancel") }}</UiButton>
        <UiButton variant="primary" :loading="saving" data-testid="check-save" @click="save">{{ t("common.save") }}</UiButton>
      </template>
    </UiDialog>

    <UiDrawer v-model:open="roundsOpen" :title="roundsOf?.title ?? ''" :description="roundsOf ? scheduleText(roundsOf, t) : undefined" size="lg">
      <div class="flex flex-col gap-4 p-5">
        <div v-if="rounds.isPending.value" class="grid gap-2"><SkeletonBlock v-for="n in 3" :key="n" height="40px" /></div>
        <p v-else-if="!rounds.data.value?.length" class="text-sm text-muted">{{ t("quizzes.checks.noRounds") }}</p>
        <div v-else class="flex flex-wrap gap-2">
          <UiButton v-for="row in rounds.data.value" :key="row.id" size="sm" :variant="roundId === row.id ? 'primary' : 'secondary'" @click="roundId = row.id">
            {{ fmt.instant(row.starts_at, "short") }} · {{ row.done }}/{{ row.people }}
          </UiButton>
        </div>
        <div v-if="round.data.value" class="flex flex-col gap-3">
          <div class="flex flex-wrap items-center gap-2 text-sm">
            <StatusPill size="sm" :tone="round.data.value.closed_at ? 'neutral' : 'info'" :label="round.data.value.closed_at ? t('quizzes.checks.closed') : t('quizzes.checks.open', { when: fmt.instant(round.data.value.due_at) })" />
            <span class="text-muted">{{ t("quizzes.checks.roundCounts", { done: round.data.value.done, people: round.data.value.people, passed: round.data.value.passed }) }}</span>
          </div>
          <p v-if="round.data.value.weakest" class="rounded-lg bg-warning-soft px-3 py-2 text-sm text-warning">
            {{ t("quizzes.checks.weakest", { text: round.data.value.weakest.text, n: round.data.value.weakest.percent }) }}
          </p>
          <ul class="divide-y divide-line rounded-lg border border-line">
            <li v-for="entry in round.data.value.entries" :key="entry.id" class="flex items-center gap-3 px-3 py-2">
              <PersonCell class="min-w-0 flex-1" :person="entry.member" :subtitle="entry.member.position ?? undefined" size="sm" />
              <template v-if="entry.done">
                <span class="text-sm tabular-nums text-fg">{{ entry.percent }} %</span>
                <UiButton size="sm" variant="ghost" @click="review(entry.attempt_id)">
                  <StatusPill size="sm" :tone="entry.passed ? 'success' : 'danger'" :label="entry.passed ? t('quizzes.results.passed') : t('quizzes.results.failed')" />
                </UiButton>
              </template>
              <StatusPill v-else size="sm" tone="neutral" :label="t('quizzes.checks.notYet')" />
            </li>
          </ul>
        </div>
      </div>
    </UiDrawer>
    <AttemptDrawer v-model:open="reviewOpen" :attempt-id="reviewing" />
  </div>
</template>
