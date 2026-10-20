<script setup lang="ts">
/**
 * Schedules (plan §6.2 "Schedules editor"): every work schedule as a card with its week at a glance
 * (or its rotation), weekly hours and who follows it; people without a schedule with a quick assign;
 * and the shift templates the roster builder offers. Assigning regenerates the next 14 days.
 */
import { Archive, CalendarClock, Ellipsis, Pencil, Plus, Shapes, Trash2, UserPlus, Users } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import AvatarStack from "@/components/AvatarStack.vue";
import DatePicker from "@/components/DatePicker.vue";
import DropdownMenu from "@/components/DropdownMenu.vue";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import FormField from "@/components/FormField.vue";
import IconButton from "@/components/IconButton.vue";
import NumberInput from "@/components/NumberInput.vue";
import PageSection from "@/components/PageSection.vue";
import PersonPicker from "@/components/PersonPicker.vue";
import type { PersonOption } from "@/components/pickers";
import ResponsiveGrid from "@/components/ResponsiveGrid.vue";
import SelectBox from "@/components/SelectBox.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import TextInput from "@/components/TextInput.vue";
import TimePicker from "@/components/TimePicker.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { todayIn } from "@/lib/dates";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { archiveSchedule, assignSchedule, removeTemplate, saveTemplate, unassignSchedule, useCompanyId, useRefresh, useSchedules, useStaff, useTemplates } from "../api";
import AttendanceHeader from "../components/AttendanceHeader.vue";
import ScheduleEditor from "../components/ScheduleEditor.vue";
import { slotColor } from "../lib";
import type { Schedule, ShiftTemplate } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const companyId = useCompanyId();
const confirm = useConfirm();
const refresh = useRefresh();

const schedules = useSchedules();
const staff = useStaff();
const templates = useTemplates();
const skeleton = useDelayedPending(computed(() => schedules.isPending.value));

const people = computed(() => staff.data.value ?? []);
const byId = computed(() => new Map(people.value.map((person) => [person.id, person])));
const unassigned = computed(() => people.value.filter((person) => !person.schedule));
const pickerPeople = computed<PersonOption[]>(() =>
  people.value.map((person) => ({
    id: person.id,
    name: person.name,
    photo_url: person.photo_url,
    subtitle: [person.position?.name, person.home_branch?.name].filter(Boolean).join(" · ") || undefined,
  })),
);

function weekCells(schedule: Schedule) {
  return Array.from({ length: 7 }, (_, weekday) => {
    const day = schedule.days.find((row) => row.weekday === weekday);
    return { weekday, label: day ? `${day.starts_at.slice(0, 2)}–${day.ends_at.slice(0, 2)}` : "", on: !!day };
  });
}

function stackOf(schedule: Schedule) {
  return schedule.member_ids.map((id) => byId.value.get(id)).filter((person) => !!person).map((person) => ({ id: person!.id, name: person!.name, photo_url: person!.photo_url }));
}

// Editing -------------------------------------------------------------------------------

const editorOpen = ref(false);
const editing = ref<Schedule | null>(null);

function openEditor(schedule: Schedule | null): void {
  editing.value = schedule;
  editorOpen.value = true;
}

async function archive(schedule: Schedule): Promise<void> {
  const answer = await confirm({
    title: t("attendance.schedules.archiveTitle", { name: schedule.name }),
    message: t("attendance.schedules.archiveBody", { n: schedule.member_ids.length }),
    confirmLabel: t("attendance.schedules.archive"),
    tone: "danger",
    icon: Archive,
  });
  if (!answer) return;
  try {
    await archiveSchedule(companyId.value, schedule.id);
    toast.success(t("attendance.schedules.archived"));
    refresh();
  } catch {
    // Shown by the HTTP client.
  }
}

const menuFor = (schedule: Schedule) => [
  { label: t("common.edit"), icon: Pencil, onSelect: () => openEditor(schedule) },
  { label: t("attendance.schedules.assign"), icon: UserPlus, onSelect: () => openAssign(schedule) },
  { type: "separator" as const },
  { label: t("attendance.schedules.archive"), icon: Archive, danger: true, onSelect: () => void archive(schedule) },
];

// Assigning -----------------------------------------------------------------------------

