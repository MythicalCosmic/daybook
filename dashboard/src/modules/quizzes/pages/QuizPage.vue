<script setup lang="ts">
/**
 * One quiz: its settings (a fixed list in its order, or questions drawn at random from topics;
 * shuffling, the time limit, the pass mark, attempts and the wait, partial credit, when the
 * answers show, who takes it), a learner's preview (a fresh draw with the answers), and the
 * results among the people the viewer sees (the attempts, the score distribution, the hardest
 * questions, reset for one person).
 */
import { Archive, ArrowDown, ArrowUp, Eye, Play, Plus, RotateCcw, Save, Trash2, Undo2 } from "@lucide/vue";
import { computed, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import { isApiError } from "@/api/http";
import BarChart from "@/components/BarChart.vue";
import DataTable from "@/components/DataTable.vue";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import FormField from "@/components/FormField.vue";
import KpiStrip from "@/components/KpiStrip.vue";
import MultiSelect from "@/components/MultiSelect.vue";
import NumberInput from "@/components/NumberInput.vue";
import PageHeader from "@/components/PageHeader.vue";
import PageSection from "@/components/PageSection.vue";
import PersonCell from "@/components/PersonCell.vue";
import PositionPicker from "@/components/PositionPicker.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SelectBox from "@/components/SelectBox.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import type { TableColumn } from "@/components/table";
import TextArea from "@/components/TextArea.vue";
import TextInput from "@/components/TextInput.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { useConfirm } from "@/components/useConfirm";
import { useDataTable } from "@/components/useDataTable";
import { toast } from "@/components/useToast";
import { useFormat } from "@/lib/useFormat";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useCompanyStore } from "@/stores/company";

import { quizzesApi, useQuestions, useQuiz, useRefresh, useResults, useTopics } from "../api";
import AttemptDrawer from "../components/AttemptDrawer.vue";
import QuestionPreview from "../components/QuestionPreview.vue";
import { moved } from "../lib";
import type { PreviewItem, Question, QuizMode, ResultAttempt, ShowAnswers } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const route = useRoute();
const router = useRouter();
const company = useCompanyStore();
const confirm = useConfirm();
const refresh = useRefresh();
const canManage = computed(() => company.can("learning.manage"));

const quizId = computed(() => Number(route.params.quizId));
const quiz = useQuiz(quizId);
const topics = useTopics();
const tab = useRouteState("tab", rs.string("settings"));
const tabs = computed(() => [
  { id: "settings", label: t("quizzes.quiz.tabSettings") },
  { id: "results", label: t("quizzes.quiz.tabResults"), count: quiz.data.value?.attempts },
  ...(canManage.value ? [{ id: "preview", label: t("quizzes.quiz.tabPreview") }] : []),
]);

// Settings ---------------------------------------------------------------------------------------

const form = reactive({
  title: "",
  emoji: "",
  description: "",
  mode: "random" as QuizMode,
  question_count: 10,
  topic_ids: [] as number[],
  question_ids: [] as number[],
  shuffle_questions: true,
  shuffle_options: true,
  limited: false,
  minutes: 10,
  pass_percent: 70,
  capped: false,
  max_attempts: 3,
  retry_after_minutes: 0,
  partial_credit: true,
  show_answers: "after" as ShowAnswers,
  audience_all: true,
  position_ids: [] as number[],
});
const listed = ref<Question[]>([]);
const errors = ref<Record<string, string>>({});
const saving = ref(false);

watch(
  () => quiz.data.value,
  (found) => {
    if (!found) return;
    Object.assign(form, {
      title: found.title,
      emoji: found.emoji,
      description: found.description,
      mode: found.mode,
      question_count: found.question_count,
      topic_ids: [...found.topic_ids],
      question_ids: [...found.question_ids],
      shuffle_questions: found.shuffle_questions,
      shuffle_options: found.shuffle_options,
      limited: found.time_limit_seconds !== null,
      minutes: found.time_limit_seconds ? Math.max(1, Math.round(found.time_limit_seconds / 60)) : 10,
      pass_percent: found.pass_percent,
      capped: found.max_attempts !== null,
      max_attempts: found.max_attempts ?? 3,
      retry_after_minutes: found.retry_after_minutes,
      partial_credit: found.partial_credit,
      show_answers: found.show_answers,
      audience_all: found.audience_all,
      position_ids: [...found.position_ids],
    });
  },
  { immediate: true },
);

