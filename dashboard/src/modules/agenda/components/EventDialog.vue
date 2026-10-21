<script setup lang="ts">
/**
 * Add or change a company event: what and when (one day with times, or all-day days), repeats,
 * where, who comes (with one-tap groups: everyone, a branch, a position), who sees it, when the
 * bot reminds the attendees, and a description. Times are in the company's timezone.
 */
import { Building2, CalendarClock, Eye, Lock, MapPin, Users } from "@lucide/vue";
import { useQueryClient } from "@tanstack/vue-query";
import { computed, watch } from "vue";
import { useI18n } from "vue-i18n";
import { z } from "zod";

import BranchPicker from "@/components/BranchPicker.vue";
import DatePicker from "@/components/DatePicker.vue";
import FormField from "@/components/FormField.vue";
import type { SelectOption } from "@/components/options";
import PersonPicker from "@/components/PersonPicker.vue";
import { useScopedBranches } from "@/components/pickers";
import RadioCards from "@/components/RadioCards.vue";
import SelectBox from "@/components/SelectBox.vue";
import TextArea from "@/components/TextArea.vue";
import TextInput from "@/components/TextInput.vue";
import TimePicker from "@/components/TimePicker.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";
import { todayIn } from "@/lib/dates";
import { useForm } from "@/lib/useForm";
import { useCompanyStore } from "@/stores/company";

import { agendaApi, agendaKeys, useAgendaSettings, useInvitees } from "../api";
import { EVENT_KINDS, KIND_TOKENS, REMIND_OPTIONS, remindKey, tokenColor } from "../lib";
import type { AgendaEvent, EventInput, EventKind, EventRepeat, EventVisibility } from "../types";

const open = defineModel<boolean>("open", { default: false });
const props = withDefaults(defineProps<{ event?: AgendaEvent | null; day?: string | null; time?: string | null }>(), { event: null, day: null, time: null });
const emit = defineEmits<{ saved: [event: AgendaEvent] }>();

const { t } = useI18n();
const company = useCompanyStore();
const client = useQueryClient();
const invitees = useInvitees(open);
const settings = useAgendaSettings();
const branches = useScopedBranches();

const schema = z
  .object({
    title: z.string().trim().min(1, "common.form.required").max(200, "common.form.tooLong"),
    kind: z.enum(["meeting", "training", "inventory", "celebration", "deadline", "other"]),
    allDay: z.boolean(),
    date: z.string().min(10, "common.form.required"),
    endDate: z.string().nullable(),
    startTime: z.string().nullable(),
    endTime: z.string().nullable(),
    repeat: z.enum(["none", "weekly", "monthly"]),
    repeatUntil: z.string().nullable(),
    place: z.string().max(200, "common.form.tooLong"),
    branch: z.number().nullable(),
    attendees: z.array(z.number()),
    visibility: z.enum(["company", "attendees"]),
    remind: z.number().nullable(),
    description: z.string().max(5000, "common.form.tooLong"),
  })
  .refine((v) => v.allDay || !!v.startTime, { message: "common.form.required", path: ["startTime"] })
  .refine((v) => v.allDay || !v.endTime || !v.startTime || v.endTime > v.startTime, { message: "agenda.dialog.endAfterStart", path: ["endTime"] })
  .refine((v) => !v.allDay || !v.endDate || v.endDate >= v.date, { message: "agenda.dialog.endAfterStart", path: ["endDate"] })
  .refine((v) => v.repeat === "none" || !v.repeatUntil || v.repeatUntil >= v.date, { message: "agenda.dialog.untilAfterStart", path: ["repeatUntil"] });

type Values = z.input<typeof schema>;

function blank(): Values {
  return {
    title: "",
    kind: "meeting",
    allDay: false,
    date: props.day ?? todayIn(company.timezone),
    endDate: null,
    startTime: props.time ?? "10:00",
    endTime: props.time ? addHour(props.time) : "11:00",
    repeat: "none",
    repeatUntil: null,
    place: "",
    branch: null,
    attendees: [],
    visibility: "company",
    remind: settings.data.value?.default_remind_before ?? 60,
    description: "",
  };
}

function fromEvent(event: AgendaEvent): Values {
  return {
    title: event.title,
    kind: event.kind,
    allDay: event.all_day,
    date: event.start.slice(0, 10),
    endDate: event.all_day && event.end ? event.end.slice(0, 10) : null,
    startTime: event.all_day ? "10:00" : event.start.slice(11, 16),
    endTime: event.all_day ? "11:00" : (event.end?.slice(11, 16) ?? null),
    repeat: event.repeat,
    repeatUntil: event.repeat_until,
    place: event.place,
    branch: event.branch?.id ?? null,
    attendees: event.attendees.map((attendee) => attendee.member.id),
    visibility: event.visibility,
    remind: event.remind_before,
    description: event.description,
  };
}

