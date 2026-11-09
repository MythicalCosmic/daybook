<script setup lang="ts">
/**
 * The question bank (Savollar bazasi): every question with its kind, topic, difficulty, how often
 * it was answered right, its state and where it came from. Filters by topic, kind, difficulty,
 * state and source; several at once into use or the archive; the editor per kind; "Write
 * questions from…" a page or a lesson, whose drafts wait here (`?job=`) for review.
 * `?new=1` opens the editor (the command palette).
 */
import { Archive, CheckCheck, Library, PenLine, WandSparkles } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import BulkActionBar from "@/components/BulkActionBar.vue";
import DataTable from "@/components/DataTable.vue";
import EmptyState from "@/components/EmptyState.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import PageHeader from "@/components/PageHeader.vue";
import SelectBox from "@/components/SelectBox.vue";
import StatusPill from "@/components/StatusPill.vue";
import type { TableColumn } from "@/components/table";
import TextInput from "@/components/TextInput.vue";
import UiBadge from "@/components/UiBadge.vue";
import UiButton from "@/components/UiButton.vue";
import { useDataTable } from "@/components/useDataTable";
import { toast } from "@/components/useToast";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useCompanyStore } from "@/stores/company";

import { quizzesApi, useDraft, useQuestions, useRefresh, useTopics } from "../api";
import DraftDialog from "../components/DraftDialog.vue";
import QuestionEditor from "../components/QuestionEditor.vue";
import { DIFFICULTIES, KINDS } from "../lib";
import type { DraftJob, Question, QuestionState } from "../types";

const { t } = useI18n();
const company = useCompanyStore();
const refresh = useRefresh();
const topics = useTopics();

const search = useRouteState("q", rs.string(""));
const topic = useRouteState("topic", rs.string(""));
const kind = useRouteState("kind", rs.string(""));
const difficulty = useRouteState("difficulty", rs.string(""));
const state = useRouteState("state", rs.string(""));
const source = useRouteState("source", rs.string(""));
const job = useRouteState("job", rs.string(""));
const creating = useRouteState("new", rs.boolean(false));

const table = useDataTable({ id: "quizzes.questions", pageSize: 50 });
const params = computed(() => ({
  ...table.params.value,
  q: search.value || undefined,
  topic: topic.value || undefined,
  kind: kind.value || undefined,
  difficulty: difficulty.value || undefined,
  state: state.value || undefined,
  source: source.value || undefined,
  draft_job: job.value || undefined,
}));
table.resetPageOn(() => [search.value, topic.value, kind.value, difficulty.value, state.value, source.value, job.value]);
const questions = useQuestions(params);
const filtered = computed(() => !!(search.value || topic.value || kind.value || difficulty.value || state.value || source.value || job.value));

// A drafting job: its progress, then its drafts.
const jobId = computed(() => (job.value ? Number(job.value) : null));
const draftJob = useDraft(jobId, () => {
  const found = jobDetail.value;
  return found && (found.state === "queued" || found.state === "running") ? 2000 : false;
});
const jobDetail = computed(() => draftJob.data.value ?? null);
watch(
  () => jobDetail.value?.state,
  (now, before) => {
    if ((before === "queued" || before === "running") && (now === "done" || now === "failed")) refresh();
  },
);

const columns = computed<TableColumn<Question>[]>(() => [
  { id: "text", header: t("quizzes.col.question"), minWidth: 280 },
  { id: "kind", header: t("quizzes.col.kind"), width: 150, value: (row) => t(`quizzes.kind.${row.kind}`) },
  { id: "topic", header: t("quizzes.col.topic"), width: 160, value: (row) => row.topic?.name ?? "" },
  { id: "difficulty", header: t("quizzes.col.difficulty"), width: 110, value: (row) => t(`quizzes.difficulty.${row.difficulty}`) },
  { id: "correct_percent", header: t("quizzes.col.right"), width: 110, numeric: true, hint: t("quizzes.col.rightHint") },
  { id: "state", header: t("quizzes.col.state"), width: 120 },
]);

