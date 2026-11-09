<script setup lang="ts">
/**
 * Writing or changing one question of the bank: its kind, the text, the part of its kind (the
 * options and which are right, true or false, the steps in their right order, the pairs, the
 * accepted answers, the number), the explanation shown after answering, the topic, difficulty,
 * points and a picture. The checks run as one types (the server's rules, lib.validate) and a
 * preview shows what the learner will see.
 */
import { ArrowDown, ArrowUp, ImagePlus, Plus, Trash2, X } from "@lucide/vue";
import { computed, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { isApiError } from "@/api/http";
import CheckBox from "@/components/CheckBox.vue";
import FormField from "@/components/FormField.vue";
import NumberInput from "@/components/NumberInput.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SelectBox from "@/components/SelectBox.vue";
import TextArea from "@/components/TextArea.vue";
import TextInput from "@/components/TextInput.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import UiButton from "@/components/UiButton.vue";
import UiDrawer from "@/components/UiDrawer.vue";
import { toast } from "@/components/useToast";
import { useCompanyStore } from "@/stores/company";

import { quizzesApi, useRefresh, useTopics } from "../api";
import { blankDraft, dataOf, DIFFICULTIES, draftOf, KINDS, LETTERS, LIMITS, moved, previewOf, serverProblems, validate, type Draft } from "../lib";
import type { Question, QuestionKind, QuestionState } from "../types";
import QuestionPreview from "./QuestionPreview.vue";

const open = defineModel<boolean>("open", { default: false });
const props = withDefaults(defineProps<{ question?: Question | null; kind?: QuestionKind }>(), { question: null, kind: "single" });
const emit = defineEmits<{ saved: [question: Question] }>();

const { t } = useI18n();
const company = useCompanyStore();
const refresh = useRefresh();
const topics = useTopics();

const draft = reactive<Draft>(blankDraft());
const tried = ref(false);
const saving = ref(false);
const uploading = ref(false);
const server = ref<Record<string, string>>({});
const seed = ref(1);

watch(
  () => [open.value, props.question?.id] as const,
  ([isOpen]) => {
    if (!isOpen) return;
    Object.assign(draft, props.question ? draftOf(props.question) : blankDraft(props.kind));
    tried.value = false;
    server.value = {};
    seed.value = Math.floor(Math.random() * 1_000_000) + 1;
  },
  { immediate: true },
);

const editing = computed(() => props.question !== null);
const kindLocked = computed(() => (props.question?.answered ?? 0) > 0);
const problems = computed(() => validate(draft));
const count = computed(() => Object.keys(problems.value).length);

/** A problem to show under a field: the server's, or the live check's once a save was tried. */
function problem(where: string): string | undefined {
  if (server.value[where]) return server.value[where];
  const found = problems.value[where];
  if (!found || !tried.value) return undefined;
  return t(found.key, found.values ?? {});
}

/** A seeded shuffle, so the preview doesn't reshuffle at every key. */
function seeded(): () => number {
  let state = seed.value;
  return () => {
    state = (state * 1_103_515_245 + 12_345) % 2_147_483_648;
    return state / 2_147_483_648;
  };
}
const preview = computed(() => previewOf(draft, seeded()));

const kindOptions = computed(() => KINDS.map((value) => ({ value, label: t(`quizzes.kind.${value}`), description: t(`quizzes.kindHint.${value}`) })));
const topicOptions = computed(() => (topics.data.value ?? []).filter((topic) => !topic.archived || topic.id === draft.topic_id).map((topic) => ({ value: topic.id, label: topic.name })));
const difficultyOptions = computed(() => DIFFICULTIES.map((value) => ({ value, label: t(`quizzes.difficulty.${value}`) })));
const stateOptions = computed(() => (["draft", "active", "archived"] as QuestionState[]).map((value) => ({ value, label: t(`quizzes.state.${value}`) })));
const truth = computed({
  get: () => (draft.answer ? "true" : "false"),
  set: (value: string) => {
    draft.answer = value === "true";
  },
});

function setKind(kind: QuestionKind | null): void {
  if (!kind || kindLocked.value) return;
  draft.kind = kind;
  if (kind === "single" && draft.options.filter((o) => o.correct).length !== 1) {
    draft.options = draft.options.map((o, index) => ({ ...o, correct: index === 0 }));
  }
}

function markRight(index: number, value: boolean): void {
  if (draft.kind === "single") draft.options = draft.options.map((o, at) => ({ ...o, correct: at === index }));
  else draft.options[index]!.correct = value;
}

const fileInput = ref<HTMLInputElement | null>(null);
async function upload(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = "";
  if (!file) return;
  uploading.value = true;
  try {
    draft.image = await quizzesApi.uploadImage(company.currentId ?? 0, file);
  } finally {
    uploading.value = false;
  }
}

async function save(state?: QuestionState): Promise<void> {
  tried.value = true;
  server.value = {};
  if (count.value) return;
  saving.value = true;
  const cid = company.currentId ?? 0;
  const input = {
    kind: draft.kind,
    text: draft.text.trim(),
    data: dataOf(draft),
    explanation: draft.explanation.trim(),
    topic_id: draft.topic_id,
    difficulty: draft.difficulty,
    points: draft.points,
    image_id: draft.image?.id ?? null,
    state: state ?? draft.state,
  };
  try {
    const saved = props.question ? await quizzesApi.updateQuestion(cid, props.question.id, input) : await quizzesApi.createQuestion(cid, input);
    toast.success(t("quizzes.editor.saved"));
    refresh();
    emit("saved", saved);
    open.value = false;
  } catch (error) {
    if (isApiError(error)) server.value = serverProblems(error.fieldErrors);
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <UiDrawer v-model:open="open" :title="editing ? t('quizzes.editor.editTitle') : t('quizzes.editor.newTitle')" size="xl">
    <div class="grid gap-6 p-5 lg:grid-cols-[minmax(0,1fr)_320px]">
      <div class="flex min-w-0 flex-col gap-4">
        <FormField :label="t('quizzes.editor.kind')" :hint="kindLocked ? t('quizzes.editor.kindLocked') : undefined">
          <SelectBox :model-value="draft.kind" :options="kindOptions" :disabled="kindLocked" data-testid="question-kind" @update:model-value="(value) => setKind(value as QuestionKind | null)" />
        </FormField>
        <FormField :label="draft.kind === 'true_false' ? t('quizzes.editor.statement') : t('quizzes.editor.text')" :error="problem('text')" required>
          <TextArea v-model="draft.text" :rows="3" autosize :max-rows="8" :maxlength="LIMITS.question" data-testid="question-text" />
        </FormField>

        <!-- One right answer, several right answers -->
        <FormField v-if="draft.kind === 'single' || draft.kind === 'multi'" :label="t('quizzes.editor.options')" :hint="draft.kind === 'single' ? t('quizzes.editor.oneRightHint') : t('quizzes.editor.someRightHint')" :error="problem('options')">
          <ul class="flex flex-col gap-2">
            <li v-for="(option, index) in draft.options" :key="index" class="flex items-start gap-2">
              <CheckBox :model-value="option.correct" :aria-label="t('quizzes.editor.right')" class="mt-2" @update:model-value="(value) => markRight(index, value)" />
              <span class="mt-2 w-4 shrink-0 text-xs font-semibold text-muted">{{ LETTERS[index] }}</span>
              <div class="min-w-0 flex-1">
                <TextInput v-model="option.text" :maxlength="LIMITS.text" :invalid="!!problem(`options.${index}.text`)" :placeholder="t('quizzes.editor.optionPlaceholder')" />
                <p v-if="problem(`options.${index}.text`)" class="mt-1 text-xs text-danger">{{ problem(`options.${index}.text`) }}</p>
              </div>
              <UiButton size="sm" variant="ghost" :icon="Trash2" :aria-label="t('quizzes.editor.remove')" :disabled="draft.options.length <= LIMITS.options[0]" @click="draft.options.splice(index, 1)" />
            </li>
          </ul>
          <UiButton v-if="draft.options.length < LIMITS.options[1]" size="sm" variant="ghost" :icon="Plus" class="mt-2 self-start" @click="draft.options.push({ text: '', correct: false })">{{ t("quizzes.editor.addOption") }}</UiButton>
        </FormField>

        <!-- True or false -->
        <FormField v-else-if="draft.kind === 'true_false'" :label="t('quizzes.editor.truth')">
          <SegmentedControl
            v-model="truth"
            :options="[
              { value: 'true', label: t('quizzes.preview.true') },
              { value: 'false', label: t('quizzes.preview.false') },
            ]"
          />
        </FormField>

        <!-- Steps in order -->
        <FormField v-else-if="draft.kind === 'order'" :label="t('quizzes.editor.steps')" :hint="t('quizzes.editor.stepsHint')" :error="problem('items')">
          <ol class="flex flex-col gap-2">
            <li v-for="(item, index) in draft.items" :key="index" class="flex items-start gap-2">
              <span class="mt-2 w-5 shrink-0 text-right text-xs font-semibold text-muted">{{ index + 1 }}.</span>
              <div class="min-w-0 flex-1">
                <TextInput v-model="item.text" :maxlength="LIMITS.text" :invalid="!!problem(`items.${index}.text`)" />
                <p v-if="problem(`items.${index}.text`)" class="mt-1 text-xs text-danger">{{ problem(`items.${index}.text`) }}</p>
              </div>
              <UiButton size="sm" variant="ghost" :icon="ArrowUp" :aria-label="t('quizzes.editor.up')" :disabled="index === 0" @click="draft.items = moved(draft.items, index, -1)" />
              <UiButton size="sm" variant="ghost" :icon="ArrowDown" :aria-label="t('quizzes.editor.down')" :disabled="index === draft.items.length - 1" @click="draft.items = moved(draft.items, index, 1)" />
              <UiButton size="sm" variant="ghost" :icon="Trash2" :aria-label="t('quizzes.editor.remove')" :disabled="draft.items.length <= LIMITS.items[0]" @click="draft.items.splice(index, 1)" />
            </li>
          </ol>
          <UiButton v-if="draft.items.length < LIMITS.items[1]" size="sm" variant="ghost" :icon="Plus" class="mt-2 self-start" @click="draft.items.push({ text: '' })">{{ t("quizzes.editor.addStep") }}</UiButton>
        </FormField>

        <!-- Pairs -->
        <FormField v-else-if="draft.kind === 'match'" :label="t('quizzes.editor.pairs')" :hint="t('quizzes.editor.pairsHint')" :error="problem('pairs')">
          <ul class="flex flex-col gap-2">
            <li v-for="(pair, index) in draft.pairs" :key="index" class="grid grid-cols-[1fr_1fr_auto] items-start gap-2">
              <div>
                <TextInput v-model="pair.left" :maxlength="LIMITS.text" :invalid="!!problem(`pairs.${index}.left`)" :placeholder="t('quizzes.editor.left')" />
                <p v-if="problem(`pairs.${index}.left`)" class="mt-1 text-xs text-danger">{{ problem(`pairs.${index}.left`) }}</p>
              </div>
              <div>
                <TextInput v-model="pair.right" :maxlength="LIMITS.text" :invalid="!!problem(`pairs.${index}.right`)" :placeholder="t('quizzes.editor.rightSide')" />
                <p v-if="problem(`pairs.${index}.right`)" class="mt-1 text-xs text-danger">{{ problem(`pairs.${index}.right`) }}</p>
              </div>
              <UiButton size="sm" variant="ghost" :icon="Trash2" :aria-label="t('quizzes.editor.remove')" :disabled="draft.pairs.length <= LIMITS.pairs[0]" @click="draft.pairs.splice(index, 1)" />
            </li>
          </ul>
          <UiButton v-if="draft.pairs.length < LIMITS.pairs[1]" size="sm" variant="ghost" :icon="Plus" class="mt-2 self-start" @click="draft.pairs.push({ left: '', right: '' })">{{ t("quizzes.editor.addPair") }}</UiButton>
        </FormField>

        <!-- Typed answer -->
        <FormField v-else-if="draft.kind === 'text'" :label="t('quizzes.editor.answers')" :hint="t('quizzes.editor.answersHint')" :error="problem('answers')">
          <ul class="flex flex-col gap-2">
            <li v-for="(_answer, index) in draft.answers" :key="index" class="flex items-start gap-2">
              <div class="min-w-0 flex-1">
                <TextInput v-model="draft.answers[index]" :maxlength="LIMITS.text" :invalid="!!problem(`answers.${index}`)" />
                <p v-if="problem(`answers.${index}`)" class="mt-1 text-xs text-danger">{{ problem(`answers.${index}`) }}</p>
              </div>
              <UiButton size="sm" variant="ghost" :icon="X" :aria-label="t('quizzes.editor.remove')" :disabled="draft.answers.length <= 1" @click="draft.answers.splice(index, 1)" />
            </li>
          </ul>
          <div class="mt-2 flex flex-wrap items-center gap-3">
            <UiButton v-if="draft.answers.length < LIMITS.answers" size="sm" variant="ghost" :icon="Plus" @click="draft.answers.push('')">{{ t("quizzes.editor.addAnswer") }}</UiButton>
            <ToggleSwitch v-model="draft.caseSensitive" size="sm" :label="t('quizzes.editor.case')" />
          </div>
        </FormField>

        <!-- A number -->
        <div v-else-if="draft.kind === 'number'" class="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <FormField :label="t('quizzes.editor.value')" :error="problem('value')" required>
            <NumberInput v-model="draft.value" :decimals="3" :steppers="false" :invalid="!!problem('value')" />
          </FormField>
          <FormField :label="t('quizzes.editor.tolerance')" :hint="t('quizzes.editor.toleranceHint')" :error="problem('tolerance')">
            <NumberInput :model-value="draft.tolerance" :min="0" :decimals="3" :steppers="false" @update:model-value="(value) => (draft.tolerance = value ?? 0)" />
          </FormField>
          <FormField :label="t('quizzes.editor.unit')" :error="problem('unit')" optional>
            <TextInput v-model="draft.unit" :maxlength="LIMITS.unit" :placeholder="t('quizzes.editor.unitPlaceholder')" />
          </FormField>
        </div>

        <FormField :label="t('quizzes.editor.explanation')" :hint="t('quizzes.editor.explanationHint')" :error="problem('explanation')" optional>
          <TextArea v-model="draft.explanation" :rows="2" autosize :max-rows="6" :maxlength="LIMITS.explanation" />
        </FormField>

        <div class="grid grid-cols-1 gap-3 sm:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_minmax(0,1fr)]">
          <FormField :label="t('quizzes.editor.topic')" optional>
            <SelectBox v-model="draft.topic_id" :options="topicOptions" clearable :placeholder="t('quizzes.editor.noTopic')" />
          </FormField>
          <FormField :label="t('quizzes.editor.difficulty')">
            <SelectBox :model-value="draft.difficulty" :options="difficultyOptions" @update:model-value="(value) => (draft.difficulty = (value as Draft['difficulty']) ?? 'medium')" />
          </FormField>
          <FormField :label="t('quizzes.editor.points')" :error="problem('points')">
            <NumberInput :model-value="draft.points" :min="LIMITS.points[0]" :max="LIMITS.points[1]" @update:model-value="(value) => (draft.points = value ?? 1)" />
          </FormField>
        </div>

        <FormField :label="t('quizzes.editor.picture')" optional>
          <div class="flex flex-wrap items-center gap-3">
            <img v-if="draft.image" :src="draft.image.url" alt="" class="h-20 w-auto rounded-lg border border-line object-contain" />
            <UiButton size="sm" variant="secondary" :icon="ImagePlus" :loading="uploading" @click="fileInput?.click()">{{ draft.image ? t("quizzes.editor.replacePicture") : t("quizzes.editor.addPicture") }}</UiButton>
            <UiButton v-if="draft.image" size="sm" variant="ghost" :icon="Trash2" @click="draft.image = null">{{ t("quizzes.editor.removePicture") }}</UiButton>
          </div>
          <input ref="fileInput" type="file" class="sr-only" accept="image/*" @change="upload" />
        </FormField>

        <FormField v-if="editing" :label="t('quizzes.editor.state')">
          <SelectBox :model-value="draft.state" :options="stateOptions" @update:model-value="(value) => (draft.state = (value as QuestionState) ?? 'active')" />
        </FormField>
      </div>

      <aside class="flex flex-col gap-2 self-start rounded-xl border border-line bg-surface-2/40 p-4 lg:sticky lg:top-4">
        <p class="text-xs font-semibold uppercase tracking-wide text-muted">{{ t("quizzes.editor.preview") }}</p>
        <QuestionPreview :question="preview" compact />
        <p class="text-xs text-muted">{{ t("quizzes.editor.previewHint") }}</p>
      </aside>
    </div>

    <template #footer>
      <span v-if="tried && count" class="mr-auto text-sm text-danger" data-testid="question-problems">{{ t("quizzes.editor.problems", { n: count }, count) }}</span>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton v-if="!editing" variant="secondary" :loading="saving" @click="save('draft')">{{ t("quizzes.editor.saveDraft") }}</UiButton>
      <UiButton variant="primary" :loading="saving" data-testid="question-save" @click="save()">{{ t("common.save") }}</UiButton>
    </template>
  </UiDrawer>
</template>