function addHour(time: string): string {
  const [h, m] = time.split(":").map(Number);
  return `${String(Math.min(23, (h ?? 0) + 1)).padStart(2, "0")}:${String(m ?? 0).padStart(2, "0")}`;
}

const form = useForm(schema, blank(), {
  onSubmit: async (values) => {
    const input: EventInput = {
      title: values.title,
      description: values.description,
      kind: values.kind as EventKind,
      all_day: values.allDay,
      start: values.allDay ? values.date : `${values.date}T${values.startTime}`,
      end: values.allDay ? (values.endDate && values.endDate !== values.date ? values.endDate : null) : values.endTime ? `${values.date}T${values.endTime}` : null,
      place: values.place,
      branch: values.branch,
      visibility: values.visibility as EventVisibility,
      attendee_ids: values.attendees,
      remind_before: values.remind,
      repeat: values.repeat as EventRepeat,
      repeat_until: values.repeat === "none" ? null : values.repeatUntil,
    };
    const cid = company.currentId ?? 0;
    const saved = props.event ? await agendaApi.update(cid, props.event.id, input) : await agendaApi.create(cid, input);
    client.setQueryData(agendaKeys.event(cid, saved.id), saved);
    void client.invalidateQueries({ queryKey: agendaKeys.all(cid) });
    toast.success(props.event ? t("agenda.dialog.saved") : t("agenda.dialog.created"), {
      description: !props.event && input.attendee_ids.length ? t("agenda.dialog.invitesSent", { n: input.attendee_ids.length }, input.attendee_ids.length) : undefined,
    });
    open.value = false;
    emit("saved", saved);
  },
});

watch(open, (isOpen) => {
  if (isOpen) form.reset(props.event ? fromEvent(props.event) : blank());
});

const people = computed(() => invitees.data.value ?? []);
const personOptions = computed(() => people.value.map((person) => ({ id: person.id, name: person.name, photo_url: person.photo_url, subtitle: person.subtitle })));

/** One-tap groups of attendees. */
const groups = computed(() => {
  const list: Array<{ id: string; label: string; ids: number[] }> = [];
  if (people.value.length) list.push({ id: "all", label: t("agenda.dialog.everyone"), ids: people.value.map((p) => p.id) });
  for (const branch of branches.value) {
    const ids = people.value.filter((p) => p.branch_ids.includes(branch.id)).map((p) => p.id);
    if (ids.length && branches.value.length > 1) list.push({ id: `b${branch.id}`, label: branch.name, ids });
  }
  return list;
});

function addGroup(ids: number[]): void {
  form.values.attendees = Array.from(new Set([...(form.values.attendees as number[]), ...ids]));
}

const kindOptions = computed(() => EVENT_KINDS.map((kind) => ({ value: kind, label: t(`agenda.kind.${kind}`), color: tokenColor(KIND_TOKENS[kind])! })));
const repeatOptions = computed<SelectOption<string>[]>(() => [
  { value: "none", label: t("agenda.repeat.none") },
  { value: "weekly", label: t("agenda.repeat.weekly") },
  { value: "monthly", label: t("agenda.repeat.monthly") },
]);
const remindOptions = computed<SelectOption<number | string>[]>(() =>
  REMIND_OPTIONS.map((minutes) => {
    const { key, n } = remindKey(minutes);
    return { value: minutes === null ? "none" : minutes, label: n !== undefined ? t(key, { n }, n) : t(key) };
  }),
);
const remindValue = computed({
  get: () => (form.values.remind === null ? "none" : (form.values.remind as number)),
  set: (value: number | string | null) => (form.values.remind = value === "none" || value === null ? null : Number(value)),
});
const visibilityOptions = computed(() => [
  { value: "company" as const, label: t("agenda.visibility.company"), description: t("agenda.visibility.companyHint"), icon: Eye },
  { value: "attendees" as const, label: t("agenda.visibility.attendees"), description: t("agenda.visibility.attendeesHint"), icon: Lock },
]);
</script>