// The questions of the list, read from the bank (in the list's order).
const listQuery = useQuestions(computed(() => ({ page_size: 200 })));
watch(
  () => [form.question_ids, listQuery.data.value] as const,
  () => {
    const known = new Map((listQuery.data.value?.results ?? []).map((row) => [row.id, row]));
    listed.value = form.question_ids.map((id) => known.get(id)).filter((row): row is Question => !!row);
  },
  { immediate: true, deep: true },
);

const modeOptions = computed(() => [
  { value: "random" as QuizMode, label: t("quizzes.mode.random") },
  { value: "fixed" as QuizMode, label: t("quizzes.mode.fixed") },
]);
const showOptions = computed(() => (["after", "passed", "never"] as ShowAnswers[]).map((value) => ({ value, label: t(`quizzes.show.${value}`) })));
const topicOptions = computed(() => (topics.data.value ?? []).filter((topic) => !topic.archived || form.topic_ids.includes(topic.id)).map((topic) => ({ value: topic.id, label: topic.name })));

async function save(): Promise<void> {
  errors.value = {};
  if (!form.title.trim()) {
    errors.value = { title: t("quizzes.quiz.errTitle") };
    return;
  }
  saving.value = true;
  try {
    await quizzesApi.updateQuiz(company.currentId ?? 0, quizId.value, {
      title: form.title.trim(),
      emoji: form.emoji.trim(),
      description: form.description.trim(),
      mode: form.mode,
      question_count: form.question_count,
      topic_ids: form.topic_ids,
      question_ids: form.question_ids,
      shuffle_questions: form.shuffle_questions,
      shuffle_options: form.shuffle_options,
      time_limit_seconds: form.limited ? form.minutes * 60 : null,
      pass_percent: form.pass_percent,
      max_attempts: form.capped ? form.max_attempts : null,
      retry_after_minutes: form.retry_after_minutes,
      partial_credit: form.partial_credit,
      show_answers: form.show_answers,
      audience_all: form.audience_all,
      position_ids: form.audience_all ? [] : form.position_ids,
    });
    toast.success(t("quizzes.quiz.saved"));
    refresh();
  } catch (failure) {
    if (isApiError(failure)) {
      errors.value = Object.fromEntries(Object.entries(failure.fieldErrors).map(([key, messages]) => [key, messages[0] ?? ""]));
      if (failure.detail) toast.error(failure.detail);
    }
  } finally {
    saving.value = false;
  }
}

async function act(action: "publish" | "archive" | "restore"): Promise<void> {
  try {
    await quizzesApi.quizAction(company.currentId ?? 0, quizId.value, action);
    toast.success(t(`quizzes.quiz.done.${action}`));
    refresh();
  } catch (failure) {
    if (isApiError(failure) && failure.detail) toast.error(failure.detail);
  }
}

async function remove(): Promise<void> {
  const answer = await confirm({
    title: t("quizzes.quiz.deleteTitle", { title: form.title }),
    confirmLabel: t("quizzes.quiz.delete"),
    tone: "danger",
    onConfirm: () => quizzesApi.deleteQuiz(company.currentId ?? 0, quizId.value),
  });
  if (answer) {
    refresh();
    void router.push(`/c/${company.currentId}/learning/quizzes`);
  }
}

// Picking questions for the list.
const picking = ref(false);
const pickSearch = ref("");
const pickable = useQuestions(computed(() => ({ state: "active", q: pickSearch.value || undefined, page_size: 50 })));
function addToList(row: Question): void {
  if (!form.question_ids.includes(row.id)) form.question_ids = [...form.question_ids, row.id];
}

// Preview ---------------------------------------------------------------------------------------

const previewing = ref(false);
const drawn = ref<PreviewItem[] | null>(null);
async function draw(): Promise<void> {
  previewing.value = true;
  try {
    drawn.value = (await quizzesApi.preview(company.currentId ?? 0, quizId.value)).questions;
  } finally {
    previewing.value = false;
  }
}
watch(tab, (value) => {
  if (value === "preview" && drawn.value === null) void draw();
});

// Results ---------------------------------------------------------------------------------------

