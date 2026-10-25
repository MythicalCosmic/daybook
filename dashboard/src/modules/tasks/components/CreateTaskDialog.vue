<script setup lang="ts">
/**
 * "New task" (plan §6.2): for people, a position or a branch's staff, one task per person. Due
 * presets, priority, proof, confirmation, a checklist and an optional reward. The footer says how
 * many tasks it makes and who gets them before anything is created.
 *
 * Quick add (contract 1): the title is read as it's typed. "Ertaga 15:00 dorilarni sanash !!"
 * selects "tomorrow (Monday), 15:00" and Urgent, and saves the title as "Dorilarni sanash". The line
 * under the title says what was understood, with the weekday and the date; "Not a date" keeps the
 * words in the title. Picking a deadline or a priority by hand wins until the typed words change.
 */
import { Building2, CalendarClock, Camera, Repeat, Sparkles, UserRound, Users, X } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink } from "vue-router";

import AvatarStack from "@/components/AvatarStack.vue";
import BranchPicker from "@/components/BranchPicker.vue";
import DatePicker from "@/components/DatePicker.vue";
import FormField from "@/components/FormField.vue";
import MoneyInput from "@/components/MoneyInput.vue";
import PersonPicker from "@/components/PersonPicker.vue";
import PositionPicker from "@/components/PositionPicker.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SelectBox from "@/components/SelectBox.vue";
import TextArea from "@/components/TextArea.vue";
import TextInput from "@/components/TextInput.vue";
import TimePicker from "@/components/TimePicker.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";
import { addDays, todayIn, zonedNow } from "@/lib/dates";
import { useCompanyStore } from "@/stores/company";

import { useCompanyId, useCreateTasks, useTaskOptions, useTasksSettings } from "../api";
import { zonedIso } from "../meta";
import { resultKey, useQuickAdd } from "../quickAdd";
import type { ProofKind, TaskPriority } from "../types";
import ChecklistEditor from "./ChecklistEditor.vue";
import PriorityFlag from "./PriorityFlag.vue";

const open = defineModel<boolean>("open", { default: false });
const emit = defineEmits<{ created: [ids: number[]] }>();

const { t } = useI18n();
const company = useCompanyStore();
const companyId = useCompanyId();
const options = useTaskOptions();
const create = useCreateTasks();
const rules = useTasksSettings();

type Audience = "people" | "positions" | "branches";
type DuePreset = "parsed" | "hour" | "today" | "tomorrow_am" | "tomorrow_pm" | "three_days" | "none" | "custom";

const title = ref("");
const description = ref("");
const audience = ref<Audience>("people");
const people = ref<number[]>([]);
const positions = ref<number[]>([]);
const branches = ref<number[]>([]);
/** A deadline picked by hand; null = what the title says, else tomorrow 09:00. */
const dueChoice = ref<DuePreset | null>(null);
const customDay = ref<string | null>(null);
const customTime = ref<string | null>("18:00");
/** A priority picked by hand; null = what the title says, else normal. */
const priorityChoice = ref<TaskPriority | null>(null);
const proof = ref<ProofKind>("none");
/** "Check it when it's done": null until touched, and then the company's rule decides (§15.3). */
const needsConfirmation = ref<boolean | null>(null);
const rule = computed(() => rules.data.value?.on_finish ?? "auto");
const confirmShown = computed(() => needsConfirmation.value ?? rule.value !== "auto");
const confirmHint = computed(() => {
  if (needsConfirmation.value !== null) return t("tasks.create.confirmHint");
  return t({ auto: "tasks.create.ruleAuto", proof: "tasks.create.ruleProof", ask: "tasks.create.ruleAsk" }[rule.value]);
});
const checklist = ref<string[]>([]);
const reward = ref<string | null>(null);
const showErrors = ref(false);

// Quick add -------------------------------------------------------------------------------------
const quick = useQuickAdd(title, companyId);
/** The understanding the person said no to ("Not a date"); a different one shows again. */
const dismissed = ref<string | null>(null);
const understood = computed(() => {
  const result = quick.result.value;
  return result && resultKey(result) !== dismissed.value ? result : null;
});
// New words understood: they win over an earlier pick, as the latest thing the person said.
watch(
  () => resultKey(understood.value),
  (key) => {
    if (!key || !understood.value) return;
    if (understood.value.due_at) dueChoice.value = null;
    if (understood.value.priority) priorityChoice.value = null;
  },
);
function notADate(): void {
  dismissed.value = resultKey(quick.result.value);
}

