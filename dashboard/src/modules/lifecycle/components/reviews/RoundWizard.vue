<script setup lang="ts">
/**
 * A new review round in four steps (or a draft's changes): its name and period (last quarter by
 * default), who is in it (everyone, or some positions and/or pharmacies, with who would review
 * whom), the questions (a pharmacy's ready ones to keep or edit, 3 to 10, each a rating from 1 to
 * 5 or a text answer) and the two deadlines. It saves as a draft, or opens at once: then everyone
 * in it hears in the bot.
 */
import { ArrowDown, ArrowUp, CalendarRange, ClipboardList, ListChecks, Plus, RotateCcw, Send, Star, Trash2, Type, Users } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import BranchPicker from "@/components/BranchPicker.vue";
import DatePicker from "@/components/DatePicker.vue";
import FormField from "@/components/FormField.vue";
import IconButton from "@/components/IconButton.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import PositionPicker from "@/components/PositionPicker.vue";
import RadioCards from "@/components/RadioCards.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import TextInput from "@/components/TextInput.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import WizardSteps from "@/components/WizardSteps.vue";
import { toast } from "@/components/useToast";
import { useFormat } from "@/lib/useFormat";
import { useCompanyToday } from "@/stores/company";

import { reviewsApi, usePreview, useReviewMutation, useTemplate } from "../../reviews/api";
import {
  blankRound,
  editQuestion,
  ERROR_STEP,
  MAX_QUESTIONS,
  moveItem,
  presetPeriod,
  quarterOf,
  roundErrors,
  roundPayload,
  type PeriodPreset,
  type RoundErrors,
  type RoundForm,
  type RoundStep,
} from "../../reviews/lib";
import type { QuestionKind, Round } from "../../reviews/types";

const open = defineModel<boolean>("open", { default: false });
const props = withDefaults(defineProps<{ round?: Round | null }>(), { round: null });
const emit = defineEmits<{ saved: [round: Round] }>();

const { t } = useI18n();
const fmt = useFormat();
const today = useCompanyToday();
const template = useTemplate(() => open.value);

const STEPS: RoundStep[] = ["basics", "people", "questions", "deadlines"];
const step = ref<RoundStep>("basics");
const steps = computed(() => STEPS.map((id) => ({ id, label: t(`lifecycle.reviews.wizard.step.${id}`) })));
const form = ref<RoundForm>(blankRound(today.value, "", []));
const errors = ref<RoundErrors>({});
const nameTouched = ref(false);

function defaultName(preset: PeriodPreset, start: string, end: string): string {
  if (preset === "month") return t("lifecycle.reviews.wizard.nameMonth", { month: fmt.day(start, "monthYear") });
  if (preset === "half") return t("lifecycle.reviews.wizard.nameHalf", { half: end.slice(5, 7) === "06" ? 1 : 2, year: end.slice(0, 4) });
  if (preset === "quarter") return t("lifecycle.reviews.wizard.nameQuarter", quarterOf(end));
  return t("lifecycle.reviews.wizard.nameCustom");
}

function reset(): void {
  const questions = (template.data.value ?? []).map((question) => ({ kind: question.kind, text: question.text, key: question.key }));
  const round = props.round;
  if (round) {
    form.value = {
      name: round.name,
      preset: "custom",
      period_start: round.period_start,
      period_end: round.period_end,
      audience: round.audience.positions.length || round.audience.branches.length ? "some" : "all",
      positions: round.audience.positions.map((item) => item.id),
      branches: round.audience.branches.map((item) => item.id),
      questions: round.questions.map((question) => ({ kind: question.kind, text: question.text, key: question.key })),
      self_due_on: round.self_due_on,
      manager_due_on: round.manager_due_on,
    };
    nameTouched.value = true;
  } else {
    const blank = blankRound(today.value, "", questions);
    blank.name = defaultName("quarter", blank.period_start, blank.period_end);
    form.value = blank;
    nameTouched.value = false;
  }
  errors.value = {};
  step.value = "basics";
}
watch(open, (isOpen) => isOpen && reset(), { immediate: true });
// The template arrives after the dialog opened: fill an untouched new round with it.
watch(
  () => template.data.value,
  (value) => {
    if (value && open.value && !props.round && !form.value.questions.length) {
      form.value.questions = value.map((question) => ({ kind: question.kind, text: question.text, key: question.key }));
    }
  },
);