const kindOptions = computed(() => KINDS.map((value) => ({ value, label: t(`quizzes.kind.${value}`) })));
const difficultyOptions = computed(() => DIFFICULTIES.map((value) => ({ value, label: t(`quizzes.difficulty.${value}`) })));
const stateOptions = computed(() => (["draft", "active", "archived"] as const).map((value) => ({ value, label: t(`quizzes.state.${value}`) })));
const sourceOptions = computed(() => (["manual", "ai", "rules", "copy"] as const).map((value) => ({ value, label: t(`quizzes.source.${value}`) })));
const topicOptions = computed(() => (topics.data.value ?? []).map((row) => ({ value: String(row.id), label: row.name })));
const STATE_TONES: Record<QuestionState, "neutral" | "success" | "warning"> = { draft: "warning", active: "success", archived: "neutral" };

// The editor and the drafting dialog.
const editing = ref<Question | null>(null);
const editorOpen = ref(false);
watch(
  creating,
  (value) => {
    if (value) {
      editing.value = null;
      editorOpen.value = true;
    }
  },
  { immediate: true },
);
watch(editorOpen, (value) => {
  if (!value) creating.value = false;
});
function edit(row: Question): void {
  editing.value = row;
  editorOpen.value = true;
}
const drafting = ref(false);
function started(found: DraftJob): void {
  toast.success(t("quizzes.drafts.started"));
  job.value = String(found.id);
  state.value = "";
}

// Several at once.
const picked = computed(() => table.selectedIds.value.map(Number));
const working = ref(false);
async function bulk(target: QuestionState): Promise<void> {
  working.value = true;
  try {
    const { changed } = await quizzesApi.bulk(company.currentId ?? 0, picked.value, target);
    toast.success(t("quizzes.bank.changed", { n: changed }, changed));
    table.clearSelection();
    refresh();
  } finally {
    working.value = false;
  }
}
</script>

