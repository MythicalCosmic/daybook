<script setup lang="ts">
/**
 * Create or edit a routine (made every day it's due, for everyone it names) or an onboarding
 * template (given once to each new person it names, a few days after they're let in). People,
 * positions, an optional branch, proof, checklist, reminder policy and who hears when it's late.
 * Existing routines show "who gets it tomorrow" beside the form. The When section says when the
 * next (or first) tasks come as you type; a routine made after today's deadline starts the next
 * day it's due, and saving one offers "Give today's task now".
 */
import { CalendarClock, Trash2 } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import BranchPicker from "@/components/BranchPicker.vue";
import DatePicker from "@/components/DatePicker.vue";
import FormField from "@/components/FormField.vue";
import NumberInput from "@/components/NumberInput.vue";
import PersonPicker from "@/components/PersonPicker.vue";
import PositionPicker from "@/components/PositionPicker.vue";
import SelectBox from "@/components/SelectBox.vue";
import TextArea from "@/components/TextArea.vue";
import TextInput from "@/components/TextInput.vue";
import TimePicker from "@/components/TimePicker.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import UiButton from "@/components/UiButton.vue";
import UiDrawer from "@/components/UiDrawer.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import WeekdayPicker from "@/components/WeekdayPicker.vue";
import { isApiError } from "@/api/http";

import { useDeleteRoutine, useFinishRule, usePlanOptions, useSaveRoutine } from "../api";
import { afterSave, missesToday, nextRunOf, runLabel } from "../lib";
import type { ProofKind, Routine, RoutineInput } from "../types";
import { useRunWords } from "../useRunWords";
import ChecklistEditor from "./ChecklistEditor.vue";
import GiveTodayDialog from "./GiveTodayDialog.vue";
import RoutinePreview from "./RoutinePreview.vue";

const open = defineModel<boolean>("open", { default: false });
const props = withDefaults(defineProps<{ routine?: Routine | null; onboarding?: boolean }>(), { routine: null, onboarding: false });
const emit = defineEmits<{ saved: [routine: Routine]; deleted: [] }>();

const { t } = useI18n();
const confirm = useConfirm();
const options = usePlanOptions();
const save = useSaveRoutine();
const remove = useDeleteRoutine();

const isOnboarding = computed(() => props.routine?.onboarding ?? props.onboarding);
const editing = computed(() => !!props.routine);

const title = ref("");
const description = ref("");
const weekdays = ref<number[]>([0, 1, 2, 3, 4, 5, 6]);
const dueTime = ref<string | null>("09:00");
const startsOn = ref<string | null>(null);
const dueAfter = ref<number | null>(1);
const people = ref<number[]>([]);
const positions = ref<number[]>([]);
const branch = ref<number | null>(null);
const proof = ref<ProofKind>("none");
/** "Check each one": null on a new routine until touched (the company's rule decides, §15.3). */
const needsConfirmation = ref<boolean | null>(null);
const confirmTouched = ref(false);
const finishRule = useFinishRule();
const rule = computed(() => finishRule.data.value?.on_finish ?? "auto");
const confirmShown = computed(() => needsConfirmation.value ?? rule.value !== "auto");
const confirmHint = computed(() => {
  if (confirmTouched.value) return undefined;
  if (props.routine) return props.routine.needs_confirmation && props.routine.accept_with_proof ? t("routines.editor.acceptWithProof") : undefined;
  return t({ auto: "routines.editor.ruleAuto", proof: "routines.editor.ruleProof", ask: "routines.editor.ruleAsk" }[rule.value]);
});
function setConfirmation(value: boolean): void {
  needsConfirmation.value = value;
  confirmTouched.value = true;
}
const checklist = ref<string[]>([]);
const policy = ref<number | null>(null);
const escalateTo = ref<number | null>(null);
const active = ref(true);
const errors = ref<Record<string, string>>({});