function reset(): void {
  title.value = "";
  description.value = "";
  audience.value = "people";
  people.value = [];
  positions.value = [];
  branches.value = [];
  dueChoice.value = null;
  customDay.value = addDays(todayIn(company.timezone), 1);
  customTime.value = "18:00";
  priorityChoice.value = null;
  proof.value = "none";
  needsConfirmation.value = null;
  checklist.value = [];
  reward.value = null;
  showErrors.value = false;
  dismissed.value = null;
  quick.reset();
}
watch(open, (value) => value && reset(), { immediate: true });

const due = computed<DuePreset>({
  get: () => {
    // "From the title" picked, then the words deleted: back to the default, never "no deadline".
    const choice = dueChoice.value === "parsed" && !understood.value?.due_at ? null : dueChoice.value;
    return choice ?? (understood.value?.due_at ? "parsed" : "tomorrow_am");
  },
  set: (value) => (dueChoice.value = value),
});
const priority = computed<TaskPriority>({
  get: () => priorityChoice.value ?? understood.value?.priority ?? "normal",
  set: (value) => (priorityChoice.value = value),
});
/** The title as it will be saved: without the understood words, unless the person said no. */
const finalTitle = computed(() => (understood.value ? understood.value.title.trim() : title.value.trim()));

const pickerPeople = computed(() =>
  (options.data.value?.people ?? []).map((p) => ({ id: p.id, name: p.name, photo_url: p.photo_url, subtitle: [p.position, p.branch].filter(Boolean).join(" · ") })),
);
const me = computed(() => company.current?.membership_id ?? 0);

/** Who gets a task, as the server will resolve it (groups leave out the creator). */
const recipients = computed(() => {
  const all = options.data.value?.people ?? [];
  if (audience.value === "people") return all.filter((p) => people.value.includes(p.id));
  if (audience.value === "positions") return all.filter((p) => p.position_id !== null && positions.value.includes(p.position_id) && p.id !== me.value);
  return all.filter((p) => p.branch_id !== null && branches.value.includes(p.branch_id) && p.id !== me.value);
});

const hourNow = computed(() => zonedNow(company.timezone).getHours());
const duePresets = computed(() => {
  const presets: Array<{ value: DuePreset; label: string }> = [];
  if (understood.value?.due_at) presets.push({ value: "parsed", label: understood.value.due_label ?? understood.value.due_at });
  presets.push({ value: "hour", label: t("tasks.create.due.hour") });
  if (hourNow.value < 17) presets.push({ value: "today", label: t("tasks.create.due.today") });
  presets.push(
    { value: "tomorrow_am", label: t("tasks.create.due.tomorrowAm") },
    { value: "tomorrow_pm", label: t("tasks.create.due.tomorrowPm") },
    { value: "three_days", label: t("tasks.create.due.threeDays") },
    { value: "none", label: t("tasks.create.due.none") },
    { value: "custom", label: t("tasks.create.due.custom") },
  );
  return presets;
});

function dueAt(): string | null {
  const today = todayIn(company.timezone);
  switch (due.value) {
    case "parsed":
      return understood.value?.due_at ?? null;
    case "hour":
      return new Date(Date.now() + 60 * 60_000).toISOString();
    case "today":
      return zonedIso(today, "18:00", company.timezone);
    case "tomorrow_am":
      return zonedIso(addDays(today, 1), "09:00", company.timezone);
    case "tomorrow_pm":
      return zonedIso(addDays(today, 1), "18:00", company.timezone);
    case "three_days":
      return zonedIso(addDays(today, 3), "18:00", company.timezone);
    case "custom":
      return customDay.value ? zonedIso(customDay.value, customTime.value ?? "18:00", company.timezone) : null;
    default:
      return null;
  }
}

const titleError = computed(() => {
  if (!showErrors.value) return null;
  if (!title.value.trim()) return t("tasks.create.titleRequired");
  // Only a date was typed ("ertaga 15:00"): the date is understood, the work isn't.
  if (!finalTitle.value) return t("tasks.quick.titleMissing");
  return null;
});
const whoError = computed(() => (showErrors.value && recipients.value.length === 0 ? t("tasks.create.whoRequired") : null));