const results = useResults(quizId, computed(() => ({ branch: company.branchFilter.length === 1 ? company.branchFilter[0] : undefined })));
const table = useDataTable({ id: "quizzes.results", pageSize: 50 });
const resultColumns = computed<TableColumn<ResultAttempt>[]>(() => [
  { id: "member", header: t("quizzes.col.person"), minWidth: 200, value: (row) => row.member.name },
  { id: "number", header: t("quizzes.col.attempt"), width: 90, numeric: true },
  { id: "percent", header: t("quizzes.col.score"), width: 110, numeric: true },
  { id: "passed", header: t("quizzes.col.result"), width: 130 },
  { id: "finished_at", header: t("quizzes.col.finished"), width: 170, format: (value) => (value ? fmt.instant(String(value)) : "—") },
  ...(canManage.value ? [{ id: "actions", header: "", width: 120, hideable: false } as TableColumn<ResultAttempt>] : []),
]);
const kpis = computed(() => {
  const summary = results.data.value?.summary;
  return [
    { label: t("quizzes.results.attempts"), value: summary?.attempts ?? null },
    { label: t("quizzes.results.people"), value: summary?.people ?? null },
    { label: t("quizzes.results.passRate"), value: summary?.pass_rate ?? null, format: "percent" as const },
    { label: t("quizzes.results.average"), value: summary?.average ?? null, format: "percent" as const },
  ];
});
const distribution = computed(() => {
  const rows = results.data.value?.distribution ?? [];
  return {
    categories: rows.map((row) => `${row.start}–${row.end}`),
    series: [{ name: t("quizzes.results.attempts"), data: rows.map((row) => row.count) }],
  };
});
const reviewing = ref<number | null>(null);
const reviewOpen = ref(false);
function review(row: ResultAttempt): void {
  reviewing.value = row.id;
  reviewOpen.value = true;
}
async function reset(row: ResultAttempt): Promise<void> {
  const answer = await confirm({
    title: t("quizzes.results.resetTitle", { name: row.member.name }),
    message: t("quizzes.results.resetBody"),
    confirmLabel: t("quizzes.results.reset"),
    onConfirm: () => quizzesApi.reset(company.currentId ?? 0, quizId.value, row.member.id),
  });
  if (answer) {
    toast.success(t("quizzes.results.resetDone", { name: row.member.name }));
    refresh();
  }
}
</script>

