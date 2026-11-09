<script setup lang="ts">
/**
 * A course: its details (who it is for, mandatory with a deadline and a renewal, a certificate),
 * its steps in order (lessons, pages, quizzes; required or not; sequential or any order) and its
 * People tab: everyone assigned with progress, the deadline and lateness, and the manager's
 * actions (assign more, remind, excuse, move the deadline, take it back).
 */
import { ArrowDown, ArrowUp, Archive, BellRing, BookOpen, CalendarClock, FileQuestion, PlayCircle, Plus, RotateCcw, Send, Trash2, UserMinus, UserPlus, XCircle } from "@lucide/vue";
import { computed, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";

import BranchPicker from "@/components/BranchPicker.vue";
import DatePicker from "@/components/DatePicker.vue";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import FormField from "@/components/FormField.vue";
import IconButton from "@/components/IconButton.vue";
import NumberInput from "@/components/NumberInput.vue";
import PageHeader from "@/components/PageHeader.vue";
import PersonCell from "@/components/PersonCell.vue";
import PositionPicker from "@/components/PositionPicker.vue";
import ProgressBar from "@/components/ProgressBar.vue";
import RadioCards from "@/components/RadioCards.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import TextArea from "@/components/TextArea.vue";
import TextInput from "@/components/TextInput.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { TOPIC_COLOR_KEYS, topicColor } from "@/lib/topicColors";
import { useFormat } from "@/lib/useFormat";
import { useCompanyId, useCompanyStore, useCompanyToday } from "@/stores/company";

import { learningApi, useCourse, useCoursePeople, useRefresh } from "../api";
import AssignDialog from "../components/AssignDialog.vue";
import StepDialog from "../components/StepDialog.vue";
import { STATE_TONES, STATUS_TONES } from "../lib";
import type { CourseDetail, CourseInput, CoursePerson, PeopleBucket, StepKind } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const route = useRoute();
const company = useCompanyStore();
const cid = useCompanyId();
const today = useCompanyToday();
const refresh = useRefresh();
const confirm = useConfirm();

const id = computed(() => Number(route.params.courseId));
const course = useCourse(id);
const data = computed<CourseDetail | undefined>(() => course.data.value);
const canManage = computed(() => company.can("learning.manage"));
const tab = ref<"details" | "steps" | "people">("steps");
const people = useCoursePeople(id, computed(() => tab.value === "people"));

const tabs = computed(() => [
  { id: "steps", label: t("learning.course.tabSteps"), count: data.value?.step_list.length },
  { id: "details", label: t("learning.course.tabDetails") },
  { id: "people", label: t("learning.course.tabPeople"), count: data.value?.stats.people },
]);

// Details -------------------------------------------------------------------------------------

const form = reactive({
  title: "",
  emoji: "",
  color: "",
  description: "",
  mandatory: false,
  audience: "all" as "all" | "positions",
  position_ids: [] as number[],
  branch_ids: [] as number[],
  due_days: null as number | null,
  renew_months: null as number | null,
  sequential: true,
  certificate: true,
});
watch(
  data,
  (value) => {
    if (!value) return;
    Object.assign(form, {
      title: value.title,
      emoji: value.emoji,
      color: value.color,
      description: value.description,
      mandatory: value.mandatory,
      audience: value.audience_all ? "all" : "positions",
      position_ids: value.positions.map((row) => row.id),
      branch_ids: value.branches.map((row) => row.id),
      due_days: value.due_days,
      renew_months: value.renew_months,
      sequential: value.sequential,
      certificate: value.certificate,
    });
  },
  { immediate: true },
);
const audienceOptions = computed(() => [
  { value: "all" as const, label: t("learning.audience.all"), description: t("learning.audience.allHint") },
  { value: "positions" as const, label: t("learning.audience.positions"), description: t("learning.audience.positionsHint") },
]);
const saving = ref(false);
async function saveDetails(): Promise<void> {
  saving.value = true;
  const input: CourseInput = {
    title: form.title.trim(),
    emoji: form.emoji.trim(),
    color: form.color,
    description: form.description,
    mandatory: form.mandatory,
    audience_all: form.audience === "all",
    position_ids: form.audience === "all" ? [] : form.position_ids,
    branch_ids: form.branch_ids,
    due_days: form.due_days || null,
    renew_months: form.renew_months || null,
    sequential: form.sequential,
    certificate: form.certificate,
  };
  try {
    await learningApi.updateCourse(cid.value, id.value, input);
    toast.success(t("learning.saved"));
    refresh();
  } finally {
    saving.value = false;
  }
}

async function act(action: "publish" | "archive" | "restore"): Promise<void> {
  if (action === "archive") {
    const ok = await confirm({ title: t("learning.course.archiveTitle"), message: t("learning.course.archiveBody"), confirmLabel: t("learning.course.archive"), tone: "danger" });
    if (!ok) return;
  }
  await learningApi.courseAction(cid.value, id.value, action);
  toast.success(t(`learning.course.done.${action}`));
  refresh();
}

// Steps ---------------------------------------------------------------------------------------

const stepIcons = { lesson: PlayCircle, page: BookOpen, quiz: FileQuestion } as const;
const adding = ref(false);
const taken = computed(() => (data.value?.step_list ?? []).map((step) => ({ kind: step.kind, id: step.target.id })));
async function addStep(input: { kind: StepKind; target_id: number; required: boolean }): Promise<void> {
  await learningApi.addStep(cid.value, id.value, input);
  refresh();
}
async function toggleRequired(stepId: number, required: boolean): Promise<void> {
  await learningApi.updateStep(cid.value, id.value, stepId, { required });
  refresh();
}
async function removeStep(stepId: number): Promise<void> {
  const ok = await confirm({ title: t("learning.step.removeTitle"), message: t("learning.step.removeBody"), confirmLabel: t("common.delete"), tone: "danger" });
  if (!ok) return;
  await learningApi.removeStep(cid.value, id.value, stepId);
  refresh();
}
async function move(index: number, by: -1 | 1): Promise<void> {
  const ids = (data.value?.step_list ?? []).map((step) => step.id);
  const target = index + by;
  if (target < 0 || target >= ids.length) return;
  [ids[index], ids[target]] = [ids[target]!, ids[index]!];
  await learningApi.reorderSteps(cid.value, id.value, ids);
  refresh();
}
const stepTarget = (kind: StepKind, targetId: number) =>
  kind === "lesson" ? `/c/${company.currentId}/learning/lessons/${targetId}` : kind === "page" ? `/c/${company.currentId}/knowledge/p/${targetId}` : `/c/${company.currentId}/learning/quizzes/${targetId}`;

// People --------------------------------------------------------------------------------------

const bucket = ref<"all" | PeopleBucket>("all");
const assigning = ref(false);
const rows = computed(() => {
  const all = people.data.value?.results ?? [];
  if (bucket.value === "all") return all;
  return all.filter((row) => bucketOf(row) === bucket.value);
});
function bucketOf(row: CoursePerson): PeopleBucket {
  const state = row.assignment.state;
  if (state === "exempt" || state === "cancelled") return "closed";
  if (state === "completed") return "completed";
  return row.assignment.late ? "late" : "open";
}
const bucketOptions = computed(() => {
  const counts = people.data.value?.counts;
  return [
    { value: "all" as const, label: t("common.all"), count: people.data.value?.results.length },
    { value: "open" as const, label: t("learning.people.open"), count: counts?.open },
    { value: "late" as const, label: t("learning.people.late"), count: counts?.late },
    { value: "completed" as const, label: t("learning.people.completed"), count: counts?.completed },
    { value: "closed" as const, label: t("learning.people.closed"), count: counts?.closed },
  ];
});
async function remind(memberIds?: number[]): Promise<void> {
  const { count } = await learningApi.remind(cid.value, id.value, memberIds);
  toast.success(count ? t("learning.people.reminded", { n: count }, count) : t("learning.people.nobodyToRemind"));
}
async function exempt(row: CoursePerson): Promise<void> {
  const answer = await confirm({ title: t("learning.people.exemptTitle", { name: row.member.name }), message: t("learning.people.exemptBody"), confirmLabel: t("learning.people.exempt"), reason: "required" });
  if (!answer) return;
  await learningApi.exempt(cid.value, row.assignment.id, answer.reason);
  refresh();
}
async function cancel(row: CoursePerson): Promise<void> {
  const ok = await confirm({ title: t("learning.people.cancelTitle", { name: row.member.name }), message: t("learning.people.cancelBody"), confirmLabel: t("learning.people.cancel"), tone: "danger" });
  if (!ok) return;
  await learningApi.cancel(cid.value, row.assignment.id);
  refresh();
}
const moving = ref<CoursePerson | null>(null);
const newDue = ref<string | null>(null);
function startMove(row: CoursePerson): void {
  moving.value = row;
  newDue.value = row.assignment.due_at ? row.assignment.due_at.slice(0, 10) : null;
}
async function saveMove(): Promise<void> {
  if (!moving.value) return;
  await learningApi.moveDue(cid.value, moving.value.assignment.id, newDue.value);
  moving.value = null;
  refresh();
}
const movingOpen = computed({ get: () => moving.value !== null, set: (value: boolean) => (moving.value = value ? moving.value : null) });
</script>

<template>
  <div>
    <ErrorState v-if="course.isError.value" :error="course.error.value" :retry="() => course.refetch()" />
    <template v-else-if="!data">
      <SkeletonBlock height="72px" radius="12px" class="mb-4" />
      <SkeletonBlock v-for="n in 4" :key="n" height="56px" radius="10px" class="mb-2" />
    </template>
    <template v-else>
      <PageHeader v-model:tab="tab" :title="`${data.emoji ? `${data.emoji} ` : ''}${data.title}`" :back="`/c/${company.currentId}/learning/courses`" :back-label="t('learning.nav.courses')" :tabs="tabs">
        <template #actions>
          <StatusPill :tone="STATUS_TONES[data.status]" :label="t(`learning.status.${data.status}`)" />
          <template v-if="canManage">
            <UiButton v-if="data.status === 'draft'" variant="primary" :icon="Send" :disabled="!data.step_list.length" @click="act('publish')">{{ t("learning.course.publish") }}</UiButton>
            <UiButton v-if="data.status === 'published'" variant="secondary" :icon="Archive" @click="act('archive')">{{ t("learning.course.archive") }}</UiButton>
            <UiButton v-if="data.status === 'archived'" variant="secondary" :icon="RotateCcw" @click="act('restore')">{{ t("learning.course.restore") }}</UiButton>
          </template>
        </template>
      </PageHeader>

      <!-- Steps -->
      <section v-if="tab === 'steps'" class="flex flex-col gap-3">
        <div class="flex flex-wrap items-center justify-between gap-2">
          <p class="text-sm text-muted">
            {{ data.sequential ? t("learning.course.sequentialOn") : t("learning.course.sequentialOff") }}
            · {{ t("learning.course.about", { time: fmt.duration(data.minutes) }) }}
          </p>
          <UiButton v-if="canManage && data.status !== 'archived'" size="sm" :icon="Plus" @click="adding = true">{{ t("learning.step.add") }}</UiButton>
        </div>
        <div v-if="!data.step_list.length" class="ui-card">
          <EmptyState :icon="PlayCircle" :title="t('learning.step.emptyTitle')" :description="t('learning.step.emptyBody')">
            <UiButton v-if="canManage" variant="primary" :icon="Plus" @click="adding = true">{{ t("learning.step.add") }}</UiButton>
          </EmptyState>
        </div>
        <ol v-else class="ui-card flex flex-col divide-y divide-line">
          <li v-for="(step, index) in data.step_list" :key="step.id" class="flex flex-wrap items-center gap-3 px-4 py-3">
            <span class="w-6 text-sm font-semibold text-muted tabular-nums">{{ index + 1 }}</span>
            <span class="grid size-9 shrink-0 place-items-center rounded-[10px] bg-surface-2 text-muted"><component :is="stepIcons[step.kind]" :size="18" aria-hidden="true" /></span>
            <span class="min-w-0 flex-1">
              <RouterLink :to="stepTarget(step.kind, step.target.id)" class="block truncate font-medium text-fg hover:underline">{{ step.target.emoji ? `${step.target.emoji} ` : "" }}{{ step.target.title }}</RouterLink>
              <span class="block text-xs text-muted">
                {{ t(`learning.step.kind.${step.kind}`) }}<template v-if="step.target.minutes"> · {{ fmt.duration(step.target.minutes) }}</template>
                <template v-if="step.target.status !== 'published'"> · {{ t(`learning.status.${step.target.status}`) }}</template>
              </span>
            </span>
            <ToggleSwitch v-if="canManage" :model-value="step.required" size="sm" :label="t('learning.step.requiredShort')" @update:model-value="(value: boolean) => toggleRequired(step.id, value)" />
            <StatusPill v-else-if="!step.required" size="sm" variant="outline" :label="t('learning.step.optional')" />
            <div v-if="canManage" class="flex items-center gap-1">
              <IconButton :icon="ArrowUp" size="sm" :label="t('learning.step.up')" :disabled="index === 0" @click="move(index, -1)" />
              <IconButton :icon="ArrowDown" size="sm" :label="t('learning.step.down')" :disabled="index === data.step_list.length - 1" @click="move(index, 1)" />
              <IconButton :icon="Trash2" size="sm" :label="t('learning.step.remove')" @click="removeStep(step.id)" />
            </div>
          </li>
        </ol>
        <StepDialog v-model:open="adding" :taken="taken" @pick="addStep" />
      </section>

      <!-- Details -->
      <form v-else-if="tab === 'details'" class="ui-card flex flex-col gap-5 p-5" @submit.prevent="saveDetails">
        <div class="grid gap-4 sm:grid-cols-[6rem_minmax(0,1fr)]">
          <FormField :label="t('learning.course.emoji')">
            <TextInput v-model="form.emoji" :maxlength="16" :disabled="!canManage" />
          </FormField>
          <FormField :label="t('learning.course.name')" required>
            <TextInput v-model="form.title" :maxlength="200" :disabled="!canManage" />
          </FormField>
        </div>
        <FormField :label="t('learning.course.description')" optional>
          <TextArea v-model="form.description" :rows="3" autosize :maxlength="2000" :disabled="!canManage" />
        </FormField>
        <FormField :label="t('learning.course.color')">
          <div class="flex flex-wrap gap-2" role="radiogroup" :aria-label="t('learning.course.color')">
            <button
              v-for="key in ['', ...TOPIC_COLOR_KEYS]"
              :key="key || 'none'"
              type="button"
              role="radio"
              :aria-checked="form.color === key"
              :aria-label="key || t('learning.course.noColor')"
              :disabled="!canManage"
              class="size-7 rounded-full border-2 transition"
              :class="form.color === key ? 'border-fg' : 'border-transparent'"
              :style="{ background: key ? topicColor(key) : 'var(--color-surface-2, #e5e5e5)' }"
              @click="form.color = key"
            />
          </div>
        </FormField>
        <FormField :label="t('learning.course.audience')">
          <RadioCards v-model="form.audience" :options="audienceOptions" :disabled="!canManage" />
        </FormField>
        <FormField v-if="form.audience === 'positions'" :label="t('learning.course.positions')" required>
          <PositionPicker v-model="form.position_ids" multiple :disabled="!canManage" />
        </FormField>
        <FormField :label="t('learning.course.branches')" :hint="t('learning.course.branchesHint')" optional>
          <BranchPicker v-model="form.branch_ids" multiple :disabled="!canManage" />
        </FormField>
        <ToggleSwitch v-model="form.mandatory" layout="row" :label="t('learning.course.mandatory')" :description="t('learning.course.mandatoryHint')" :disabled="!canManage" />
        <div class="grid gap-4 sm:grid-cols-2">
          <FormField :label="t('learning.course.dueDays')" :hint="t('learning.course.dueDaysHint')" optional>
            <NumberInput v-model="form.due_days" :min="0" :max="365" :suffix="t('learning.settings.days')" :disabled="!canManage" />
          </FormField>
          <FormField :label="t('learning.course.renew')" :hint="t('learning.course.renewHint')" optional>
            <NumberInput v-model="form.renew_months" :min="0" :max="60" :suffix="t('learning.course.months')" :disabled="!canManage" />
          </FormField>
        </div>
        <ToggleSwitch v-model="form.sequential" layout="row" :label="t('learning.course.sequential')" :description="t('learning.course.sequentialHint')" :disabled="!canManage" />
        <ToggleSwitch v-model="form.certificate" layout="row" :label="t('learning.course.certificate')" :description="t('learning.course.certificateHint')" :disabled="!canManage" />
        <div v-if="canManage">
          <UiButton type="submit" variant="primary" :loading="saving" :disabled="!form.title.trim()">{{ t("common.save") }}</UiButton>
        </div>
      </form>

      <!-- People -->
      <section v-else class="flex flex-col gap-3">
        <div class="flex flex-wrap items-center justify-between gap-2">
          <SegmentedControl v-model="bucket" :options="bucketOptions" size="sm" />
          <div v-if="canManage" class="flex flex-wrap gap-2">
            <UiButton size="sm" variant="secondary" :icon="BellRing" @click="remind()">{{ t("learning.people.remindAll") }}</UiButton>
            <UiButton size="sm" variant="primary" :icon="UserPlus" :disabled="data.status !== 'published'" @click="assigning = true">{{ t("learning.people.assign") }}</UiButton>
          </div>
        </div>
        <template v-if="people.isPending.value">
          <SkeletonBlock v-for="n in 4" :key="n" height="52px" radius="10px" />
        </template>
        <ErrorState v-else-if="people.isError.value" compact :error="people.error.value" :retry="() => people.refetch()" />
        <div v-else-if="!rows.length" class="ui-card">
          <EmptyState size="sm" :icon="UserPlus" :title="t('learning.people.empty')" :description="data.mandatory ? t('learning.people.emptyMandatory') : t('learning.people.emptyOptional')" />
        </div>
        <ul v-else class="ui-card flex flex-col divide-y divide-line">
          <li v-for="row in rows" :key="row.assignment.id" class="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3">
            <PersonCell :person="row.member" :subtitle="[row.member.position, row.member.branch].filter(Boolean).join(' · ') || null" link class="min-w-0 flex-1 basis-48" />
            <div class="flex w-full items-center gap-2 sm:w-48">
              <ProgressBar class="flex-1" size="sm" :value="row.assignment.percent" :max="100" tone="auto" />
              <span class="w-14 text-right text-xs text-muted tabular-nums">{{ row.assignment.steps_done }}/{{ row.assignment.steps_total }}</span>
            </div>
            <div class="flex w-40 flex-col items-start gap-0.5">
              <StatusPill v-if="row.assignment.late" size="sm" tone="danger" :label="t('learning.daysLate', { n: row.assignment.days_late }, row.assignment.days_late)" />
              <StatusPill v-else size="sm" :tone="STATE_TONES[row.assignment.state]" :label="t(`learning.state.${row.assignment.state}`)" />
              <span v-if="row.assignment.due_at && row.assignment.state !== 'completed'" class="text-[11px] text-subtle">{{ t("learning.people.dueOn", { day: fmt.instant(row.assignment.due_at, "date") }) }}</span>
              <span v-else-if="row.assignment.completed_at" class="text-[11px] text-subtle">{{ fmt.instant(row.assignment.completed_at, "date") }}<template v-if="row.assignment.certificate_no"> · {{ row.assignment.certificate_no }}</template></span>
            </div>
            <div v-if="canManage && (row.assignment.state === 'assigned' || row.assignment.state === 'in_progress')" class="flex items-center gap-1">
              <IconButton :icon="BellRing" size="sm" :label="t('learning.people.remind')" @click="remind([row.member.id])" />
              <IconButton :icon="CalendarClock" size="sm" :label="t('learning.people.move')" @click="startMove(row)" />
              <IconButton :icon="UserMinus" size="sm" :label="t('learning.people.exempt')" @click="exempt(row)" />
              <IconButton :icon="XCircle" size="sm" :label="t('learning.people.cancel')" @click="cancel(row)" />
            </div>
          </li>
        </ul>
        <AssignDialog v-model:open="assigning" :course-id="id" />
        <UiDialog v-model:open="movingOpen" :title="t('learning.people.moveTitle', { name: moving?.member.name ?? '' })" size="sm">
          <FormField :label="t('learning.people.newDue')" :hint="t('learning.people.newDueHint')">
            <DatePicker v-model="newDue" :min="today" clearable />
          </FormField>
          <template #footer>
            <UiButton variant="ghost" @click="moving = null">{{ t("common.cancel") }}</UiButton>
            <UiButton variant="primary" @click="saveMove">{{ t("common.save") }}</UiButton>
          </template>
        </UiDialog>
      </section>
    </template>
  </div>
</template>