const presets = computed(() =>
  (["quarter", "month", "half", "custom"] as PeriodPreset[]).map((value) => ({ value, label: t(`lifecycle.reviews.wizard.preset.${value}`) })),
);
const preset = computed<PeriodPreset>({
  get: () => form.value.preset,
  set: (value) => {
    form.value.preset = value;
    if (value !== "custom") {
      const period = presetPeriod(value, today.value);
      form.value.period_start = period.start;
      form.value.period_end = period.end;
    }
    if (!nameTouched.value) form.value.name = defaultName(value, form.value.period_start, form.value.period_end);
  },
});

const audiences = computed(() => [
  { value: "all" as const, label: t("lifecycle.reviews.wizard.everyone"), description: t("lifecycle.reviews.wizard.everyoneHint"), icon: Users },
  { value: "some" as const, label: t("lifecycle.reviews.wizard.some"), description: t("lifecycle.reviews.wizard.someHint"), icon: ListChecks },
]);
const audience = computed<"all" | "some" | null>({ get: () => form.value.audience, set: (value) => (form.value.audience = value ?? "all") });
const previewParams = computed(() => ({
  position: form.value.audience === "some" ? form.value.positions : [],
  branch: form.value.audience === "some" ? form.value.branches : [],
  period_end: form.value.period_end || undefined,
}));
const preview = usePreview(previewParams, () => open.value && (step.value === "people" || step.value === "deadlines"));

const KIND_OPTIONS = computed(() => [
  { value: "rating" as QuestionKind, label: t("lifecycle.reviews.kind.rating"), icon: Star },
  { value: "text" as QuestionKind, label: t("lifecycle.reviews.kind.text"), icon: Type },
]);
function setText(index: number, text: string): void {
  const list = [...form.value.questions];
  list[index] = editQuestion(list[index]!, text, template.data.value ?? []);
  form.value.questions = list;
}
function setKind(index: number, kind: QuestionKind): void {
  const list = [...form.value.questions];
  list[index] = { ...list[index]!, kind, key: "" };
  form.value.questions = list;
}
function addQuestion(): void {
  if (form.value.questions.length >= MAX_QUESTIONS) return;
  form.value.questions = [...form.value.questions, { kind: "rating", text: "", key: "" }];
}
function useTemplateQuestions(): void {
  form.value.questions = (template.data.value ?? []).map((question) => ({ kind: question.kind, text: question.text, key: question.key }));
}

const message = (key: string | undefined) => (key ? t(`lifecycle.reviews.error.${key}`) : null);
const stepErrors = computed(() => [...new Set(Object.keys(errors.value).map((key) => ERROR_STEP[key as keyof RoundErrors]))]);
function check(only?: RoundStep): boolean {
  const all = roundErrors(form.value, today.value);
  const relevant = only ? Object.fromEntries(Object.entries(all).filter(([key]) => ERROR_STEP[key as keyof RoundErrors] === only)) : all;
  errors.value = relevant;
  return Object.keys(relevant).length === 0;
}
const index = computed(() => STEPS.indexOf(step.value));
function next(): void {
  if (!check(step.value)) return;
  step.value = STEPS[Math.min(STEPS.length - 1, index.value + 1)]!;
}
function previous(): void {
  step.value = STEPS[Math.max(0, index.value - 1)]!;
}

const create = useReviewMutation((cid, opening: boolean) => reviewsApi.createRound(cid, roundPayload(form.value, opening)));
const update = useReviewMutation((cid, id: number) => {
  const { open: _ignored, ...body } = roundPayload(form.value, false);
  return reviewsApi.updateRound(cid, id, body);
});
const opening = useReviewMutation((cid, id: number) => reviewsApi.openRound(cid, id));
const busy = computed(() => create.isPending.value || update.isPending.value || opening.isPending.value);