<template>
  <div>
    <PageHeader :title="t('quizzes.nav.questions')" :description="t('quizzes.bank.description')">
      <template #actions>
        <UiButton variant="secondary" :icon="WandSparkles" data-testid="write-from" @click="drafting = true">{{ t("quizzes.drafts.open") }}</UiButton>
        <UiButton variant="primary" :icon="PenLine" @click="creating = true">{{ t("quizzes.bank.new") }}</UiButton>
      </template>
    </PageHeader>

    <InlineAlert v-if="jobDetail" class="mb-4" :tone="jobDetail.state === 'failed' ? 'danger' : jobDetail.state === 'done' ? 'success' : 'info'" data-testid="draft-job">
      <span v-if="jobDetail.state === 'queued' || jobDetail.state === 'running'">{{ t("quizzes.drafts.working", { source: jobDetail.page?.title ?? jobDetail.lesson?.title ?? "" }) }}</span>
      <span v-else-if="jobDetail.state === 'done'">
        {{ t("quizzes.drafts.done", { n: jobDetail.made, source: jobDetail.page?.title ?? jobDetail.lesson?.title ?? "" }, jobDetail.made) }}
        <template v-if="jobDetail.dropped"> {{ t("quizzes.drafts.dropped", { n: jobDetail.dropped }, jobDetail.dropped) }}</template>
        {{ jobDetail.engine === "claude" ? t("quizzes.drafts.byClaude") : t("quizzes.drafts.byRules") }}
      </span>
      <span v-else>{{ jobDetail.error || t("quizzes.drafts.failed") }}</span>
      <UiButton size="sm" variant="ghost" class="ml-2" @click="job = ''">{{ t("quizzes.drafts.showAll") }}</UiButton>
    </InlineAlert>

    <div v-if="questions.data.value && !questions.data.value.count && !filtered" class="ui-card">
      <EmptyState :icon="Library" :title="t('quizzes.bank.emptyTitle')" :description="t('quizzes.bank.emptyBody')">
        <UiButton variant="primary" :icon="PenLine" @click="creating = true">{{ t("quizzes.bank.new") }}</UiButton>
        <UiButton variant="secondary" :icon="WandSparkles" @click="drafting = true">{{ t("quizzes.drafts.open") }}</UiButton>
      </EmptyState>
    </div>

    <DataTable
      v-else
      :state="table"
      :columns="columns"
      :rows="questions.data.value?.results"
      :total="questions.data.value?.count"
      row-key="id"
      :loading="questions.isPending.value"
      :fetching="questions.isFetching.value"
      :error="questions.error.value"
      :retry="() => questions.refetch()"
      selectable
      clickable
      :filtered="filtered"
      csv-name="questions"
      @row-click="edit"
      @clear-filters="
        search = '';
        topic = '';
        kind = '';
        difficulty = '';
        state = '';
        source = '';
        job = '';
      "
    >
      <template #toolbar>
        <div class="flex flex-wrap items-center gap-2">
          <TextInput v-model="search" :debounce="300" type="search" size="sm" class="w-full sm:w-60" :placeholder="t('quizzes.bank.search')" clearable />
          <SelectBox v-model="topic" size="sm" class="w-44" :options="topicOptions" clearable :placeholder="t('quizzes.bank.anyTopic')" />
          <SelectBox v-model="kind" size="sm" class="w-44" :options="kindOptions" clearable :placeholder="t('quizzes.bank.anyKind')" />
          <SelectBox v-model="difficulty" size="sm" class="w-32" :options="difficultyOptions" clearable :placeholder="t('quizzes.bank.anyDifficulty')" />
          <SelectBox v-model="state" size="sm" class="w-32" :options="stateOptions" clearable :placeholder="t('quizzes.bank.anyState')" />
          <SelectBox v-model="source" size="sm" class="w-40" :options="sourceOptions" clearable :placeholder="t('quizzes.bank.anySource')" />
        </div>
      </template>
      <template #cell-text="{ row }">
        <span class="flex min-w-0 items-center gap-2">
          <img v-if="row.image" :src="row.image.url" alt="" class="size-8 shrink-0 rounded-md object-cover" loading="lazy" />
          <span class="min-w-0">
            <span class="block truncate font-medium text-fg">{{ row.text }}</span>
            <span v-if="row.source !== 'manual' || row.page || row.lesson" class="block truncate text-xs text-muted">
              {{ t(`quizzes.source.${row.source}`) }}<template v-if="row.page ?? row.lesson"> · {{ (row.page ?? row.lesson)?.title }}</template>
            </span>
          </span>
        </span>
      </template>
      <template #cell-correct_percent="{ row }">
        <span v-if="row.correct_percent !== null" :class="row.correct_percent < 50 ? 'text-danger' : 'text-fg'">{{ row.correct_percent }} %</span>
        <span v-else class="text-subtle">—</span>
        <span v-if="row.answered" class="ml-1 text-xs text-muted">({{ row.answered }})</span>
      </template>
      <template #cell-state="{ row }">
        <StatusPill size="sm" :tone="STATE_TONES[row.state]" :label="t(`quizzes.state.${row.state}`)" />
        <UiBadge v-if="row.quizzes" size="sm" class="ml-1" :title="t('quizzes.bank.inQuizzes', { n: row.quizzes }, row.quizzes)">{{ row.quizzes }}</UiBadge>
      </template>
    </DataTable>

    <div v-if="picked.length" class="h-16" aria-hidden="true" />
    <BulkActionBar :count="picked.length" @clear="table.clearSelection()">
      <UiButton size="sm" variant="ghost" :icon="CheckCheck" :loading="working" data-testid="bulk-activate" @click="bulk('active')">{{ t("quizzes.bank.activate") }}</UiButton>
      <UiButton size="sm" variant="ghost" :icon="Archive" :loading="working" @click="bulk('archived')">{{ t("quizzes.bank.archive") }}</UiButton>
    </BulkActionBar>

    <QuestionEditor v-model:open="editorOpen" :question="editing" />
    <DraftDialog v-model:open="drafting" @created="started" />
  </div>
</template>
