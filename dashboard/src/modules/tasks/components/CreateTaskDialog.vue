<script setup lang="ts">
/**
 * "New task" (plan §6.2): for people, a position or a branch's staff, one task per person. Due
 * presets, priority, proof, confirmation, a checklist and an optional reward. The footer says how
 * many tasks it makes and who gets them before anything is created.
 */
import { Building2, Camera, UserRound, Users } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

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

import { useCreateTasks, useTaskOptions } from "../api";
import { zonedIso } from "../meta";
import type { ProofKind, TaskPriority } from "../types";
import ChecklistEditor from "./ChecklistEditor.vue";

const open = defineModel<boolean>("open", { default: false });
const emit = defineEmits<{ created: [ids: number[]] }>();

const { t } = useI18n();
const company = useCompanyStore();
const options = useTaskOptions();
const create = useCreateTasks();

type Audience = "people" | "positions" | "branches";
type DuePreset = "hour" | "today" | "tomorrow_am" | "tomorrow_pm" | "three_days" | "none" | "custom";

const title = ref("");
const description = ref("");
const audience = ref<Audience>("people");
const people = ref<number[]>([]);
const positions = ref<number[]>([]);
const branches = ref<number[]>([]);
const due = ref<DuePreset>("tomorrow_am");
const customDay = ref<string | null>(null);
const customTime = ref<string | null>("18:00");
const priority = ref<TaskPriority>("normal");
const proof = ref<ProofKind>("none");
const needsConfirmation = ref(false);
const checklist = ref<string[]>([]);
const reward = ref<string | null>(null);
const showErrors = ref(false);

function reset(): void {
  title.value = "";
  description.value = "";
  audience.value = "people";
  people.value = [];
  positions.value = [];
  branches.value = [];
  due.value = "tomorrow_am";
  customDay.value = addDays(todayIn(company.timezone), 1);
  customTime.value = "18:00";
  priority.value = "normal";
  proof.value = "none";
  needsConfirmation.value = false;
  checklist.value = [];
  reward.value = null;
  showErrors.value = false;
}
watch(open, (value) => value && reset(), { immediate: true });
// Proof photos are worth a look: asking for a photo suggests confirming it too.
watch(proof, (value) => {
  if (value === "photo") needsConfirmation.value = true;
});

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
  const presets: Array<{ value: DuePreset; label: string }> = [{ value: "hour", label: t("tasks.create.due.hour") }];
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

const titleError = computed(() => (showErrors.value && !title.value.trim() ? t("tasks.create.titleRequired") : null));
const whoError = computed(() => (showErrors.value && recipients.value.length === 0 ? t("tasks.create.whoRequired") : null));

const proofOptions = computed(() => (["none", "photo", "text", "any"] as const).map((value) => ({ value, label: t(`tasks.proof.${value}`) })));

async function submit(): Promise<void> {
  showErrors.value = true;
  if (!title.value.trim() || recipients.value.length === 0) return;
  try {
    const result = await create.mutateAsync({
      title: title.value.trim(),
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
    toast.success(t("tasks.create.done", { n: result.created }, result.created), { description: title.value.trim() });
    open.value = false;
    emit("created", result.ids);
  } catch {
    // Field errors and the reason come from the HTTP layer.
  }
}
</script>

<template>
  <UiDialog v-model:open="open" :title="t('tasks.create.title')" :description="t('tasks.create.description')" size="xl">
    <form class="grid gap-x-6 gap-y-4 lg:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)]" @submit.prevent="submit" @keydown.meta.enter.prevent="submit" @keydown.ctrl.enter.prevent="submit">
      <div class="flex min-w-0 flex-col gap-4">
        <FormField :label="t('tasks.field.title')" :error="titleError" required>
          <TextInput v-model="title" :maxlength="200" :placeholder="t('tasks.create.titlePlaceholder')" autofocus />
        </FormField>
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
                :class="[
                  'pressable h-8 rounded-full border px-3 text-sm transition-colors',
                  due === preset.value ? 'border-primary bg-accent-soft font-semibold text-accent-fg' : 'border-line bg-surface text-fg hover:bg-highlight',
                ]"
                @click="due = preset.value"
              >
                {{ preset.label }}
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
        <ToggleSwitch v-model="needsConfirmation" layout="row" :label="t('tasks.create.confirm')" :description="t('tasks.create.confirmHint')" />
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
      <UiButton variant="primary" :icon="proof === 'photo' ? Camera : undefined" :loading="create.isPending.value" kbd="⌘↵" @click="submit">{{ t("tasks.create.submit") }}</UiButton>
    </template>
  </UiDialog>
</template>