function load(): void {
  const routine = props.routine;
  title.value = routine?.title ?? "";
  description.value = routine?.description ?? "";
  weekdays.value = routine ? [...routine.weekdays] : [0, 1, 2, 3, 4, 5, 6];
  dueTime.value = routine ? routine.due_time.slice(0, 5) : isOnboarding.value ? "12:00" : "09:00";
  startsOn.value = routine?.starts_on ?? null;
  dueAfter.value = routine?.due_after_days ?? 1;
  people.value = routine?.assignees.map((p) => p.id) ?? [];
  positions.value = routine?.positions.map((p) => p.id) ?? [];
  branch.value = routine?.branch?.id ?? null;
  proof.value = routine?.proof ?? "none";
  needsConfirmation.value = routine ? routine.needs_confirmation : null;
  confirmTouched.value = false;
  checklist.value = routine ? [...routine.checklist] : [];
  policy.value = routine?.reminder_policy?.id ?? null;
  escalateTo.value = routine?.escalate_to?.id ?? null;
  active.value = routine?.is_active ?? true;
  errors.value = {};
}
watch(open, (value) => value && load(), { immediate: true });

const pickerPeople = computed(() =>
  (options.data.value?.people ?? []).map((p) => ({ id: p.id, name: p.name, photo_url: p.photo_url, subtitle: [p.position, p.branch].filter(Boolean).join(" · ") })),
);
const policyOptions = computed(() => [
  { value: 0, label: t("routines.editor.defaultPolicy") },
  ...(options.data.value?.policies ?? []).filter((p) => !p.is_default).map((p) => ({ value: p.id, label: p.name })),
]);
const policyValue = computed({ get: () => policy.value ?? 0, set: (value: number) => (policy.value = value || null) });

// When its tasks come, as the form stands (the server has the last word: it knows the holidays).
const words = useRunWords();
const runHint = computed(() => {
  if (isOnboarding.value) return null;
  if (editing.value && !active.value) return { text: t("routines.editor.pausedRun"), late: null };
  const draft = { weekdays: weekdays.value, due_time: dueTime.value, starts_on: startsOn.value };
  const next = nextRunOf(draft, words.value.now, words.value.timeZone);
  if (!next) return null;
  const when = runLabel(next, words.value);
  const late = !editing.value && missesToday(draft, words.value.now, words.value.timeZone) ? t("routines.editor.missesToday", { time: dueTime.value }) : null;
  return { text: t(editing.value ? "routines.editor.nextRun" : "routines.editor.firstRun", { when }), late };
});

// After saving: when the first tasks come, and today's task for a routine made after its time.
const giveOpen = ref(false);
const saved = ref<Routine | null>(null);
function announce(routine: Routine, created: boolean): void {
  const title = created ? t("routines.toast.created") : t("routines.toast.saved");
  const next = afterSave(routine, created);
  if (next === "dialog") {
    // It missed today's deadline: say so where it can't be missed, and offer today's task.
    saved.value = routine;
    giveOpen.value = true;
    toast.success(title, { description: routine.title });
    return;
  }
  const when = routine.next_run ? runLabel(routine.next_run, words.value) : null;
  const description = when ? t(created ? "routines.editor.firstRun" : "routines.editor.nextRun", { when }) : routine.title;
  toast.success(title, {
    description,
    ...(next === "offer" ? { action: { label: t("routines.give.button"), onClick: () => ((saved.value = routine), (giveOpen.value = true)) } } : {}),
  });
}
const proofOptions = computed(() => (["none", "photo", "text", "any"] as const).map((value) => ({ value, label: t(`routines.proof.${value}`) })));

function input(): RoutineInput {
  const body: RoutineInput = {
    title: title.value.trim(),
    description: description.value.trim(),
    due_time: dueTime.value ?? "09:00",
    proof: proof.value,
    // Sent when touched; a new routine sends null (the company's rule), an edit leaves it be.
    ...(confirmTouched.value ? { needs_confirmation: needsConfirmation.value } : props.routine ? {} : { needs_confirmation: null }),
    checklist: checklist.value.map((step) => step.trim()).filter(Boolean),
    branch_id: branch.value,
    assignee_ids: people.value,
    position_ids: positions.value,
    reminder_policy_id: policy.value,
    escalate_to_id: escalateTo.value,
    is_active: active.value,
  };
  if (isOnboarding.value) {
    body.onboarding = true;
    body.due_after_days = dueAfter.value ?? 1;
  } else {
    body.weekdays = weekdays.value;
    body.starts_on = startsOn.value;
  }
  return body;
}

