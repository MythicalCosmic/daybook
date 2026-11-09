<script setup lang="ts">
/**
 * "Write questions from…": a knowledge base page or a lesson, how many questions (1–15), of
 * which kinds, how hard, for which topic. The tutor writes them as drafts (Claude when it may
 * run, else the rules: numbers, steps and terms of the text); they wait in the bank for review.
 */
import { FileText, PlayCircle, WandSparkles } from "@lucide/vue";
import { useQuery } from "@tanstack/vue-query";
import { computed, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { http, isApiError, ownerPath } from "@/api/http";
import FormField from "@/components/FormField.vue";
import MultiSelect from "@/components/MultiSelect.vue";
import NumberInput from "@/components/NumberInput.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SelectBox from "@/components/SelectBox.vue";
import TextInput from "@/components/TextInput.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { useCompanyId } from "@/stores/company";

import { quizKeys, quizzesApi, useTopics } from "../api";
import { DIFFICULTIES, KINDS } from "../lib";
import type { DraftJob, Paginated, QuestionKind } from "../types";

const open = defineModel<boolean>("open", { default: false });
const emit = defineEmits<{ created: [job: DraftJob] }>();

const { t } = useI18n();
const cid = useCompanyId();
const topics = useTopics();

const form = reactive({
  source: "page" as "page" | "lesson",
  q: "",
  picked: null as { id: number; title: string } | null,
  count: 5,
  kinds: [] as QuestionKind[],
  difficulty: "" as "" | "easy" | "medium" | "hard",
  topic_id: null as number | null,
  rulesOnly: false,
});
const saving = ref(false);
const failure = ref("");

watch(open, (isOpen) => {
  if (!isOpen) return;
  Object.assign(form, { q: "", picked: null, count: 5, kinds: [], difficulty: "", topic_id: null, rulesOnly: false });
  failure.value = "";
});
watch(
  () => form.source,
  () => {
    form.picked = null;
  },
);

type Row = { id: number; title: string };
function rowsOf(found: Row[] | Paginated<Row>): Row[] {
  return Array.isArray(found) ? found : found.results;
}

const search = useQuery({
  queryKey: computed(() => quizKeys.of(cid.value, "sources", { source: form.source, q: form.q })),
  queryFn: async (): Promise<Row[]> => {
    if (form.source === "page") return rowsOf(await quizzesApi.pages(cid.value, form.q));
    try {
      return rowsOf(await http.get<Row[] | Paginated<Row>>(ownerPath(cid.value, "learning/lessons/"), { q: form.q, page_size: 20 }));
    } catch {
      return []; // no lessons here yet
    }
  },
  enabled: computed(() => open.value && cid.value > 0),
  staleTime: 15_000,
});

const kindOptions = computed(() => KINDS.map((value) => ({ value, label: t(`quizzes.kind.${value}`) })));
const difficultyOptions = computed(() => [{ value: "", label: t("quizzes.drafts.anyDifficulty") }, ...DIFFICULTIES.map((value) => ({ value, label: t(`quizzes.difficulty.${value}`) }))]);
const topicOptions = computed(() => (topics.data.value ?? []).filter((topic) => !topic.archived).map((topic) => ({ value: topic.id, label: topic.name })));

async function start(): Promise<void> {
  failure.value = "";
  if (!form.picked) {
    failure.value = t("quizzes.drafts.pickFirst");
    return;
  }
  saving.value = true;
  try {
    const job = await quizzesApi.createDraft(cid.value, {
      page_id: form.source === "page" ? form.picked.id : null,
      lesson_id: form.source === "lesson" ? form.picked.id : null,
      count: form.count,
      kinds: form.kinds,
      difficulty: form.difficulty,
      topic_id: form.topic_id,
      engine: form.rulesOnly ? "rules" : "auto",
    });
    emit("created", job);
    open.value = false;
  } catch (error) {
    if (isApiError(error)) failure.value = error.detail || Object.values(error.fieldErrors)[0]?.[0] || t("quizzes.drafts.failed");
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <UiDialog v-model:open="open" :title="t('quizzes.drafts.title')" :description="t('quizzes.drafts.description')" size="lg">
    <div class="flex flex-col gap-4">
      <SegmentedControl
        v-model="form.source"
        :options="[
          { value: 'page', label: t('quizzes.drafts.page'), icon: FileText },
          { value: 'lesson', label: t('quizzes.drafts.lesson'), icon: PlayCircle },
        ]"
      />
      <FormField :label="form.source === 'page' ? t('quizzes.drafts.findPage') : t('quizzes.drafts.findLesson')" :error="failure || undefined">
        <TextInput v-model="form.q" :debounce="250" clearable :placeholder="t('quizzes.drafts.searchPlaceholder')" />
        <ul class="mt-2 max-h-48 overflow-y-auto rounded-lg border border-line" data-testid="draft-sources">
          <li v-for="row in search.data.value ?? []" :key="row.id">
            <button
              type="button"
              class="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-surface-2"
              :class="form.picked?.id === row.id ? 'bg-accent-soft text-accent-fg' : 'text-fg'"
              @click="form.picked = row"
            >
              <component :is="form.source === 'page' ? FileText : PlayCircle" :size="14" class="shrink-0 text-muted" aria-hidden="true" />
              <span class="truncate">{{ row.title }}</span>
            </button>
          </li>
          <li v-if="!search.isPending.value && !(search.data.value ?? []).length" class="px-3 py-3 text-sm text-muted">{{ t("quizzes.drafts.nothingFound") }}</li>
        </ul>
      </FormField>
      <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <FormField :label="t('quizzes.drafts.count')">
          <NumberInput :model-value="form.count" :min="1" :max="15" @update:model-value="(value) => (form.count = value ?? 5)" />
        </FormField>
        <FormField :label="t('quizzes.drafts.difficulty')">
          <SelectBox :model-value="form.difficulty" :options="difficultyOptions" @update:model-value="(value) => (form.difficulty = (value as typeof form.difficulty) ?? '')" />
        </FormField>
        <FormField :label="t('quizzes.drafts.kinds')" :hint="t('quizzes.drafts.kindsHint')" optional>
          <MultiSelect v-model="form.kinds" :options="kindOptions" :placeholder="t('quizzes.drafts.anyKind')" />
        </FormField>
        <FormField :label="t('quizzes.editor.topic')" :hint="t('quizzes.drafts.topicHint')" optional>
          <SelectBox v-model="form.topic_id" :options="topicOptions" clearable />
        </FormField>
      </div>
      <ToggleSwitch v-model="form.rulesOnly" :label="t('quizzes.drafts.rulesOnly')" :description="t('quizzes.drafts.rulesOnlyHint')" />
    </div>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="primary" :icon="WandSparkles" :loading="saving" :disabled="!form.picked" data-testid="draft-start" @click="start">{{ t("quizzes.drafts.start") }}</UiButton>
    </template>
  </UiDialog>
</template>