<template>
  <UiDialog v-model:open="open" :title="event ? t('agenda.dialog.editTitle') : t('agenda.dialog.newTitle')" size="lg">
    <form id="agenda-event-form" class="flex flex-col gap-4" @submit.prevent="form.submit">
      <FormField :label="t('agenda.dialog.title')" :error="form.errors.title" required>
        <TextInput v-model="form.values.title" :placeholder="t('agenda.dialog.titlePlaceholder')" :maxlength="200" autofocus @blur="form.touch('title')" />
      </FormField>

      <div class="flex flex-wrap gap-1.5" role="radiogroup" :aria-label="t('agenda.dialog.kind')">
        <button
          v-for="option in kindOptions"
          :key="option.value"
          type="button"
          role="radio"
          :aria-checked="form.values.kind === option.value"
          :class="[
            'pressable inline-flex h-8 items-center gap-2 rounded-full border px-3 text-sm font-medium transition-colors',
            form.values.kind === option.value ? 'border-transparent bg-accent-soft text-accent-fg' : 'border-line text-muted hover:bg-highlight hover:text-fg',
          ]"
          @click="form.values.kind = option.value"
        >
          <span class="size-2.5 rounded-full" :style="{ background: option.color }" aria-hidden="true" />
          {{ option.label }}
        </button>
      </div>

      <div class="ui-card flex flex-col gap-4 bg-surface-2/40 p-4 dark:bg-surface-2/60">
        <ToggleSwitch v-model="form.values.allDay" :label="t('agenda.dialog.allDay')" />
        <div class="grid grid-cols-2 gap-3 sm:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)_minmax(0,1fr)]">
          <FormField :label="form.values.allDay ? t('agenda.dialog.from') : t('agenda.dialog.date')" :error="form.errors.date" required class="col-span-2 sm:col-span-1">
            <DatePicker v-model="form.values.date" format="weekday" />
          </FormField>
          <template v-if="form.values.allDay">
            <FormField :label="t('agenda.dialog.to')" :error="form.errors.endDate" optional class="col-span-2">
              <DatePicker v-model="form.values.endDate" :min="form.values.date" clearable :placeholder="t('agenda.dialog.sameDay')" />
            </FormField>
          </template>
          <template v-else>
            <FormField :label="t('agenda.dialog.starts')" :error="form.errors.startTime" required>
              <TimePicker v-model="form.values.startTime" :step="15" />
            </FormField>
            <FormField :label="t('agenda.dialog.ends')" :error="form.errors.endTime">
              <TimePicker v-model="form.values.endTime" :step="15" />
            </FormField>
          </template>
        </div>
        <div class="grid gap-3 sm:grid-cols-2">
          <FormField :label="t('agenda.dialog.repeat')">
            <SelectBox v-model="form.values.repeat" :options="repeatOptions" />
          </FormField>
          <FormField v-if="form.values.repeat !== 'none'" :label="t('agenda.dialog.until')" :error="form.errors.repeatUntil" optional>
            <DatePicker v-model="form.values.repeatUntil" :min="form.values.date" clearable :placeholder="t('agenda.dialog.forever')" />
          </FormField>
        </div>
      </div>

      <div class="grid gap-3 sm:grid-cols-2">
        <FormField :label="t('agenda.dialog.place')" optional>
          <TextInput v-model="form.values.place" :icon="MapPin" :placeholder="t('agenda.dialog.placePlaceholder')" :maxlength="200" />
        </FormField>
        <FormField v-if="branches.length > 1" :label="t('agenda.dialog.branch')" :hint="t('agenda.dialog.branchHint')" optional>
          <BranchPicker v-model="form.values.branch" :branches="branches" :placeholder="t('agenda.dialog.wholeCompany')" />
        </FormField>
      </div>

      <FormField :label="t('agenda.dialog.attendees')" :hint="t('agenda.dialog.attendeesHint')">
        <PersonPicker v-model="form.values.attendees" multiple :people="personOptions" />
        <div v-if="groups.length" class="mt-2 flex flex-wrap items-center gap-1.5">
          <span class="text-xs text-muted">{{ t("agenda.dialog.addGroup") }}</span>
          <button
            v-for="group in groups"
            :key="group.id"
            type="button"
            class="pressable inline-flex h-6 items-center gap-1 rounded-full border border-line px-2 text-xs font-medium text-muted hover:bg-highlight hover:text-fg"
            @click="addGroup(group.ids)"
          >
            <Users v-if="group.id === 'all'" :size="12" />
            <Building2 v-else :size="12" />
            {{ group.label }}
            <span class="tabular-nums text-subtle">{{ group.ids.length }}</span>
          </button>
        </div>
      </FormField>

      <div class="grid gap-3 sm:grid-cols-[minmax(0,1fr)_220px]">
        <FormField :label="t('agenda.dialog.visibility')">
          <RadioCards v-model="form.values.visibility" :options="visibilityOptions" :columns="2" />
        </FormField>
        <FormField :label="t('agenda.dialog.remind')" :hint="t('agenda.dialog.remindHint')">
          <SelectBox v-model="remindValue" :options="remindOptions" />
        </FormField>
      </div>

      <FormField :label="t('agenda.dialog.description')" optional>
        <TextArea v-model="form.values.description" :rows="3" :placeholder="t('agenda.dialog.descriptionPlaceholder')" />
      </FormField>
      <p v-if="form.formError.value" class="text-sm text-danger">{{ form.formError.value }}</p>
    </form>
    <template #footer>
      <span class="mr-auto hidden items-center gap-1.5 text-xs text-muted sm:inline-flex"><CalendarClock :size="13" />{{ t("agenda.dialog.tz", { tz: company.timezone }) }}</span>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="primary" type="submit" form="agenda-event-form" :loading="form.submitting.value">{{ event ? t("common.save") : t("agenda.dialog.create") }}</UiButton>
    </template>
  </UiDialog>
</template>
