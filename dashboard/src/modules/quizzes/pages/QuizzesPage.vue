<script setup lang="ts">
/**
 * Quizzes (Testlar): each with its questions (a fixed list, or drawn at random from topics), the
 * pass mark, how many took it and how many of them passed. A new quiz starts as a draft with a
 * name and a kind; its page has the settings, a learner's preview and the results. `?new=1` opens
 * the new quiz form (the command palette).
 */
import { ClipboardCheck, Plus, Shuffle } from "@lucide/vue";
import { computed, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";

import { isApiError } from "@/api/http";
import DataTable from "@/components/DataTable.vue";
import EmptyState from "@/components/EmptyState.vue";
import FormField from "@/components/FormField.vue";
import PageHeader from "@/components/PageHeader.vue";
import ProgressBar from "@/components/ProgressBar.vue";
import RadioCards from "@/components/RadioCards.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import StatusPill from "@/components/StatusPill.vue";
import type { TableColumn } from "@/components/table";
import TextInput from "@/components/TextInput.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { useDataTable } from "@/components/useDataTable";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useCompanyStore } from "@/stores/company";

import { quizzesApi, useQuizzes, useRefresh } from "../api";
import type { QuizMode, QuizRow, QuizStatus } from "../types";

const { t } = useI18n();
const company = useCompanyStore();
const router = useRouter();
const refresh = useRefresh();
const canManage = computed(() => company.can("learning.manage"));

const status = useRouteState("status", rs.string(""));
const creating = useRouteState("new", rs.boolean(false));
const quizzes = useQuizzes(computed(() => ({ status: status.value || undefined })));
const table = useDataTable({ id: "quizzes.list", pageSize: 100 });

const STATUS_TONES: Record<QuizStatus, "success" | "warning" | "neutral"> = { published: "success", draft: "warning", archived: "neutral" };
const columns = computed<TableColumn<QuizRow>[]>(() => [
  { id: "title", header: t("quizzes.col.quiz"), minWidth: 240 },
  { id: "questions", header: t("quizzes.col.questions"), width: 130, numeric: true },
  { id: "pass_percent", header: t("quizzes.col.passMark"), width: 120, numeric: true, format: (value) => `${String(value)} %` },
  { id: "people", header: t("quizzes.col.people"), width: 110, numeric: true },
  { id: "pass_rate", header: t("quizzes.col.passRate"), width: 180 },
  { id: "status", header: t("quizzes.col.status"), width: 130 },
]);
const statusOptions = computed(() => [
  { value: "", label: t("quizzes.list.all") },
  { value: "published", label: t("quizzes.status.published") },
  { value: "draft", label: t("quizzes.status.draft") },
  { value: "archived", label: t("quizzes.status.archived") },
]);

function open(row: QuizRow): void {
  void router.push(`/c/${company.currentId}/learning/quizzes/${row.id}`);
}

// A new quiz -------------------------------------------------------------------------------------

const form = reactive({ title: "", mode: "random" as QuizMode });
const error = ref<string | undefined>(undefined);
const saving = ref(false);
watch(creating, (value) => {
  if (value) {
    form.title = "";
    form.mode = "random";
    error.value = undefined;
  }
});
const modeOptions = computed(() => [
  { value: "random" as QuizMode, label: t("quizzes.mode.random"), description: t("quizzes.modeHint.random"), icon: Shuffle },
  { value: "fixed" as QuizMode, label: t("quizzes.mode.fixed"), description: t("quizzes.modeHint.fixed"), icon: ClipboardCheck },
]);
async function create(): Promise<void> {
  if (!form.title.trim()) {
    error.value = t("quizzes.quiz.errTitle");
    return;
  }
  saving.value = true;
  try {
    const made = await quizzesApi.createQuiz(company.currentId ?? 0, { title: form.title.trim(), mode: form.mode });
    refresh();
    creating.value = false;
    void router.push(`/c/${company.currentId}/learning/quizzes/${made.id}`);
  } catch (failure) {
    if (isApiError(failure)) error.value = failure.detail ?? Object.values(failure.fieldErrors)[0]?.[0];
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <div>
    <PageHeader :title="t('quizzes.nav.quizzes')" :description="t('quizzes.list.description')">
      <template #actions>
        <UiButton v-if="canManage" variant="primary" :icon="Plus" @click="creating = true">{{ t("quizzes.list.new") }}</UiButton>
      </template>
    </PageHeader>

    <div v-if="quizzes.data.value && !quizzes.data.value.length && !status" class="ui-card">
      <EmptyState :icon="ClipboardCheck" :title="t('quizzes.list.emptyTitle')" :description="t('quizzes.list.emptyBody')">
        <UiButton v-if="canManage" variant="primary" :icon="Plus" @click="creating = true">{{ t("quizzes.list.new") }}</UiButton>
      </EmptyState>
    </div>
    <DataTable
      v-else
      :state="table"
      :columns="columns"
      :rows="quizzes.data.value"
      :total="quizzes.data.value?.length"
      row-key="id"
      :loading="quizzes.isPending.value"
      :fetching="quizzes.isFetching.value"
      :error="quizzes.error.value"
      :retry="() => quizzes.refetch()"
      clickable
      :filtered="!!status"
      hide-pagination
      csv-name="quizzes"
      @row-click="open"
      @clear-filters="status = ''"
    >
      <template #toolbar>
        <SegmentedControl v-model="status" size="sm" :options="statusOptions" />
      </template>
      <template #cell-title="{ row }">
        <span class="flex min-w-0 items-center gap-2">
          <span v-if="row.emoji" class="text-lg leading-none" aria-hidden="true">{{ row.emoji }}</span>
          <span class="min-w-0">
            <span class="block truncate font-medium text-fg">{{ row.title }}</span>
            <span class="block truncate text-xs text-muted">
              {{ t(`quizzes.mode.${row.mode}`) }}<template v-if="row.topics.length"> · {{ row.topics.map((topic) => topic.name).join(", ") }}</template>
            </span>
          </span>
        </span>
      </template>
      <template #cell-pass_rate="{ row }">
        <div v-if="row.pass_rate !== null" class="flex items-center gap-2">
          <ProgressBar :value="row.pass_rate" :max="100" size="sm" tone="auto" class="w-20" />
          <span class="text-sm tabular-nums text-fg">{{ row.pass_rate }} %</span>
        </div>
        <span v-else class="text-subtle">—</span>
      </template>
      <template #cell-status="{ row }">
        <StatusPill size="sm" :tone="STATUS_TONES[row.status]" :label="t(`quizzes.status.${row.status}`)" />
      </template>
    </DataTable>

    <UiDialog v-model:open="creating" :title="t('quizzes.list.new')" :description="t('quizzes.list.newBody')" size="md">
      <div class="flex flex-col gap-4">
        <FormField :label="t('quizzes.quiz.name')" :error="error" required>
          <TextInput v-model="form.title" :maxlength="200" autofocus :placeholder="t('quizzes.quiz.namePlaceholder')" />
        </FormField>
        <FormField :label="t('quizzes.quiz.mode')">
          <RadioCards v-model="form.mode" :options="modeOptions" :columns="2" />
        </FormField>
      </div>
      <template #footer>
        <UiButton variant="ghost" @click="creating = false">{{ t("common.cancel") }}</UiButton>
        <UiButton variant="primary" :loading="saving" @click="create">{{ t("quizzes.list.create") }}</UiButton>
      </template>
    </UiDialog>
  </div>
</template>
