<script setup lang="ts">
/**
 * Log time by hand on this project (optionally a card): day, duration ("1:30", "90m", "2h" or a
 * quick chip), a note, billable. A project manager may log for a member.
 */
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import DatePicker from "@/components/DatePicker.vue";
import FormField from "@/components/FormField.vue";
import PersonPicker from "@/components/PersonPicker.vue";
import SelectBox from "@/components/SelectBox.vue";
import TextInput from "@/components/TextInput.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";
import { todayIn } from "@/lib/dates";
import { useCompanyStore } from "@/stores/company";

import { logTime, useCards, useCompanyId, useMembers, useRefreshProjects } from "../api";
import { hhmm, parseDuration } from "../lib";
import type { ProjectDetail } from "../types";

const open = defineModel<boolean>("open", { default: false });
const props = withDefaults(defineProps<{ project: ProjectDetail; taskId?: number | null; taskKey?: string | null; day?: string | null; personId?: number | null }>(), {
  taskId: null,
  taskKey: null,
  day: null,
  personId: null,
});
const emit = defineEmits<{ saved: [] }>();

const { t } = useI18n();
const company = useCompanyStore();
const companyId = useCompanyId();
const refresh = useRefreshProjects();
const members = useMembers(() => (open.value && props.project.capabilities.manage ? props.project.id : 0));
const cards = useCards(() => (open.value && !props.taskId ? props.project.id : 0));

const day = ref<string | null>(null);
const duration = ref("");
const note = ref("");
const billable = ref(false);
const task = ref<number | null>(null);
const person = ref<number | null>(null);
const saving = ref(false);
const errors = ref<Record<string, string>>({});

const minutes = computed(() => parseDuration(duration.value));
const chips = [15, 30, 60, 90, 120, 240];
const me = computed(() => company.current?.membership_id ?? null);
const today = computed(() => todayIn(company.timezone));

watch(open, (value) => {
  if (!value) return;
  day.value = props.day ?? today.value;
  duration.value = "";
  note.value = "";
  billable.value = false;
  task.value = props.taskId;
  person.value = props.personId ?? me.value;
  errors.value = {};
});

const peopleOptions = computed(() => (members.data.value ?? []).filter((m) => m.role !== "viewer").map((m) => ({ id: m.person.id, name: m.person.name, photo_url: m.person.photo_url, subtitle: m.position || undefined })));
const cardOptions = computed(() =>
  (cards.data.value ?? []).filter((c) => c.status !== "done" && c.status !== "cancelled").map((c) => ({ value: c.id, label: `${c.key} · ${c.title}` })),
);

async function save(): Promise<void> {
  errors.value = {};
  if (!minutes.value || minutes.value < 1 || minutes.value > 1440) errors.value.duration = t("projects.time.durationInvalid");
  if (!day.value) errors.value.day = t("projects.time.dayRequired");
  if (Object.keys(errors.value).length) return;
  saving.value = true;
  try {
    await logTime(companyId.value, {
      day: day.value!,
      minutes: minutes.value!,
      project: props.project.id,
      task: task.value,
      note: note.value.trim(),
      billable: billable.value,
      person: person.value && person.value !== me.value ? person.value : null,
    });
    toast.success(t("projects.time.logged", { time: hhmm(minutes.value!) }));
    open.value = false;
    emit("saved");
    void refresh();
  } catch {
    // The HTTP layer showed why.
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <UiDialog v-model:open="open" :title="t('projects.time.logTitle')" :description="taskKey ? t('projects.time.logOnCard', { key: taskKey }) : project.name" size="sm">
    <form id="log-time" class="flex flex-col gap-4" @submit.prevent="save">
      <FormField v-if="project.capabilities.manage && peopleOptions.length" :label="t('projects.time.person')">
        <PersonPicker v-model="person" :people="peopleOptions" :clearable="false" />
      </FormField>
      <div class="grid grid-cols-2 gap-3">
        <FormField :label="t('projects.time.day')" :error="errors.day" required>
          <DatePicker v-model="day" :max="today" />
        </FormField>
        <FormField :label="t('projects.time.duration')" :error="errors.duration" :hint="minutes ? hhmm(minutes) : t('projects.time.durationHint')" required>
          <TextInput v-model="duration" placeholder="1:30" inputmode="decimal" autofocus :invalid="!!errors.duration" />
        </FormField>
      </div>
      <div class="flex flex-wrap gap-1.5">
        <button
          v-for="chip in chips"
          :key="chip"
          type="button"
          class="h-7 rounded-full border px-2.5 text-xs font-semibold tabular-nums transition-colors"
          :class="minutes === chip ? 'border-primary bg-accent-soft text-accent-fg' : 'border-line text-muted hover:bg-highlight'"
          @click="duration = hhmm(chip)"
        >
          {{ chip < 60 ? t("projects.time.minutesShort", { n: chip }) : t("projects.time.hoursShort", { n: chip / 60 }) }}
        </button>
      </div>
      <FormField v-if="!taskId" :label="t('projects.time.card')" optional>
        <SelectBox v-model="task" :options="cardOptions" clearable :placeholder="t('projects.time.wholeProject')" />
      </FormField>
      <FormField :label="t('projects.time.note')" optional>
        <TextInput v-model="note" :maxlength="300" :placeholder="t('projects.time.notePlaceholder')" />
      </FormField>
      <ToggleSwitch v-model="billable" :label="t('projects.time.billable')" :description="t('projects.time.billableHint')" />
    </form>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="primary" type="submit" form="log-time" :loading="saving">{{ t("projects.time.log") }}</UiButton>
    </template>
  </UiDialog>
</template>
