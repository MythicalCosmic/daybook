<script setup lang="ts">
/**
 * A question as the learner sees it in the app (QuestionPlay): options, steps, the two sides of a
 * match, a box for a typed answer or a number. With `right` (the manager's preview, a review) the
 * right answer is marked; with `answer` the person's own one too.
 */
import { Check, X } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import { LETTERS } from "../lib";
import type { QuestionPlay } from "../types";

const props = withDefaults(
  defineProps<{
    question: QuestionPlay;
    right?: Record<string, unknown> | null;
    answer?: Record<string, unknown> | null;
    explanation?: string | null;
    compact?: boolean;
  }>(),
  { right: null, answer: null, explanation: null, compact: false },
);

const { t } = useI18n();

function picked(source: Record<string, unknown> | null, id: string): boolean {
  if (!source) return false;
  if (typeof source.option === "string") return source.option === id;
  return Array.isArray(source.options) && (source.options as string[]).includes(id);
}

/** The steps in the order of `source` (the right order, or the person's). */
function stepsOf(source: Record<string, unknown> | null): string[] {
  if (!source || !Array.isArray(source.order)) return [];
  const texts = new Map(props.question.options.map((option) => [option.id, option.text]));
  return (source.order as string[]).map((id) => texts.get(id) ?? "");
}

function pairsOf(source: Record<string, unknown> | null): Array<{ left: string; right: string }> {
  const pairs = (source?.pairs ?? {}) as Record<string, string>;
  const rights = new Map(props.question.right.map((row) => [row.id, row.text]));
  return props.question.left.map((left) => ({ left: left.text, right: rights.get(pairs[left.id] ?? "") ?? "—" }));
}

const rightSteps = computed(() => stepsOf(props.right));
const rightPairs = computed(() => (props.right ? pairsOf(props.right) : []));
const typed = computed(() => {
  if (!props.right) return null;
  if (props.question.kind === "text") return String(props.right.text ?? "");
  if (props.question.kind === "number") return `${String(props.right.value ?? "")} ${props.question.unit ?? ""}`.trim();
  return null;
});
const trueFalse = computed(() => (props.right && typeof props.right.value === "boolean" ? (props.right.value as boolean) : null));
</script>

<template>
  <div class="flex flex-col gap-3" :data-kind="question.kind" data-testid="question-preview">
    <p class="whitespace-pre-line font-medium text-fg" :class="compact ? 'text-sm' : 'text-base'">{{ question.text || t("quizzes.editor.noText") }}</p>
    <img v-if="question.image_url" :src="question.image_url" alt="" class="max-h-48 w-auto self-start rounded-lg border border-line object-contain" />

    <ul v-if="question.kind === 'single' || question.kind === 'multi'" class="flex flex-col gap-2">
      <li
        v-for="(option, index) in question.options"
        :key="option.id"
        class="flex items-start gap-2 rounded-lg border px-3 py-2 text-sm"
        :class="picked(right, option.id) ? 'border-success bg-success-soft' : picked(answer, option.id) ? 'border-danger bg-danger-soft' : 'border-line'"
      >
        <span class="inline-flex size-5 shrink-0 items-center justify-center rounded-md bg-surface-2 text-xs font-semibold text-muted">{{ LETTERS[index] }}</span>
        <span class="min-w-0 flex-1 text-fg">{{ option.text || "…" }}</span>
        <Check v-if="picked(right, option.id)" :size="16" class="shrink-0 text-success" :aria-label="t('quizzes.preview.right')" />
        <X v-else-if="picked(answer, option.id)" :size="16" class="shrink-0 text-danger" :aria-label="t('quizzes.preview.picked')" />
      </li>
      <li v-if="question.kind === 'multi'" class="text-xs text-muted">{{ t("quizzes.preview.multiHint") }}</li>
    </ul>

    <div v-else-if="question.kind === 'true_false'" class="grid grid-cols-2 gap-2">
      <span
        v-for="value in [true, false]"
        :key="String(value)"
        class="rounded-lg border px-3 py-2 text-center text-sm font-medium"
        :class="trueFalse === value ? 'border-success bg-success-soft text-success' : 'border-line text-fg'"
        >{{ value ? t("quizzes.preview.true") : t("quizzes.preview.false") }}</span
      >
    </div>

    <template v-else-if="question.kind === 'order'">
      <ol class="flex flex-col gap-2">
        <li v-for="option in question.options" :key="option.id" class="rounded-lg border border-line px-3 py-2 text-sm text-fg">{{ option.text || "…" }}</li>
      </ol>
      <div v-if="rightSteps.length" class="rounded-lg bg-success-soft px-3 py-2 text-sm text-success">
        <p class="font-medium">{{ t("quizzes.preview.rightOrder") }}</p>
        <ol class="ml-5 list-decimal">
          <li v-for="(step, index) in rightSteps" :key="index">{{ step }}</li>
        </ol>
      </div>
    </template>

    <template v-else-if="question.kind === 'match'">
      <div class="grid grid-cols-2 gap-2 text-sm">
        <ul class="flex flex-col gap-2">
          <li v-for="row in question.left" :key="row.id" class="rounded-lg border border-line px-3 py-2 text-fg">{{ row.text || "…" }}</li>
        </ul>
        <ul class="flex flex-col gap-2">
          <li v-for="row in question.right" :key="row.id" class="rounded-lg border border-dashed border-line px-3 py-2 text-fg">{{ row.text || "…" }}</li>
        </ul>
      </div>
      <ul v-if="rightPairs.length" class="flex flex-col gap-1 rounded-lg bg-success-soft px-3 py-2 text-sm text-success">
        <li v-for="(pair, index) in rightPairs" :key="index">{{ pair.left }} — {{ pair.right }}</li>
      </ul>
    </template>

    <div v-else class="flex items-center gap-2">
      <span class="flex-1 rounded-lg border border-line bg-surface-2 px-3 py-2 text-sm text-muted">{{ question.kind === "number" ? t("quizzes.preview.numberBox") : t("quizzes.preview.textBox") }}</span>
      <span v-if="question.unit" class="text-sm text-muted">{{ question.unit }}</span>
    </div>
    <p v-if="typed !== null" class="rounded-lg bg-success-soft px-3 py-2 text-sm text-success">{{ t("quizzes.preview.rightTyped", { answer: typed }) }}</p>

    <p v-if="explanation" class="rounded-lg bg-surface-2 px-3 py-2 text-sm text-muted">{{ explanation }}</p>
  </div>
</template>