const assignOpen = ref(false);
const assignTarget = ref<Schedule | null>(null);
const assignIds = ref<number[]>([]);
const assignFrom = ref<string | null>(null);
const assigning = ref(false);

function openAssign(schedule: Schedule): void {
  assignTarget.value = schedule;
  assignIds.value = [...schedule.member_ids];
  assignFrom.value = todayIn(company.timezone);
  assignOpen.value = true;
}

async function saveAssign(): Promise<void> {
  const schedule = assignTarget.value;
  if (!schedule) return;
  const added = assignIds.value.filter((id) => !schedule.member_ids.includes(id));
  const removed = schedule.member_ids.filter((id) => !assignIds.value.includes(id));
  assigning.value = true;
  try {
    if (added.length) await assignSchedule(companyId.value, schedule.id, added, assignFrom.value);
    if (removed.length) await unassignSchedule(companyId.value, removed);
    toast.success(t("attendance.schedules.assigned", { n: assignIds.value.length }));
    refresh();
    assignOpen.value = false;
  } catch {
    // Shown by the HTTP client.
  } finally {
    assigning.value = false;
  }
}

const scheduleOptions = computed(() => (schedules.data.value ?? []).map((schedule) => ({ value: schedule.id, label: schedule.name, color: slotColor(schedule.color) })));

async function quickAssign(memberId: number, scheduleId: number | null): Promise<void> {
  if (!scheduleId) return;
  try {
    await assignSchedule(companyId.value, scheduleId, [memberId]);
    toast.success(t("attendance.schedules.assignedOne", { name: byId.value.get(memberId)?.name ?? "" }));
    refresh();
  } catch {
    // Shown by the HTTP client.
  }
}

// Templates -----------------------------------------------------------------------------

const templateOpen = ref(false);
const templateTarget = ref<ShiftTemplate | null>(null);
const templateForm = ref({ name: "", start: "09:00", end: "18:00", pause: 60 as number | null, color: 1 });
const savingTemplate = ref(false);

function openTemplate(template: ShiftTemplate | null): void {
  templateTarget.value = template;
  templateForm.value = template
    ? { name: template.name, start: template.starts_at, end: template.ends_at, pause: template.break_minutes, color: template.color }
    : { name: "", start: "09:00", end: "18:00", pause: 60, color: 2 };
  templateOpen.value = true;
}

async function submitTemplate(): Promise<void> {
  const form = templateForm.value;
  if (!form.name.trim()) return;
  savingTemplate.value = true;
  try {
    await saveTemplate(companyId.value, { name: form.name.trim(), starts_at: form.start, ends_at: form.end, break_minutes: form.pause ?? 0, color: form.color }, templateTarget.value?.id);
    toast.success(t("attendance.templates.saved"));
    refresh();
    templateOpen.value = false;
  } catch {
    // Shown by the HTTP client.
  } finally {
    savingTemplate.value = false;
  }
}

async function dropTemplate(template: ShiftTemplate): Promise<void> {
  const answer = await confirm({ title: t("attendance.templates.removeTitle", { name: template.name }), confirmLabel: t("common.delete"), tone: "danger" });
  if (!answer) return;
  try {
    await removeTemplate(companyId.value, template.id);
    refresh();
  } catch {
    // Shown by the HTTP client.
  }
}
</script>