function validate(): boolean {
  const found: Record<string, string> = {};
  if (!title.value.trim()) found.title = t("routines.editor.titleRequired");
  if (!dueTime.value) found.due_time = t("routines.editor.timeRequired");
  if (!isOnboarding.value && weekdays.value.length === 0) found.weekdays = t("routines.editor.daysRequired");
  if (!isOnboarding.value && people.value.length === 0 && positions.value.length === 0) found.who = t("routines.editor.whoRequired");
  errors.value = found;
  return Object.keys(found).length === 0;
}

async function submit(): Promise<void> {
  if (!validate()) return;
  try {
    const created = !editing.value;
    const routine = await save.mutateAsync({ id: props.routine?.id ?? null, input: input() });
    open.value = false;
    if (routine.onboarding) toast.success(created ? t("routines.toast.created") : t("routines.toast.saved"), { description: routine.title });
    else announce(routine, created);
    emit("saved", routine);
  } catch (error) {
    if (isApiError(error)) {
      const fields = error.fieldErrors;
      errors.value = Object.fromEntries(Object.entries(fields).map(([key, messages]) => [key, messages[0] ?? ""]));
    }
  }
}

async function onDelete(): Promise<void> {
  const routine = props.routine;
  if (!routine) return;
  const answer = await confirm({
    title: t("routines.delete.title"),
    message: t("routines.delete.body", { title: routine.title }),
    tone: "danger",
    confirmLabel: t("common.delete"),
  });
  if (!answer) return;
  try {
    await remove.mutateAsync(routine.id);
    toast.success(t("routines.toast.deleted"), { description: routine.title });
    open.value = false;
    emit("deleted");
  } catch {
    // shown by the HTTP layer
  }
}
</script>

