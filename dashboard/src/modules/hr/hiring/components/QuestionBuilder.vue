<script setup lang="ts">
/**
 * The questions a vacancy asks in the bot, one card each: the question, how it's answered (typed
 * text, a choice of buttons, yes or no, a number), whether it may be skipped, and for a choice its
 * options. Reorder with the arrows; at most eight questions and six options. Each problem shows on
 * its own card; `problems` (index → problem) comes from the form's last check.
 */
import { ArrowDown, ArrowUp, Binary, CircleHelp, Hash, List, Plus, Trash2, Type, X } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import IconButton from "@/components/IconButton.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import TextInput from "@/components/TextInput.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import UiButton from "@/components/UiButton.vue";

import { MAX_OPTIONS, MAX_QUESTIONS, OPTION_MAX, TEXT_MAX, emptyQuestion, type DraftQuestion, type QuestionProblem } from "../lib";
import type { QuestionKind } from "../types";

const questions = defineModel<DraftQuestion[]>({ required: true });
defineProps<{ problems?: Record<number, QuestionProblem> }>();

const { t } = useI18n();

const kinds = computed(() => [
  { value: "text" as QuestionKind, label: t("hr.hiring.kind.text"), icon: Type },
  { value: "choice" as QuestionKind, label: t("hr.hiring.kind.choice"), icon: List },
  { value: "yes_no" as QuestionKind, label: t("hr.hiring.kind.yes_no"), icon: Binary },
  { value: "number" as QuestionKind, label: t("hr.hiring.kind.number"), icon: Hash },
]);

function update(index: number, patch: Partial<DraftQuestion>): void {
  questions.value = questions.value.map((question, at) => (at === index ? { ...question, ...patch } : question));
}

function setKind(index: number, kind: QuestionKind): void {
  const question = questions.value[index]!;
  const options = kind === "choice" ? (question.options.length >= 2 ? question.options : [...question.options, "", ""].slice(0, 2)) : question.options;
  update(index, { kind, options });
}

function add(): void {
  if (questions.value.length >= MAX_QUESTIONS) return;
  questions.value = [...questions.value, emptyQuestion()];
}

function remove(index: number): void {
  questions.value = questions.value.filter((_question, at) => at !== index);
}

function shift(index: number, by: -1 | 1): void {
  const target = index + by;
  if (target < 0 || target >= questions.value.length) return;
  const next = [...questions.value];
  [next[index], next[target]] = [next[target]!, next[index]!];
  questions.value = next;
}

function setOption(index: number, at: number, value: string): void {
  const options = [...questions.value[index]!.options];
  options[at] = value;
  update(index, { options });
}

function addOption(index: number): void {
  const options = questions.value[index]!.options;
  if (options.length < MAX_OPTIONS) update(index, { options: [...options, ""] });
}

function removeOption(index: number, at: number): void {
  update(index, { options: questions.value[index]!.options.filter((_option, i) => i !== at) });
}
</script>

<template>
  <div class="flex flex-col gap-2.5" data-question-builder>
    <TransitionGroup name="list" tag="ol" class="flex flex-col gap-2.5">
      <li
        v-for="(question, index) in questions"
        :key="question.key"
        :class="['rounded-[12px] border bg-surface p-3', problems?.[index] ? 'border-danger/50' : 'border-line']"
        data-question
      >
        <div class="flex items-start gap-2">
          <span class="mt-1.5 grid size-6 shrink-0 place-items-center rounded-full bg-accent-soft text-xs font-semibold tabular-nums text-accent-fg" aria-hidden="true">{{ index + 1 }}</span>
          <div class="min-w-0 flex-1">
            <TextInput
              :model-value="question.text"
              :maxlength="TEXT_MAX"
              :placeholder="t('hr.hiring.form.questionPlaceholder')"
              :invalid="problems?.[index] === 'text' || problems?.[index] === 'textLong'"
              :aria-label="t('hr.hiring.form.questionN', { n: index + 1 })"
              @update:model-value="(value: string | null) => update(index, { text: value ?? '' })"
            />
          </div>
          <div class="flex shrink-0 items-center">
            <IconButton :icon="ArrowUp" size="sm" :label="t('hr.hiring.form.up')" :disabled="index === 0" @click="shift(index, -1)" />
            <IconButton :icon="ArrowDown" size="sm" :label="t('hr.hiring.form.down')" :disabled="index === questions.length - 1" @click="shift(index, 1)" />
            <IconButton :icon="Trash2" size="sm" :label="t('hr.hiring.form.removeQuestion')" @click="remove(index)" />
          </div>
        </div>
        <div class="mt-2.5 flex flex-wrap items-center gap-x-4 gap-y-2 pl-8">
          <SegmentedControl :model-value="question.kind" size="sm" :options="kinds" :aria-label="t('hr.hiring.form.answerKind')" @update:model-value="(kind: QuestionKind) => setKind(index, kind)" />
          <ToggleSwitch :model-value="question.required" size="sm" :label="t('hr.hiring.form.required')" @update:model-value="(value: boolean) => update(index, { required: value })" />
        </div>
        <div v-if="question.kind === 'choice'" class="mt-2.5 flex flex-col gap-1.5 pl-8" data-options>
          <div v-for="(option, at) in question.options" :key="at" class="flex items-center gap-1.5">
            <span class="size-1.5 shrink-0 rounded-full bg-line-strong" aria-hidden="true" />
            <TextInput
              :model-value="option"
              size="sm"
              :maxlength="OPTION_MAX"
              :placeholder="t('hr.hiring.form.optionN', { n: at + 1 })"
              :invalid="(problems?.[index] === 'options' && !option.trim()) || problems?.[index] === 'optionTwice' || (problems?.[index] === 'optionLong' && option.length > OPTION_MAX)"
              class="flex-1"
              @update:model-value="(value: string | null) => setOption(index, at, value ?? '')"
            />
            <IconButton :icon="X" size="sm" :label="t('hr.hiring.form.removeOption')" :disabled="question.options.length <= 2" @click="removeOption(index, at)" />
          </div>
          <button
            v-if="question.options.length < MAX_OPTIONS"
            type="button"
            class="pressable inline-flex h-8 w-fit items-center gap-1.5 rounded-[8px] px-2 text-sm font-medium text-muted hover:bg-highlight hover:text-fg"
            @click="addOption(index)"
          >
            <Plus :size="14" />{{ t("hr.hiring.form.addOption") }}
          </button>
        </div>
        <p v-if="problems?.[index]" class="mt-2 pl-8 text-sm text-danger" role="alert">{{ t(`hr.hiring.problem.${problems[index]}`) }}</p>
      </li>
    </TransitionGroup>

    <div v-if="!questions.length" class="flex items-center gap-3 rounded-[12px] border border-dashed border-line-strong px-4 py-3 text-sm text-muted">
      <CircleHelp :size="18" class="shrink-0 text-subtle" aria-hidden="true" />
      {{ t("hr.hiring.form.noQuestions") }}
    </div>
    <div class="flex flex-wrap items-center gap-2">
      <UiButton size="sm" :icon="Plus" :disabled="questions.length >= MAX_QUESTIONS" data-add-question @click="add">{{ t("hr.hiring.form.addQuestion") }}</UiButton>
      <span class="text-xs text-subtle">{{ t("hr.hiring.form.questionsLeft", { n: MAX_QUESTIONS - questions.length }, MAX_QUESTIONS - questions.length) }}</span>
      <slot name="extra" />
    </div>
  </div>
</template>