<template>
  <div class="flex flex-col gap-6">
    <AttendanceHeader :title="t('attendance.schedules.title')" :description="t('attendance.schedules.description')">
      <template #actions>
        <UiButton variant="primary" :icon="Plus" @click="openEditor(null)">{{ t("attendance.schedules.new") }}</UiButton>
      </template>
    </AttendanceHeader>

    <div v-if="skeleton">
      <ResponsiveGrid min="320px">
        <SkeletonBlock v-for="n in 4" :key="n" height="176px" radius="12px" />
      </ResponsiveGrid>
    </div>
    <ErrorState v-else-if="schedules.isError.value" :error="schedules.error.value" :retry="() => schedules.refetch()" />
    <EmptyState v-else-if="schedules.data.value && !schedules.data.value.length" size="lg" :icon="CalendarClock" :title="t('attendance.schedules.emptyTitle')" :description="t('attendance.schedules.emptyBody')">
      <UiButton variant="primary" :icon="Plus" @click="openEditor(null)">{{ t("attendance.schedules.new") }}</UiButton>
    </EmptyState>
    <ResponsiveGrid v-else-if="schedules.data.value" min="320px">
      <article v-for="schedule in schedules.data.value" :key="schedule.id" class="ui-card relative flex min-w-0 flex-col gap-4 overflow-hidden p-4 pl-5">
        <span class="absolute inset-y-0 left-0 w-1" :style="{ background: slotColor(schedule.color) }" aria-hidden="true" />
        <header class="flex items-start gap-2">
          <div class="min-w-0 flex-1">
            <h3 class="truncate text-base font-semibold text-fg">{{ schedule.name }}</h3>
            <div class="mt-1 flex flex-wrap items-center gap-1.5">
              <StatusPill size="sm" :tone="schedule.kind === 'flexible' ? 'neutral' : schedule.kind === 'rotating' ? 'info' : 'primary'" :label="t(`attendance.kind.${schedule.kind}`)" />
              <span v-if="schedule.weekly_minutes" class="text-xs text-muted">{{ t("attendance.schedules.perWeek", { d: fmt.duration(schedule.weekly_minutes) }) }}</span>
            </div>
          </div>
          <DropdownMenu :items="menuFor(schedule)">
            <template #trigger><IconButton :icon="Ellipsis" :label="t('common.more')" size="sm" /></template>
          </DropdownMenu>
        </header>

        <div v-if="schedule.kind === 'weekly'" class="grid grid-cols-7 gap-1">
          <div v-for="cell in weekCells(schedule)" :key="cell.weekday" :class="['flex flex-col items-center gap-0.5 rounded-[7px] py-1.5', cell.on ? 'bg-accent-soft text-accent-fg' : 'bg-surface-2 text-subtle']">
            <span class="text-[10px] font-semibold uppercase">{{ t(`common.weekday.min.${cell.weekday}`) }}</span>
            <span class="text-[10px] tabular-nums">{{ cell.label || "—" }}</span>
          </div>
        </div>
        <div v-else-if="schedule.kind === 'rotating'" class="flex flex-col gap-2">
          <div class="flex flex-wrap gap-1">
            <span v-for="(char, index) in schedule.rotation.split('')" :key="index" :class="['grid size-6 place-items-center rounded-[6px] text-[10px] font-bold', char === 'W' ? 'bg-primary text-on-primary' : 'bg-surface-2 text-muted']">
              {{ char === "W" ? t("attendance.schedules.workShort") : t("attendance.schedules.offShort") }}
            </span>
          </div>
          <p class="text-xs text-muted tabular-nums">{{ schedule.rotation_starts_at }}–{{ schedule.rotation_ends_at }} · {{ t("attendance.schedules.since", { day: schedule.rotation_start ? fmt.day(schedule.rotation_start, "short") : "—" }) }}</p>
        </div>
        <p v-else class="rounded-[8px] bg-surface-2 px-3 py-2 text-xs text-muted">{{ t("attendance.schedules.flexibleCard") }}</p>

        <footer class="mt-auto flex items-center gap-2 border-t border-line pt-3">
          <AvatarStack v-if="stackOf(schedule).length" :people="stackOf(schedule)" :max="5" />
          <span class="text-xs text-muted">{{ t("attendance.schedules.people", { n: schedule.member_ids.length }) }}</span>
          <span class="flex-1" />
          <UiButton size="sm" variant="ghost" :icon="UserPlus" @click="openAssign(schedule)">{{ t("attendance.schedules.assign") }}</UiButton>
        </footer>
      </article>
    </ResponsiveGrid>

    <PageSection :title="t('attendance.schedules.unassigned')" :description="t('attendance.schedules.unassignedHint')" :count="unassigned.length" variant="card" flush>
      <ul v-if="unassigned.length" class="divide-y divide-line">
        <li v-for="person in unassigned" :key="person.id" class="flex flex-wrap items-center gap-3 px-4 py-2.5">
          <UserAvatar :name="person.name" :src="person.photo_url" :size="30" />
          <div class="min-w-0 flex-1">
            <p class="truncate text-sm font-medium text-fg">{{ person.name }}</p>
            <p class="truncate text-xs text-muted">{{ [person.position?.name, person.home_branch?.name].filter(Boolean).join(" · ") }}</p>
          </div>
          <SelectBox :model-value="null" :options="scheduleOptions" size="sm" :placeholder="t('attendance.schedules.pick')" class="w-56" @update:model-value="(value) => quickAssign(person.id, value as number | null)" />
        </li>
      </ul>
      <EmptyState v-else size="sm" tone="success" :icon="Users" :title="t('attendance.schedules.allAssigned')" />
    </PageSection>

    <PageSection :title="t('attendance.templates.title')" :description="t('attendance.templates.hint')" variant="card">
      <template #actions><UiButton size="sm" :icon="Plus" @click="openTemplate(null)">{{ t("attendance.templates.new") }}</UiButton></template>
      <div v-if="templates.data.value?.length" class="flex flex-wrap gap-2">
        <div v-for="template in templates.data.value" :key="template.id" class="group inline-flex items-center gap-2 rounded-full border border-line bg-surface py-1 pl-3 pr-1 text-sm">
          <span class="size-2.5 rounded-full" :style="{ background: slotColor(template.color) }" aria-hidden="true" />
          <span class="font-medium text-fg">{{ template.name }}</span>
          <span class="tabular-nums text-muted">{{ template.starts_at }}–{{ template.ends_at }}</span>
          <IconButton :icon="Pencil" :label="t('common.edit')" size="sm" @click="openTemplate(template)" />
          <IconButton :icon="Trash2" :label="t('common.delete')" size="sm" @click="dropTemplate(template)" />
        </div>
      </div>
      <EmptyState v-else size="sm" tone="neutral" :icon="Shapes" :title="t('attendance.templates.empty')" />
    </PageSection>

    <ScheduleEditor v-model:open="editorOpen" :schedule="editing" />

    <UiDialog v-model:open="assignOpen" :title="t('attendance.schedules.assignTitle', { name: assignTarget?.name ?? '' })" :description="t('attendance.schedules.assignHint')" size="md">
      <div class="flex flex-col gap-4">
        <FormField :label="t('attendance.schedules.whoFollows')">
          <PersonPicker v-model="assignIds" multiple :people="pickerPeople" />
        </FormField>
        <FormField :label="t('attendance.schedules.from')" :hint="t('attendance.schedules.fromHint')">
          <DatePicker v-model="assignFrom" />
        </FormField>
      </div>
      <template #footer>
        <UiButton variant="ghost" @click="assignOpen = false">{{ t("common.cancel") }}</UiButton>
        <UiButton variant="primary" :loading="assigning" @click="saveAssign">{{ t("common.save") }}</UiButton>
      </template>
    </UiDialog>

    <UiDialog v-model:open="templateOpen" :title="templateTarget ? t('attendance.templates.editTitle') : t('attendance.templates.newTitle')" size="sm">
      <form class="flex flex-col gap-3" @submit.prevent="submitTemplate">
        <FormField :label="t('attendance.templates.name')" required><TextInput v-model="templateForm.name" :maxlength="60" /></FormField>
        <div class="grid grid-cols-2 gap-3">
          <FormField :label="t('attendance.roster.start')"><TimePicker v-model="templateForm.start" :step="15" /></FormField>
          <FormField :label="t('attendance.roster.end')"><TimePicker v-model="templateForm.end" :step="15" /></FormField>
        </div>
        <FormField :label="t('attendance.roster.break')"><NumberInput v-model="templateForm.pause" :min="0" :max="480" :step="15" :suffix="t('attendance.unit.min')" /></FormField>
        <div class="flex gap-2">
          <button
            v-for="slot in 8"
            :key="slot"
            type="button"
            :class="['size-6 rounded-full border-2', templateForm.color === slot ? 'border-fg' : 'border-transparent']"
            :style="{ background: slotColor(slot) }"
            :aria-label="t('attendance.schedules.colorN', { n: slot })"
            @click="templateForm.color = slot"
          />
        </div>
      </form>
      <template #footer>
        <UiButton variant="ghost" @click="templateOpen = false">{{ t("common.cancel") }}</UiButton>
        <UiButton variant="primary" :loading="savingTemplate" :disabled="!templateForm.name.trim()" @click="submitTemplate">{{ t("common.save") }}</UiButton>
      </template>
    </UiDialog>
  </div>
</template>