const proofOptions = computed(() => (["none", "photo", "text", "any"] as const).map((value) => ({ value, label: t(`tasks.proof.${value}`) })));

/** Saving: reading the title first can take a moment, and a second press mustn't make it twice. */
const saving = ref(false);

async function submit(): Promise<void> {
  if (saving.value) return;
  showErrors.value = true;
  saving.value = true;
  try {
    // Typed and saved within the pause: read the title first, so its deadline isn't lost.
    await quick.settle();
    if (!finalTitle.value || recipients.value.length === 0) return;
    const result = await create.mutateAsync({
      title: finalTitle.value,
      description: description.value.trim(),
      due_at: dueAt(),
      priority: priority.value,
      proof: proof.value,
      needs_confirmation: needsConfirmation.value,
      checklist: checklist.value.map((item) => item.trim()).filter(Boolean),
      reward: reward.value || null,
      assignee_ids: audience.value === "people" ? people.value : [],
      position_ids: audience.value === "positions" ? positions.value : [],
      branch_ids: audience.value === "branches" ? branches.value : [],
    });
    toast.success(t("tasks.create.done", { n: result.created }, result.created), { description: finalTitle.value });
    open.value = false;
    emit("created", result.ids);
  } catch {
    // Field errors and the reason come from the HTTP layer.
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <UiDialog v-model:open="open" :title="t('tasks.create.title')" :description="t('tasks.create.description')" size="xl">
    <form class="grid gap-x-6 gap-y-4 lg:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)]" @submit.prevent="submit" @keydown.meta.enter.prevent="submit" @keydown.ctrl.enter.prevent="submit">
      <div class="flex min-w-0 flex-col gap-4">
        <FormField :label="t('tasks.field.title')" :error="titleError" :hint="quick.available.value && !understood ? t('tasks.quick.hint') : undefined" required>
          <TextInput v-model="title" :maxlength="200" :placeholder="t('tasks.create.titlePlaceholder')" autofocus data-testid="create-title" />
        </FormField>
        <!-- What the title said: the saved title, the deadline with its weekday and date, urgency. -->
        <div
          v-if="understood"
          class="-mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 rounded-[10px] border border-dashed border-line-strong bg-surface-2 px-2.5 py-1.5 text-sm"
          role="status"
          :aria-label="t('tasks.quick.understood')"
          data-testid="quick-add-understood"
        >
          <span v-if="understood.title" class="inline-flex min-w-0 items-center gap-1 font-medium text-fg">
            <Sparkles :size="13" class="shrink-0 text-accent-fg" aria-hidden="true" /><span class="truncate">{{ understood.title }}</span>
          </span>
          <span v-if="understood.due_label" class="inline-flex items-center gap-1 text-fg"><CalendarClock :size="13" class="shrink-0 text-muted" aria-hidden="true" />{{ understood.due_label }}</span>
          <PriorityFlag v-if="understood.priority" :priority="understood.priority" />
          <span v-if="understood.repeat" class="inline-flex items-center gap-1 text-muted"><Repeat :size="13" aria-hidden="true" />{{ t(`tasks.quick.repeat.${understood.repeat}`) }}</span>
          <span class="flex-1" />
          <button
            type="button"
            class="pressable inline-flex h-6 items-center gap-1 rounded-full px-2 text-xs font-medium text-muted transition-colors hover:bg-highlight hover:text-fg"
            :title="t('tasks.quick.notDateHint')"
            data-testid="quick-add-dismiss"
            @click="notADate"
          >
            <X :size="12" aria-hidden="true" />{{ t("tasks.quick.notDate") }}
          </button>
        </div>
        <!-- Repeating work is a routine, not a one-off task. -->
        <p v-if="understood?.repeat" class="-mt-2 text-xs text-muted" data-testid="quick-add-repeat">
          {{ t("tasks.quick.repeatHint") }}
          <RouterLink :to="`/c/${company.currentId}/routines/all?new=1`" class="font-medium text-accent-fg hover:underline">{{ t("tasks.quick.makeRoutine") }}</RouterLink>
        </p>
        <FormField :label="t('tasks.field.description')" optional>
          <TextArea v-model="description" :rows="2" :max-rows="6" :placeholder="t('tasks.create.descriptionPlaceholder')" />
        </FormField>

        <FormField :label="t('tasks.create.who')" :error="whoError" required>
          <div class="flex flex-col gap-2">
            <SegmentedControl
              v-model="audience"
              size="sm"
              block
              :options="[
                { value: 'people', label: t('tasks.create.audience.people'), icon: UserRound },
                { value: 'positions', label: t('tasks.create.audience.positions'), icon: Users },
                { value: 'branches', label: t('tasks.create.audience.branches'), icon: Building2 },
              ]"
            />
            <PersonPicker v-if="audience === 'people'" v-model="people" multiple :people="pickerPeople" :placeholder="t('tasks.create.pickPeople')" />
            <PositionPicker v-else-if="audience === 'positions'" v-model="positions" multiple :positions="options.data.value?.positions ?? []" />
            <BranchPicker v-else v-model="branches" multiple />
          </div>
        </FormField>

        <FormField :label="t('tasks.field.due_at')">
          <div class="flex flex-col gap-2">
            <div class="flex flex-wrap gap-1.5" role="group" :aria-label="t('tasks.field.due_at')">
              <button
                v-for="preset in duePresets"
                :key="preset.value"
                type="button"
                :aria-pressed="due === preset.value"
                :title="preset.value === 'parsed' ? t('tasks.quick.fromTitle') : undefined"
                :data-testid="preset.value === 'parsed' ? 'due-parsed' : undefined"
                :class="[
                  'pressable inline-flex h-8 items-center gap-1 rounded-full border px-3 text-sm transition-colors',
                  due === preset.value ? 'border-primary bg-accent-soft font-semibold text-accent-fg' : 'border-line bg-surface text-fg hover:bg-highlight',
                ]"
                @click="due = preset.value"
              >
                <Sparkles v-if="preset.value === 'parsed'" :size="13" class="shrink-0" aria-hidden="true" />{{ preset.label }}
              </button>
            </div>
            <div v-if="due === 'custom'" class="grid grid-cols-[1fr_120px] gap-2 sm:max-w-[360px]">
              <DatePicker v-model="customDay" :min="todayIn(company.timezone)" />
              <TimePicker v-model="customTime" :step="15" />
            </div>
          </div>
        </FormField>
      </div>

      <div class="flex min-w-0 flex-col gap-4 lg:border-l lg:border-line lg:pl-6">
        <FormField :label="t('tasks.field.priority')">
          <SegmentedControl
            v-model="priority"
            size="sm"
            block
            :options="[
              { value: 'low', label: t('tasks.priority.low') },
              { value: 'normal', label: t('tasks.priority.normal') },
              { value: 'high', label: t('tasks.priority.high') },
              { value: 'urgent', label: t('tasks.priority.urgent') },
            ]"
          />
        </FormField>
        <FormField :label="t('tasks.field.proof')">
          <SelectBox v-model="proof" :options="proofOptions" />
        </FormField>
        <ToggleSwitch
          :model-value="confirmShown"
          layout="row"
          :label="t('tasks.create.confirm')"
          :description="confirmHint"
          @update:model-value="(value: boolean) => (needsConfirmation = value)"
        />
        <FormField :label="t('tasks.field.reward')" :hint="reward ? t('tasks.reward.perPerson') : t('tasks.reward.hint')" optional>
          <MoneyInput v-model="reward" />
        </FormField>
        <FormField :label="t('tasks.drawer.checklist')" optional>
          <ChecklistEditor v-model="checklist" />
        </FormField>
      </div>
    </form>

    <template #footer>
      <div class="mr-auto flex min-w-0 items-center gap-2 text-sm text-muted">
        <AvatarStack v-if="recipients.length" :people="recipients" :max="4" :size="24" />
        <span class="truncate">{{ recipients.length ? t("tasks.create.makes", { n: recipients.length }, recipients.length) : t("tasks.create.nobodyYet") }}</span>
      </div>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="primary" :icon="proof === 'photo' ? Camera : undefined" :loading="saving" kbd="mod+enter" @click="submit">{{ t("tasks.create.submit") }}</UiButton>
    </template>
  </UiDialog>
</template>