<template>
  <UiDrawer
    v-model:open="open"
    :size="editing && !isOnboarding ? 'xl' : 'lg'"
    :title="editing ? t('routines.editor.editTitle') : isOnboarding ? t('routines.editor.newOnboarding') : t('routines.editor.newTitle')"
    :description="isOnboarding ? t('routines.editor.onboardingHint') : t('routines.editor.routineHint')"
  >
    <div :class="['grid gap-6 p-5', editing && !isOnboarding && 'lg:grid-cols-[minmax(0,1fr)_260px]']">
      <form class="flex min-w-0 flex-col gap-5" @submit.prevent="submit">
        <section class="flex flex-col gap-4">
          <FormField :label="t('routines.field.title')" :error="errors.title" required>
            <TextInput v-model="title" :maxlength="200" :placeholder="isOnboarding ? t('routines.editor.onboardingPlaceholder') : t('routines.editor.titlePlaceholder')" autofocus />
          </FormField>
          <FormField :label="t('routines.field.description')" optional>
            <TextArea v-model="description" :rows="2" :placeholder="t('routines.editor.descriptionPlaceholder')" />
          </FormField>
        </section>

        <section class="flex flex-col gap-4 border-t border-line pt-5">
          <h3 class="text-xs font-semibold uppercase tracking-[0.05em] text-subtle">{{ t("routines.editor.when") }}</h3>
          <FormField v-if="!isOnboarding" :label="t('routines.field.weekdays')" :error="errors.weekdays" required>
            <WeekdayPicker v-model="weekdays" presets />
          </FormField>
          <div class="grid gap-4 sm:grid-cols-2">
            <FormField v-if="isOnboarding" :label="t('routines.field.dueAfter')" :hint="t('routines.editor.dueAfterHint')">
              <NumberInput v-model="dueAfter" :min="0" :max="90" :suffix="t('routines.unit.days')" steppers />
            </FormField>
            <FormField :label="t('routines.field.dueTime')" :error="errors.due_time" required>
              <TimePicker v-model="dueTime" :step="15" />
            </FormField>
            <FormField v-if="!isOnboarding" :label="t('routines.field.startsOn')" :hint="t('routines.editor.startsOnHint')" optional>
              <DatePicker v-model="startsOn" clearable />
            </FormField>
          </div>
          <div v-if="runHint" class="flex items-start gap-2.5 rounded-[10px] bg-surface-2 px-3 py-2.5 text-sm" data-testid="run-hint" aria-live="polite">
            <CalendarClock :size="16" class="mt-0.5 shrink-0 text-accent-fg" aria-hidden="true" />
            <div class="min-w-0">
              <p class="font-medium text-fg">{{ runHint.text }}</p>
              <p v-if="runHint.late" class="mt-0.5 text-muted">{{ runHint.late }}</p>
            </div>
          </div>
        </section>

        <section class="flex flex-col gap-4 border-t border-line pt-5">
          <h3 class="text-xs font-semibold uppercase tracking-[0.05em] text-subtle">{{ t("routines.editor.who") }}</h3>
          <p v-if="errors.who" class="-mt-2 text-sm text-danger">{{ errors.who }}</p>
          <p v-else-if="isOnboarding" class="-mt-2 text-sm text-muted">{{ t("routines.editor.onboardingWho") }}</p>
          <FormField :label="t('routines.field.positions')" :hint="isOnboarding ? undefined : t('routines.editor.positionsHint')">
            <PositionPicker v-model="positions" multiple :positions="options.data.value?.positions ?? []" />
          </FormField>
          <FormField v-if="!isOnboarding" :label="t('routines.field.people')">
            <PersonPicker v-model="people" multiple :people="pickerPeople" />
          </FormField>
          <FormField :label="t('routines.field.branch')" :hint="t('routines.editor.branchHint')" optional>
            <BranchPicker v-model="branch" :placeholder="t('routines.editor.allBranches')" />
          </FormField>
        </section>

        <section class="flex flex-col gap-4 border-t border-line pt-5">
          <h3 class="text-xs font-semibold uppercase tracking-[0.05em] text-subtle">{{ t("routines.editor.howDone") }}</h3>
          <div class="grid gap-4 sm:grid-cols-2">
            <FormField :label="t('routines.field.proof')">
              <SelectBox v-model="proof" :options="proofOptions" />
            </FormField>
            <div class="flex items-end pb-1">
              <ToggleSwitch
                :model-value="confirmShown"
                layout="row"
                class="w-full"
                :label="t('routines.field.needsConfirmation')"
                :description="confirmHint"
                @update:model-value="setConfirmation"
              />
            </div>
          </div>
          <FormField :label="t('routines.field.checklist')" :hint="t('routines.editor.checklistHint')" optional>
            <ChecklistEditor v-model="checklist" />
          </FormField>
        </section>

        <section class="flex flex-col gap-4 border-t border-line pt-5">
          <h3 class="text-xs font-semibold uppercase tracking-[0.05em] text-subtle">{{ t("routines.editor.reminders") }}</h3>
          <div class="grid gap-4 sm:grid-cols-2">
            <FormField :label="t('routines.field.policy')">
              <SelectBox v-model="policyValue" :options="policyOptions" />
            </FormField>
            <FormField :label="t('routines.field.escalateTo')" :hint="t('routines.editor.escalateHint')" optional>
              <PersonPicker v-model="escalateTo" :people="pickerPeople" :placeholder="t('routines.editor.escalateDefault')" />
            </FormField>
          </div>
          <ToggleSwitch v-if="editing" v-model="active" layout="row" :label="t('routines.field.active')" :description="t('routines.editor.activeHint')" />
        </section>
      </form>

      <aside v-if="editing && !isOnboarding && routine" class="flex min-w-0 flex-col gap-3 lg:border-l lg:border-line lg:pl-6">
        <h3 class="text-xs font-semibold uppercase tracking-[0.05em] text-subtle">{{ t("routines.preview.title") }}</h3>
        <RoutinePreview :routine-id="routine.id" compact />
      </aside>
    </div>

    <template #footer>
      <UiButton v-if="editing" variant="ghost" :icon="Trash2" class="mr-auto hover:!text-danger" :loading="remove.isPending.value" @click="onDelete">{{ t("common.delete") }}</UiButton>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="primary" :loading="save.isPending.value" @click="submit">{{ editing ? t("common.save") : t("common.create") }}</UiButton>
    </template>
  </UiDrawer>
  <GiveTodayDialog v-model:open="giveOpen" :routine="saved" />
</template>
