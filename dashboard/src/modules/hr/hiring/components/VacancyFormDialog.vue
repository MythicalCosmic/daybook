<script setup lang="ts">
/**
 * A new vacancy or changes to one: the title and the position it hires for (whose access the hired
 * person gets), the branch (or any branch, for someone who sees them all), what the job is, the pay,
 * the days it takes applications, a diploma photo for a pharmacist's job, and the questions the bot
 * asks. A new one is saved as a draft or published at once; an edit sends only what changed.
 */
import { Rocket, Save, Sparkles } from "@lucide/vue";
import { computed, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { isApiError, unshownFieldError } from "@/api/http";
import type { Money } from "@/api/types";
import BranchPicker from "@/components/BranchPicker.vue";
import DatePicker from "@/components/DatePicker.vue";
import FormField from "@/components/FormField.vue";
import MoneyInput from "@/components/MoneyInput.vue";
import { useCompanyPositions, useScopedBranches } from "@/components/pickers";
import PositionPicker from "@/components/PositionPicker.vue";
import TextArea from "@/components/TextArea.vue";
import TextInput from "@/components/TextInput.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";
import { useCompanyStore, useCompanyToday } from "@/stores/company";

import { hiringApi, useHiringMutation } from "../api";
import { cleanQuestions, pharmacistQuestions, questionProblem, toDrafts, vacancyProblem, type DraftQuestion, type QuestionProblem } from "../lib";
import type { Vacancy, VacancyInput } from "../types";
import QuestionBuilder from "./QuestionBuilder.vue";

const open = defineModel<boolean>("open", { default: false });
const props = withDefaults(defineProps<{ vacancy?: Vacancy | null }>(), { vacancy: null });
const emit = defineEmits<{ saved: [vacancy: Vacancy, created: boolean] }>();

const { t } = useI18n();
const company = useCompanyStore();
const today = useCompanyToday();
const branches = useScopedBranches();

const editing = computed(() => !!props.vacancy);
/** Only someone who sees every branch may post a vacancy for the whole company. */
const everyBranch = computed(() => company.current?.branch_scope === null);

const form = reactive({
  title: "",
  position: null as number | null,
  branch: null as number | null,
  description: "",
  salary_from: null as Money | null,
  salary_to: null as Money | null,
  opens_on: null as string | null,
  closes_on: null as string | null,
  asks_document: false,
  questions: [] as DraftQuestion[],
});
const errors = reactive<Record<string, string | undefined>>({});
const questionProblems = ref<Record<number, QuestionProblem>>({});
const titleTyped = ref(false);

watch(
  open,
  (isOpen) => {
    if (!isOpen) return;
    for (const key of Object.keys(errors)) delete errors[key];
    questionProblems.value = {};
    const v = props.vacancy;
    titleTyped.value = !!v;
    Object.assign(form, {
      title: v?.title ?? "",
      position: v?.position?.id ?? null,
      branch: v ? (v.branch?.id ?? null) : branches.value.length === 1 ? branches.value[0]!.id : null,
      description: v?.description ?? "",
      salary_from: v?.salary_from ?? null,
      salary_to: v?.salary_to ?? null,
      opens_on: v?.opens_on ?? null,
      closes_on: v?.closes_on ?? null,
      asks_document: v?.asks_document ?? false,
      questions: toDrafts(v?.questions ?? []),
    });
  },
  { immediate: true },
);

// A new vacancy is titled after its position until a title is typed.
const positions = useCompanyPositions(computed(() => open.value));
function pickedPosition(id: number | null): void {
  form.position = id;
  const name = positions.data.value?.find((row) => row.id === id)?.name;
  if (!titleTyped.value && name) form.title = name;
}

function suggest(): void {
  form.questions = pharmacistQuestions(t);
  form.asks_document = true;
}

const body = computed<VacancyInput>(() => ({
  title: form.title.trim(),
  position_id: form.position,
  branch_id: form.branch,
  description: form.description.trim(),
  salary_from: form.salary_from,
  salary_to: form.salary_to,
  opens_on: form.opens_on,
  closes_on: form.closes_on,
  asks_document: form.asks_document,
  questions: cleanQuestions(form.questions),
}));

/** What changed against the vacancy being edited (questions compare as a whole). */
function changes(input: VacancyInput, vacancy: Vacancy): Partial<VacancyInput> {
  const before: VacancyInput = {
    title: vacancy.title,
    position_id: vacancy.position?.id ?? null,
    branch_id: vacancy.branch?.id ?? null,
    description: vacancy.description,
    salary_from: vacancy.salary_from,
    salary_to: vacancy.salary_to,
    opens_on: vacancy.opens_on,
    closes_on: vacancy.closes_on,
    asks_document: vacancy.asks_document,
    questions: cleanQuestions(toDrafts(vacancy.questions)),
  };
  const out: Partial<VacancyInput> = {};
  for (const key of Object.keys(input) as Array<keyof VacancyInput>) {
    if (JSON.stringify(input[key]) !== JSON.stringify(before[key])) (out as Record<string, unknown>)[key] = input[key];
  }
  return out;
}

const save = useHiringMutation((cid, args: { input: Partial<VacancyInput>; id: number | null }) =>
  args.id ? hiringApi.updateVacancy(cid, args.id, args.input) : hiringApi.createVacancy(cid, args.input as VacancyInput),
);
const publishing = ref(false);

function check(): boolean {
  for (const key of Object.keys(errors)) delete errors[key];
  const problem = vacancyProblem(form);
  if (problem) errors[problem === "title" ? "title" : problem === "salary" ? "salary_to" : "closes_on"] = t(`hr.hiring.problem.${problem}`);
  if (!everyBranch.value && !form.branch) errors.branch = t("hr.hiring.problem.branch");
  const found: Record<number, QuestionProblem> = {};
  form.questions.forEach((question, index) => {
    const wrong = questionProblem(question);
    if (wrong) found[index] = wrong;
  });
  questionProblems.value = found;
  return !Object.values(errors).some(Boolean) && !Object.keys(found).length;
}

async function submit(publish: boolean): Promise<void> {
  if (!check()) return;
  const vacancy = props.vacancy;
  const input = vacancy ? changes(body.value, vacancy) : { ...body.value, publish };
  if (vacancy && !Object.keys(input).length) {
    open.value = false;
    return;
  }
  publishing.value = publish;
  try {
    const saved = await save.mutateAsync({ input, id: vacancy?.id ?? null });
    toast.success(vacancy ? t("hr.hiring.form.saved") : publish ? t("hr.hiring.form.published") : t("hr.hiring.form.drafted"));
    emit("saved", saved, !vacancy);
    open.value = false;
  } catch (failure) {
    if (!isApiError(failure)) return;
    const fields: Record<string, string> = { position_id: "position", branch_id: "branch" };
    for (const [field, messages] of Object.entries(failure.fieldErrors)) errors[fields[field] ?? field] = messages[0];
    const unshown = unshownFieldError(failure, ["title", "position_id", "branch_id", "description", "salary_from", "salary_to", "opens_on", "closes_on"]);
    if (unshown) toast.error(unshown);
  }
}
</script>

<template>
  <UiDialog v-model:open="open" size="lg" :title="editing ? t('hr.hiring.form.editTitle') : t('hr.hiring.form.newTitle')" :description="t('hr.hiring.form.description')">
    <form class="flex flex-col gap-5" data-vacancy-form @submit.prevent="submit(!editing)">
      <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <FormField :label="t('hr.hiring.field.position')" :hint="t('hr.hiring.form.positionHint')" optional>
          <PositionPicker :model-value="form.position" clearable :placeholder="t('hr.hiring.form.positionPlaceholder')" @update:model-value="(id: number | null) => pickedPosition(id)" />
        </FormField>
        <FormField :label="t('hr.hiring.field.branch')" :hint="everyBranch ? t('hr.hiring.form.branchHint') : undefined" :error="errors.branch" :required="!everyBranch" :optional="everyBranch">
          <BranchPicker v-model="form.branch" :branches="branches" :clearable="everyBranch" :placeholder="everyBranch ? t('hr.hiring.anyBranch') : t('hr.hiring.form.branchPlaceholder')" :invalid="!!errors.branch" />
        </FormField>
      </div>
      <FormField :label="t('hr.hiring.field.title')" :error="errors.title" :count="form.title.length" :max="120" required>
        <TextInput v-model="form.title" :maxlength="120" :placeholder="t('hr.hiring.form.titlePlaceholder')" :invalid="!!errors.title" @update:model-value="titleTyped = true" />
      </FormField>
      <FormField :label="t('hr.hiring.field.description')" :hint="t('hr.hiring.form.descriptionHint')" :count="form.description.length" :max="2000" optional>
        <TextArea v-model="form.description" :rows="3" :max-rows="8" autosize :maxlength="2000" :placeholder="t('hr.hiring.form.descriptionPlaceholder')" />
      </FormField>
      <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <FormField :label="t('hr.hiring.field.salaryFrom')" :hint="t('hr.hiring.form.salaryPlaceholder')" optional>
          <MoneyInput v-model="form.salary_from" />
        </FormField>
        <FormField :label="t('hr.hiring.field.salaryTo')" :error="errors.salary_to" optional>
          <MoneyInput v-model="form.salary_to" :invalid="!!errors.salary_to" />
        </FormField>
        <FormField :label="t('hr.hiring.field.opensOn')" :hint="t('hr.hiring.form.opensHint')" optional>
          <DatePicker v-model="form.opens_on" clearable />
        </FormField>
        <FormField :label="t('hr.hiring.field.closesOn')" :hint="t('hr.hiring.form.closesHint')" :error="errors.closes_on" optional>
          <DatePicker v-model="form.closes_on" :min="form.opens_on && form.opens_on > today ? form.opens_on : today" clearable :invalid="!!errors.closes_on" />
        </FormField>
      </div>
      <div class="rounded-[12px] border border-line p-3">
        <ToggleSwitch v-model="form.asks_document" layout="row" :label="t('hr.hiring.form.asksDocument')" :description="t('hr.hiring.form.asksDocumentHint')" />
      </div>
      <section class="flex flex-col gap-2" :aria-label="t('hr.hiring.form.questions')">
        <div>
          <h3 class="text-sm font-semibold text-fg">{{ t("hr.hiring.form.questions") }}</h3>
          <p class="text-sm text-muted">{{ t("hr.hiring.form.questionsHint") }}</p>
        </div>
        <QuestionBuilder v-model="form.questions" :problems="questionProblems">
          <template v-if="!form.questions.length" #extra>
            <UiButton size="sm" variant="ghost" :icon="Sparkles" data-suggest @click="suggest">{{ t("hr.hiring.form.suggest") }}</UiButton>
          </template>
        </QuestionBuilder>
      </section>
    </form>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <template v-if="editing">
        <UiButton variant="primary" :icon="Save" :loading="save.isPending.value" data-save @click="submit(false)">{{ t("common.save") }}</UiButton>
      </template>
      <template v-else>
        <UiButton :icon="Save" :loading="save.isPending.value && !publishing" :disabled="save.isPending.value && publishing" data-draft @click="submit(false)">{{ t("hr.hiring.form.saveDraft") }}</UiButton>
        <UiButton variant="primary" :icon="Rocket" :loading="save.isPending.value && publishing" :disabled="save.isPending.value && !publishing" data-publish @click="submit(true)">{{ t("hr.hiring.form.publish") }}</UiButton>
      </template>
    </template>
  </UiDialog>
</template>