<template>
  <div>
    <PageHeader v-model:tab="tab" :title="quiz.data.value ? `${quiz.data.value.emoji ? `${quiz.data.value.emoji} ` : ''}${quiz.data.value.title}` : t('quizzes.quiz.title')" :back="`/c/${company.currentId}/learning/quizzes`" :back-label="t('quizzes.nav.quizzes')" :tabs="tabs">
      <template #actions>
        <template v-if="quiz.data.value && canManage">
          <StatusPill :tone="quiz.data.value.status === 'published' ? 'success' : quiz.data.value.status === 'draft' ? 'warning' : 'neutral'" :label="t(`quizzes.status.${quiz.data.value.status}`)" />
          <UiButton v-if="quiz.data.value.status !== 'published'" variant="primary" :icon="Play" data-testid="quiz-publish" @click="act(quiz.data.value.status === 'archived' ? 'restore' : 'publish')">
            {{ quiz.data.value.status === "archived" ? t("quizzes.quiz.restore") : t("quizzes.quiz.publish") }}
          </UiButton>
          <UiButton v-else variant="secondary" :icon="Archive" @click="act('archive')">{{ t("quizzes.quiz.archive") }}</UiButton>
        </template>
      </template>
    </PageHeader>

    <div v-if="quiz.isPending.value" class="grid gap-3"><SkeletonBlock v-for="n in 3" :key="n" height="120px" radius="12px" /></div>
    <ErrorState v-else-if="quiz.error.value" :error="quiz.error.value" :retry="() => quiz.refetch()" />

    <!-- Settings -->
    <div v-else-if="tab === 'settings' && quiz.data.value" class="grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
      <PageSection variant="card" :title="t('quizzes.quiz.about')">
        <div class="flex flex-col gap-3">
          <div class="grid grid-cols-[80px_1fr] gap-3">
            <FormField :label="t('quizzes.quiz.emoji')" optional><TextInput v-model="form.emoji" :maxlength="4" :disabled="!canManage" /></FormField>
            <FormField :label="t('quizzes.quiz.name')" :error="errors.title" required><TextInput v-model="form.title" :maxlength="200" :disabled="!canManage" /></FormField>
          </div>
          <FormField :label="t('quizzes.quiz.description')" optional><TextArea v-model="form.description" :rows="2" autosize :max-rows="5" :maxlength="500" :disabled="!canManage" /></FormField>
          <FormField :label="t('quizzes.quiz.mode')">
            <SegmentedControl v-model="form.mode" :options="modeOptions" :disabled="!canManage" />
          </FormField>
          <template v-if="form.mode === 'random'">
            <div class="grid grid-cols-1 gap-3 sm:grid-cols-[1fr_160px]">
              <FormField :label="t('quizzes.quiz.topics')" :hint="t('quizzes.quiz.topicsHint')" :error="errors.topic_ids">
                <MultiSelect v-model="form.topic_ids" :options="topicOptions" :disabled="!canManage" :placeholder="t('quizzes.quiz.pickTopics')" />
              </FormField>
              <FormField :label="t('quizzes.quiz.count')" :error="errors.question_count">
                <NumberInput :model-value="form.question_count" :min="1" :max="50" :disabled="!canManage" @update:model-value="(value) => (form.question_count = value ?? 10)" />
              </FormField>
            </div>
          </template>
          <FormField :label="form.mode === 'fixed' ? t('quizzes.quiz.list') : t('quizzes.quiz.listRandom')" :hint="form.mode === 'fixed' ? t('quizzes.quiz.listHint') : t('quizzes.quiz.listRandomHint')">
            <ol v-if="listed.length" class="flex flex-col divide-y divide-line rounded-lg border border-line" data-testid="quiz-list">
              <li v-for="(row, index) in listed" :key="row.id" class="flex items-center gap-2 px-3 py-2 text-sm">
                <span class="w-6 shrink-0 text-right text-xs text-muted">{{ index + 1 }}.</span>
                <span class="min-w-0 flex-1">
                  <span class="block truncate text-fg">{{ row.text }}</span>
                  <span class="block truncate text-xs text-muted">{{ t(`quizzes.kind.${row.kind}`) }}<template v-if="row.topic"> · {{ row.topic.name }}</template></span>
                </span>
                <template v-if="canManage">
                  <UiButton size="sm" variant="ghost" :icon="ArrowUp" :aria-label="t('quizzes.editor.up')" :disabled="index === 0" @click="form.question_ids = moved(form.question_ids, index, -1)" />
                  <UiButton size="sm" variant="ghost" :icon="ArrowDown" :aria-label="t('quizzes.editor.down')" :disabled="index === listed.length - 1" @click="form.question_ids = moved(form.question_ids, index, 1)" />
                  <UiButton size="sm" variant="ghost" :icon="Trash2" :aria-label="t('quizzes.editor.remove')" @click="form.question_ids = form.question_ids.filter((id) => id !== row.id)" />
                </template>
              </li>
            </ol>
            <p v-else class="rounded-lg border border-dashed border-line px-3 py-3 text-sm text-muted">{{ t("quizzes.quiz.listEmpty") }}</p>
            <UiButton v-if="canManage" size="sm" variant="ghost" :icon="Plus" class="mt-2 self-start" @click="picking = true">{{ t("quizzes.quiz.addQuestions") }}</UiButton>
          </FormField>
        </div>
      </PageSection>

      <div class="flex flex-col gap-4">
        <PageSection variant="card" :title="t('quizzes.quiz.rules')">
          <div class="flex flex-col gap-3">
            <ToggleSwitch v-model="form.shuffle_questions" :disabled="!canManage" :label="t('quizzes.quiz.shuffleQuestions')" />
            <ToggleSwitch v-model="form.shuffle_options" :disabled="!canManage" :label="t('quizzes.quiz.shuffleOptions')" :description="t('quizzes.quiz.shuffleOptionsHint')" />
            <ToggleSwitch v-model="form.partial_credit" :disabled="!canManage" :label="t('quizzes.quiz.partial')" :description="t('quizzes.quiz.partialHint')" />
            <FormField :label="t('quizzes.quiz.passMark')" :error="errors.pass_percent">
              <NumberInput :model-value="form.pass_percent" :min="1" :max="100" suffix="%" :disabled="!canManage" @update:model-value="(value) => (form.pass_percent = value ?? 70)" />
            </FormField>
            <ToggleSwitch v-model="form.limited" :disabled="!canManage" :label="t('quizzes.quiz.timeLimit')" />
            <FormField v-if="form.limited" :label="t('quizzes.quiz.minutes')" :error="errors.time_limit_seconds">
              <NumberInput :model-value="form.minutes" :min="1" :max="240" :suffix="t('quizzes.quiz.minuteUnit')" :disabled="!canManage" @update:model-value="(value) => (form.minutes = value ?? 10)" />
            </FormField>
            <ToggleSwitch v-model="form.capped" :disabled="!canManage" :label="t('quizzes.quiz.capAttempts')" />
            <FormField v-if="form.capped" :label="t('quizzes.quiz.maxAttempts')" :error="errors.max_attempts">
              <NumberInput :model-value="form.max_attempts" :min="1" :max="20" :disabled="!canManage" @update:model-value="(value) => (form.max_attempts = value ?? 3)" />
            </FormField>
            <FormField :label="t('quizzes.quiz.wait')" :hint="t('quizzes.quiz.waitHint')" :error="errors.retry_after_minutes">
              <NumberInput :model-value="form.retry_after_minutes" :min="0" :max="43200" :suffix="t('quizzes.quiz.minuteUnit')" :disabled="!canManage" @update:model-value="(value) => (form.retry_after_minutes = value ?? 0)" />
            </FormField>
            <FormField :label="t('quizzes.quiz.showAnswers')">
              <SelectBox :model-value="form.show_answers" :options="showOptions" :disabled="!canManage" @update:model-value="(value) => (form.show_answers = (value as ShowAnswers) ?? 'after')" />
            </FormField>
          </div>
        </PageSection>
        <PageSection variant="card" :title="t('quizzes.quiz.audience')">
          <div class="flex flex-col gap-3">
            <ToggleSwitch v-model="form.audience_all" :disabled="!canManage" :label="t('quizzes.quiz.everyone')" :description="t('quizzes.quiz.everyoneHint')" />
            <FormField v-if="!form.audience_all" :label="t('quizzes.quiz.positions')">
              <PositionPicker v-model="form.position_ids" multiple :disabled="!canManage" />
            </FormField>
            <p class="text-xs text-muted">{{ t("quizzes.quiz.usedIn", { courses: quiz.data.value.in_courses, checks: quiz.data.value.in_checks }) }}</p>
          </div>
        </PageSection>
        <div v-if="canManage" class="flex flex-wrap gap-2">
          <UiButton variant="primary" :icon="Save" :loading="saving" data-testid="quiz-save" @click="save">{{ t("common.save") }}</UiButton>
          <UiButton variant="ghost" :icon="Undo2" @click="quiz.refetch()">{{ t("quizzes.quiz.undo") }}</UiButton>
          <UiButton v-if="!quiz.data.value.attempts && !quiz.data.value.in_courses && !quiz.data.value.in_checks" variant="ghost" :icon="Trash2" class="ml-auto text-danger" @click="remove">{{ t("quizzes.quiz.delete") }}</UiButton>
        </div>
      </div>
    </div>

    <!-- Results -->
    <div v-else-if="tab === 'results'" class="flex flex-col gap-4">
      <KpiStrip :items="kpis" :loading="results.isPending.value" :columns="4" phone="grid" />
      <div class="grid gap-4 lg:grid-cols-2">
        <PageSection variant="card" :title="t('quizzes.results.distribution')">
          <BarChart v-if="results.data.value?.summary.attempts" :categories="distribution.categories" :series="distribution.series" height="220px" integer :x-format="'none'" />
          <p v-else class="py-6 text-center text-sm text-muted">{{ t("quizzes.results.none") }}</p>
        </PageSection>
        <PageSection variant="card" :title="t('quizzes.results.hardest')" :description="t('quizzes.results.hardestHint')" flush>
          <ul v-if="results.data.value?.hardest.length" class="divide-y divide-line">
            <li v-for="row in results.data.value.hardest" :key="row.id" class="flex items-center gap-3 px-4 py-2.5 text-sm">
              <span class="min-w-0 flex-1 truncate text-fg">{{ row.text }}</span>
              <span class="shrink-0 text-xs text-muted">{{ t(`quizzes.kind.${row.kind}`) }}</span>
              <span class="w-14 shrink-0 text-right font-semibold tabular-nums" :class="row.percent < 50 ? 'text-danger' : 'text-fg'">{{ row.percent }} %</span>
            </li>
          </ul>
          <p v-else class="px-4 py-6 text-center text-sm text-muted">{{ t("quizzes.results.none") }}</p>
        </PageSection>
      </div>
      <DataTable
        :state="table"
        :columns="resultColumns"
        :rows="results.data.value?.attempts"
        :total="results.data.value?.attempts.length"
        row-key="id"
        :loading="results.isPending.value"
        :fetching="results.isFetching.value"
        :error="results.error.value"
        :retry="() => results.refetch()"
        clickable
        csv-name="quiz-results"
        :empty-title="t('quizzes.results.emptyTitle')"
        :empty-description="t('quizzes.results.emptyBody')"
        @row-click="review"
      >
        <template #cell-member="{ row }">
          <PersonCell :person="{ id: row.member.id, name: row.member.name, photo_url: row.member.photo_url }" :subtitle="row.member.position ?? undefined" />
        </template>
        <template #cell-percent="{ row }">{{ row.percent === null ? "—" : `${row.percent} %` }}</template>
        <template #cell-passed="{ row }">
          <StatusPill v-if="row.state === 'in_progress'" size="sm" tone="info" :label="t('quizzes.attemptState.in_progress')" />
          <StatusPill v-else size="sm" :tone="row.passed ? 'success' : 'danger'" :label="row.passed ? t('quizzes.results.passed') : t('quizzes.results.failed')" />
          <StatusPill v-if="row.check" size="sm" variant="plain" tone="neutral" :label="t('quizzes.results.check')" />
          <StatusPill v-if="row.reset" size="sm" variant="plain" tone="neutral" :label="t('quizzes.results.wasReset')" />
        </template>
        <template #cell-actions="{ row }">
          <UiButton v-if="!row.reset && row.state !== 'in_progress'" size="sm" variant="ghost" :icon="RotateCcw" @click.stop="reset(row)">{{ t("quizzes.results.reset") }}</UiButton>
        </template>
      </DataTable>
    </div>

    <!-- Preview -->
    <div v-else-if="tab === 'preview'" class="flex flex-col gap-4">
      <div class="flex flex-wrap items-center gap-2">
        <p class="flex-1 text-sm text-muted">{{ t("quizzes.preview.description") }}</p>
        <UiButton variant="secondary" :icon="Eye" :loading="previewing" @click="draw">{{ t("quizzes.preview.again") }}</UiButton>
      </div>
      <div v-if="previewing && !drawn" class="grid gap-3"><SkeletonBlock v-for="n in 3" :key="n" height="120px" radius="12px" /></div>
      <div v-else-if="drawn && !drawn.length" class="ui-card"><EmptyState :icon="Eye" :title="t('quizzes.preview.emptyTitle')" :description="t('quizzes.preview.emptyBody')" /></div>
      <ol v-else-if="drawn" class="grid gap-3 lg:grid-cols-2">
        <li v-for="(item, index) in drawn" :key="`${item.question.id}-${index}`" class="ui-card p-4">
          <p class="mb-2 text-xs font-semibold text-muted">{{ t("quizzes.preview.number", { n: index + 1, points: item.question.points }) }}</p>
          <QuestionPreview :question="item.question" :right="item.right_answer" :explanation="item.explanation" compact />
        </li>
      </ol>
    </div>

    <UiDialog v-model:open="picking" :title="t('quizzes.quiz.addQuestions')" :description="t('quizzes.quiz.addQuestionsBody')" size="lg">
      <TextInput v-model="pickSearch" :debounce="250" type="search" clearable :placeholder="t('quizzes.bank.search')" />
      <ul class="mt-3 max-h-[50vh] divide-y divide-line overflow-y-auto rounded-lg border border-line">
        <li v-for="row in pickable.data.value?.results ?? []" :key="row.id" class="flex items-center gap-3 px-3 py-2 text-sm">
          <span class="min-w-0 flex-1">
            <span class="block truncate text-fg">{{ row.text }}</span>
            <span class="block truncate text-xs text-muted">{{ t(`quizzes.kind.${row.kind}`) }}<template v-if="row.topic"> · {{ row.topic.name }}</template></span>
          </span>
          <UiButton size="sm" :variant="form.question_ids.includes(row.id) ? 'ghost' : 'secondary'" :disabled="form.question_ids.includes(row.id)" @click="addToList(row)">
            {{ form.question_ids.includes(row.id) ? t("quizzes.quiz.added") : t("quizzes.quiz.add") }}
          </UiButton>
        </li>
      </ul>
      <template #footer>
        <UiButton variant="primary" @click="picking = false">{{ t("quizzes.quiz.doneAdding") }}</UiButton>
      </template>
    </UiDialog>

    <AttemptDrawer v-model:open="reviewOpen" :attempt-id="reviewing" />
  </div>
</template>