async function submit(openNow: boolean): Promise<void> {
  if (!check()) {
    const first = stepErrors.value[0];
    if (first) step.value = first;
    return;
  }
  try {
    let saved: Round;
    if (props.round) {
      saved = await update.mutateAsync(props.round.id);
      if (openNow) saved = await opening.mutateAsync(saved.id);
    } else {
      saved = await create.mutateAsync(openNow);
    }
    toast.success(openNow ? t("lifecycle.reviews.wizard.opened", { count: saved.progress.people }, saved.progress.people) : t("lifecycle.reviews.wizard.savedDraft"));
    emit("saved", saved);
    open.value = false;
  } catch {
    // The HTTP layer showed the server's reason (nobody in it, a deadline passed).
  }
}

const reviewers = computed(() => preview.data.value?.reviewers ?? []);
const completed = computed(() => STEPS.slice(0, index.value));
</script>

<template>
  <UiDialog v-model:open="open" size="lg" :title="round ? t('lifecycle.reviews.wizard.editTitle') : t('lifecycle.reviews.wizard.title')" :description="t('lifecycle.reviews.wizard.description')">
    <div class="flex flex-col gap-5" data-round-wizard>
      <WizardSteps v-model="step" :steps="steps" :completed="completed" :errors="stepErrors" :linear="false" />

      <!-- 1. Name and period -->
      <div v-if="step === 'basics'" class="flex flex-col gap-4" data-step="basics">
        <FormField :label="t('lifecycle.reviews.wizard.period')" :error="message(errors.period)" required>
          <SegmentedControl v-model="preset" :options="presets" size="sm" :aria-label="t('lifecycle.reviews.wizard.period')" />
          <div class="mt-3 grid gap-2 sm:grid-cols-2">
            <DatePicker v-model="form.period_start" :max="today" format="medium" :disabled="preset !== 'custom'" :aria-label="t('lifecycle.reviews.wizard.periodStart')" />
            <DatePicker v-model="form.period_end" :min="form.period_start" format="medium" :disabled="preset !== 'custom'" :aria-label="t('lifecycle.reviews.wizard.periodEnd')" />
          </div>
        </FormField>
        <FormField :label="t('lifecycle.reviews.wizard.name')" :hint="t('lifecycle.reviews.wizard.nameHint')" :error="message(errors.name)" required>
          <TextInput v-model="form.name" :maxlength="120" :icon="CalendarRange" @update:model-value="nameTouched = true" />
        </FormField>
      </div>

      <!-- 2. Who is in it -->
      <div v-else-if="step === 'people'" class="flex flex-col gap-4" data-step="people">
        <RadioCards v-model="audience" :options="audiences" :columns="2" />
        <div v-if="form.audience === 'some'" class="grid gap-3 sm:grid-cols-2">
          <FormField :label="t('lifecycle.reviews.wizard.positions')" optional>
            <PositionPicker v-model="form.positions" multiple :placeholder="t('lifecycle.reviews.wizard.anyPosition')" />
          </FormField>
          <FormField :label="t('lifecycle.reviews.wizard.branches')" optional>
            <BranchPicker v-model="form.branches" multiple :placeholder="t('lifecycle.reviews.wizard.anyBranch')" />
          </FormField>
        </div>
        <p v-if="errors.audience" class="text-xs text-danger">{{ message(errors.audience) }}</p>

        <section class="rounded-[14px] border border-line p-4" data-preview>
          <div class="mb-3 flex items-center justify-between gap-2">
            <p class="text-sm font-semibold text-fg">{{ t("lifecycle.reviews.wizard.inIt", { count: preview.data.value?.count ?? 0 }, preview.data.value?.count ?? 0) }}</p>
            <span v-if="preview.isFetching.value" class="text-xs text-subtle">{{ t("lifecycle.reviews.wizard.counting") }}</span>
          </div>
          <div v-if="preview.isPending.value" class="flex flex-col gap-2"><SkeletonBlock v-for="n in 3" :key="n" height="36px" radius="10px" /></div>
          <template v-else-if="preview.data.value?.count">
            <p class="mb-2 text-xs font-medium text-muted">{{ t("lifecycle.reviews.wizard.whoReviews") }}</p>
            <ul class="mb-3 flex flex-wrap gap-2">
              <li v-for="item in reviewers" :key="item.reviewer?.id ?? 0" class="flex items-center gap-2 rounded-full border border-line py-1 pl-1 pr-3 text-sm">
                <UserAvatar :name="item.reviewer?.name ?? '?'" :src="item.reviewer?.photo_url" :size="24" />
                <span class="text-fg">{{ item.reviewer?.name ?? t("lifecycle.reviews.wizard.noReviewer") }}</span>
                <span class="tabular-nums text-muted">{{ item.people }}</span>
              </li>
            </ul>
            <ul class="max-h-56 divide-y divide-line overflow-y-auto rounded-[10px] border border-line">
              <li v-for="person in preview.data.value.people" :key="person.member.id" class="flex items-center gap-2.5 px-3 py-2">
                <UserAvatar :name="person.member.name" :src="person.member.photo_url" :size="26" />
                <div class="min-w-0 flex-1">
                  <p class="truncate text-sm text-fg">{{ person.member.name }}</p>
                  <p class="truncate text-xs text-muted">{{ [person.position, person.home_branch?.name].filter(Boolean).join(" · ") }}</p>
                </div>
                <span class="shrink-0 text-xs text-subtle">{{ person.reviewer ? t("lifecycle.reviews.wizard.reviewedBy", { name: person.reviewer.name }) : "—" }}</span>
              </li>
            </ul>
          </template>
          <p v-else class="text-sm text-muted">{{ t("lifecycle.reviews.wizard.nobody") }}</p>
          <p class="mt-3 text-xs text-subtle">{{ t("lifecycle.reviews.wizard.reviewerRule") }}</p>
        </section>
      </div>

      <!-- 3. Questions -->
      <div v-else-if="step === 'questions'" class="flex flex-col gap-3" data-step="questions">
        <div class="flex flex-wrap items-center justify-between gap-2">
          <p class="text-sm text-muted">{{ t("lifecycle.reviews.wizard.questionsHint") }}</p>
          <UiButton size="sm" variant="ghost" :icon="RotateCcw" @click="useTemplateQuestions">{{ t("lifecycle.reviews.wizard.useTemplate") }}</UiButton>
        </div>
        <div v-if="template.isPending.value && !form.questions.length" class="flex flex-col gap-2"><SkeletonBlock v-for="n in 5" :key="n" height="56px" radius="12px" /></div>
        <ol class="flex flex-col gap-2" data-questions>
          <li v-for="(question, number) in form.questions" :key="number" class="rounded-[12px] border border-line p-3">
            <div class="flex items-start gap-2">
              <span class="mt-2 grid size-6 shrink-0 place-items-center rounded-full bg-primary-soft text-xs font-semibold text-primary">{{ number + 1 }}</span>
              <div class="grid min-w-0 flex-1 gap-2">
                <TextInput :model-value="question.text" :maxlength="300" :placeholder="t('lifecycle.reviews.wizard.questionPlaceholder')" :invalid="!question.text.trim() && !!errors.questions" :aria-label="t('lifecycle.reviews.wizard.questionLabel', { number: number + 1 })" @update:model-value="(value) => setText(number, value ?? '')" />
                <SegmentedControl :model-value="question.kind" :options="KIND_OPTIONS" size="sm" :aria-label="t('lifecycle.reviews.wizard.kind')" @update:model-value="(value: QuestionKind) => setKind(number, value)" />
              </div>
              <div class="flex shrink-0 flex-col gap-0.5 sm:flex-row">
                <IconButton :icon="ArrowUp" size="sm" :label="t('lifecycle.reviews.wizard.up')" :disabled="number === 0" @click="form.questions = moveItem(form.questions, number, -1)" />
                <IconButton :icon="ArrowDown" size="sm" :label="t('lifecycle.reviews.wizard.down')" :disabled="number === form.questions.length - 1" @click="form.questions = moveItem(form.questions, number, 1)" />
                <IconButton :icon="Trash2" size="sm" :label="t('lifecycle.reviews.wizard.remove')" @click="form.questions = form.questions.filter((_, i) => i !== number)" />
              </div>
            </div>
          </li>
        </ol>
        <div class="flex flex-wrap items-center justify-between gap-2">
          <UiButton size="sm" :icon="Plus" :disabled="form.questions.length >= MAX_QUESTIONS" @click="addQuestion">{{ t("lifecycle.reviews.wizard.addQuestion") }}</UiButton>
          <span class="text-xs tabular-nums text-muted">{{ t("lifecycle.reviews.wizard.questionCount", { count: form.questions.length }, form.questions.length) }}</span>
        </div>
        <p v-if="errors.questions" class="text-xs text-danger">{{ message(errors.questions) }}</p>
      </div>

      <!-- 4. Deadlines -->
      <div v-else class="flex flex-col gap-4" data-step="deadlines">
        <div class="grid gap-3 sm:grid-cols-2">
          <FormField :label="t('lifecycle.reviews.wizard.selfDue')" :hint="t('lifecycle.reviews.wizard.selfDueHint')" :error="message(errors.self_due_on)" required>
            <DatePicker v-model="form.self_due_on" :min="today" format="weekday" :invalid="!!errors.self_due_on" />
          </FormField>
          <FormField :label="t('lifecycle.reviews.wizard.managerDue')" :hint="t('lifecycle.reviews.wizard.managerDueHint')" :error="message(errors.manager_due_on)" required>
            <DatePicker v-model="form.manager_due_on" :min="form.self_due_on || today" format="weekday" :invalid="!!errors.manager_due_on" />
          </FormField>
        </div>
        <section class="rounded-[14px] bg-surface-2/60 p-4 dark:bg-surface-3/40" data-summary>
          <p class="mb-2 flex items-center gap-2 text-sm font-semibold text-fg"><ClipboardList :size="16" aria-hidden="true" />{{ form.name || "—" }}</p>
          <ul class="grid gap-1.5 text-sm text-muted sm:grid-cols-2">
            <li>{{ t("lifecycle.reviews.wizard.sumPeriod", { from: form.period_start ? fmt.day(form.period_start, "medium") : "—", to: form.period_end ? fmt.day(form.period_end, "medium") : "—" }) }}</li>
            <li>{{ t("lifecycle.reviews.wizard.inIt", { count: preview.data.value?.count ?? 0 }, preview.data.value?.count ?? 0) }}</li>
            <li>{{ t("lifecycle.reviews.wizard.questionCount", { count: form.questions.length }, form.questions.length) }}</li>
            <li>{{ t("lifecycle.reviews.wizard.sumReviewers", { count: reviewers.length }, reviewers.length) }}</li>
          </ul>
        </section>
        <InlineAlert tone="info" size="sm" :description="t('lifecycle.reviews.wizard.openNote')" />
      </div>
    </div>

    <template #footer>
      <UiButton v-if="index > 0" variant="ghost" @click="previous">{{ t("lifecycle.reviews.wizard.back") }}</UiButton>
      <UiButton v-else variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <template v-if="index < STEPS.length - 1">
        <UiButton variant="primary" @click="next">{{ t("lifecycle.reviews.wizard.next") }}</UiButton>
      </template>
      <template v-else>
        <UiButton :loading="busy && !opening.isPending.value" :disabled="busy" @click="submit(false)">{{ round ? t("lifecycle.reviews.wizard.save") : t("lifecycle.reviews.wizard.saveDraft") }}</UiButton>
        <UiButton variant="primary" :icon="Send" :loading="busy" @click="submit(true)">{{ t("lifecycle.reviews.wizard.openNow") }}</UiButton>
      </template>
    </template>
  </UiDialog>
</template>
