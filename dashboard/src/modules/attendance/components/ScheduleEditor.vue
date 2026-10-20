<script setup lang="ts">
/**
 * Create or change a work schedule in a drawer: weekly hours per weekday, a rotation such as 2/2
 * (W for a work day, O for a day off) with its first day, or flexible hours (no shifts generated).
 * Saving regenerates the untouched future shifts of the people who follow it.
 */
import { Copy, Minus, Plus } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import DatePicker from "@/components/DatePicker.vue";
import FormField from "@/components/FormField.vue";
import IconButton from "@/components/IconButton.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import NumberInput from "@/components/NumberInput.vue";
import RadioCards from "@/components/RadioCards.vue";
import TextInput from "@/components/TextInput.vue";
import TimePicker from "@/components/TimePicker.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import UiButton from "@/components/UiButton.vue";
import UiDrawer from "@/components/UiDrawer.vue";
import { toast } from "@/components/useToast";
import { todayIn } from "@/lib/dates";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { createSchedule, updateSchedule, useCompanyId, useRefresh } from "../api";
import { slotColor, spanMinutes } from "../lib";
import type { Schedule, ScheduleInput, ScheduleKind } from "../types";

const open = defineModel<boolean>("open", { default: false });
const props = defineProps<{ schedule: Schedule | null }>();

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const companyId = useCompanyId();
const refresh = useRefresh();

interface DayRow {
  on: boolean;
  start: string;
  end: string;
  pause: number | null;
}

const name = ref("");
const kind = ref<ScheduleKind>("weekly");
const color = ref(1);
const days = ref<DayRow[]>([]);
const rotation = ref("WWOO");
const rotationStart = ref<string | null>(null);
const rotationHours = ref({ start: "09:00", end: "21:00", pause: 60 as number | null });
const saving = ref(false);
const nameError = ref<string | null>(null);

function blankDays(): DayRow[] {
  return Array.from({ length: 7 }, (_, index) => ({ on: index < 6, start: "09:00", end: "18:00", pause: 60 }));
}

watch(
  () => [open.value, props.schedule] as const,
  ([isOpen, schedule]) => {
    if (!isOpen) return;
    name.value = schedule?.name ?? "";
    kind.value = schedule?.kind ?? "weekly";
    color.value = schedule?.color ?? 1;
    const rows = blankDays().map((row) => ({ ...row, on: !schedule }));
    if (schedule) {
      for (const day of schedule.days) rows[day.weekday] = { on: true, start: day.starts_at, end: day.ends_at, pause: day.break_minutes };
    } else {
      rows.forEach((row, index) => (row.on = index < 6));
    }
    days.value = rows;
    rotation.value = schedule?.rotation || "WWOO";
    rotationStart.value = schedule?.rotation_start ?? todayIn(company.timezone);
    rotationHours.value = {
      start: schedule?.rotation_starts_at ?? "09:00",
      end: schedule?.rotation_ends_at ?? "21:00",
      pause: schedule?.rotation_break_minutes ?? 60,
    };
    nameError.value = null;
  },
  { immediate: true },
);

const PRESETS = [
  { label: "2/2", value: "WWOO" },
  { label: "3/3", value: "WWWOOO" },
  { label: "5/2", value: "WWWWWOO" },
  { label: "1/3", value: "WOOO" },
];

const weeklyMinutes = computed(() =>
  days.value.reduce((sum, row) => (row.on ? sum + spanMinutes(row.start, row.end, row.pause ?? 0) : sum), 0),
);

function copyMonday(): void {
  const first = days.value[0];
  if (!first) return;
  days.value = days.value.map((row, index) => (index === 0 || !row.on ? row : { ...row, start: first.start, end: first.end, pause: first.pause }));
}

function toggleRotation(index: number): void {
  const chars = rotation.value.split("");
  chars[index] = chars[index] === "W" ? "O" : "W";
  rotation.value = chars.join("");
}

function resizeRotation(delta: number): void {
  if (delta > 0 && rotation.value.length < 31) rotation.value += "O";
  if (delta < 0 && rotation.value.length > 2) rotation.value = rotation.value.slice(0, -1);
}

async function save(): Promise<void> {
  if (!name.value.trim()) {
    nameError.value = t("common.form.required");
    return;
  }
  const body: ScheduleInput = {
    name: name.value.trim(),
    kind: kind.value,
    color: color.value,
    days:
      kind.value === "weekly"
        ? days.value.flatMap((row, weekday) => (row.on ? [{ weekday, starts_at: row.start, ends_at: row.end, break_minutes: row.pause ?? 0 }] : []))
        : [],
    rotation: kind.value === "rotating" ? rotation.value : "",
    rotation_start: kind.value === "rotating" ? rotationStart.value : null,
    rotation_starts_at: kind.value === "rotating" ? rotationHours.value.start : null,
    rotation_ends_at: kind.value === "rotating" ? rotationHours.value.end : null,
    rotation_break_minutes: rotationHours.value.pause ?? 0,
  };
  saving.value = true;
  try {
    if (props.schedule) await updateSchedule(companyId.value, props.schedule.id, body);
    else await createSchedule(companyId.value, body);
    toast.success(props.schedule ? t("attendance.schedules.saved") : t("attendance.schedules.created"));
    refresh();
    open.value = false;
  } catch {
    // The HTTP client shows the server's message.
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <UiDrawer v-model:open="open" size="lg" :title="schedule ? t('attendance.schedules.editTitle') : t('attendance.schedules.newTitle')" :description="t('attendance.schedules.editorHint')">
    <form class="flex flex-col gap-5" @submit.prevent="save">
      <FormField :label="t('attendance.schedules.name')" :error="nameError" required>
        <TextInput v-model="name" :maxlength="100" :placeholder="t('attendance.schedules.namePlaceholder')" autofocus />
      </FormField>

      <div class="flex flex-col gap-2">
        <span class="text-sm font-medium text-fg">{{ t("attendance.schedules.kind") }}</span>
        <RadioCards
          v-model="kind"
          :columns="3"
          :options="[
            { value: 'weekly', label: t('attendance.kind.weekly'), description: t('attendance.kind.weeklyHint') },
            { value: 'rotating', label: t('attendance.kind.rotating'), description: t('attendance.kind.rotatingHint') },
            { value: 'flexible', label: t('attendance.kind.flexible'), description: t('attendance.kind.flexibleHint') },
          ]"
        />
      </div>

      <div class="flex flex-col gap-2">
        <span class="text-sm font-medium text-fg">{{ t("attendance.schedules.color") }}</span>
        <div class="flex gap-2">
          <button
            v-for="slot in 8"
            :key="slot"
            type="button"
            :class="['size-7 rounded-full border-2 transition-transform hover:scale-110', color === slot ? 'border-fg' : 'border-transparent']"
            :style="{ background: slotColor(slot) }"
            :aria-label="t('attendance.schedules.colorN', { n: slot })"
            :aria-pressed="color === slot"
            @click="color = slot"
          />
        </div>
      </div>

      <section v-if="kind === 'weekly'" class="flex flex-col gap-2">
        <div class="flex items-center justify-between">
          <span class="text-sm font-medium text-fg">{{ t("attendance.schedules.hours") }}</span>
          <UiButton size="sm" variant="ghost" :icon="Copy" @click="copyMonday">{{ t("attendance.schedules.copyMonday") }}</UiButton>
        </div>
        <div class="ui-card divide-y divide-line">
          <div v-for="(row, index) in days" :key="index" class="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3 px-3 py-2 sm:grid-cols-[140px_1fr]">
            <ToggleSwitch v-model="row.on" :label="t(`common.weekday.long.${index}`)" size="sm" />
            <div v-if="row.on" class="col-span-2 flex flex-wrap items-center gap-2 sm:col-span-1 sm:justify-end">
              <TimePicker v-model="row.start" :step="15" size="sm" class="w-24" />
              <span class="text-subtle">–</span>
              <TimePicker v-model="row.end" :step="15" size="sm" class="w-24" />
              <NumberInput v-model="row.pause" :min="0" :max="480" :step="15" size="sm" :suffix="t('attendance.schedules.breakSuffix')" class="w-32" />
            </div>
            <span v-else class="text-right text-xs text-subtle sm:text-left">{{ t("attendance.schedules.dayOff") }}</span>
          </div>
        </div>
        <p class="text-xs text-muted">{{ t("attendance.schedules.weekTotal", { d: fmt.duration(weeklyMinutes) }) }}</p>
      </section>

      <section v-else-if="kind === 'rotating'" class="flex flex-col gap-3">
        <div class="flex flex-col gap-2">
          <div class="flex flex-wrap items-center justify-between gap-2">
            <span class="text-sm font-medium text-fg">{{ t("attendance.schedules.pattern") }}</span>
            <div class="flex gap-1">
              <button v-for="preset in PRESETS" :key="preset.value" type="button" :class="['rounded-full border px-2.5 py-0.5 text-xs font-semibold', rotation === preset.value ? 'border-primary bg-accent-soft text-accent-fg' : 'border-line text-muted hover:bg-highlight']" @click="rotation = preset.value">
                {{ preset.label }}
              </button>
            </div>
          </div>
          <div class="flex flex-wrap items-center gap-1.5">
            <button
              v-for="(char, index) in rotation.split('')"
              :key="index"
              type="button"
              :class="['grid size-9 place-items-center rounded-[8px] text-xs font-bold transition-colors', char === 'W' ? 'bg-primary text-on-primary' : 'bg-surface-2 text-muted']"
              :aria-label="char === 'W' ? t('attendance.schedules.workDayN', { n: index + 1 }) : t('attendance.schedules.offDayN', { n: index + 1 })"
              @click="toggleRotation(index)"
            >
              {{ char === "W" ? t("attendance.schedules.workShort") : t("attendance.schedules.offShort") }}
            </button>
            <IconButton size="sm" :icon="Minus" :label="t('attendance.schedules.shorter')" @click="resizeRotation(-1)" />
            <IconButton size="sm" :icon="Plus" :label="t('attendance.schedules.longer')" @click="resizeRotation(1)" />
          </div>
          <p class="text-xs text-muted">{{ t("attendance.schedules.patternHint") }}</p>
        </div>
        <div class="grid gap-3 sm:grid-cols-4">
          <FormField :label="t('attendance.schedules.firstDay')" class="sm:col-span-2"><DatePicker v-model="rotationStart" /></FormField>
          <FormField :label="t('attendance.roster.start')"><TimePicker v-model="rotationHours.start" :step="15" /></FormField>
          <FormField :label="t('attendance.roster.end')"><TimePicker v-model="rotationHours.end" :step="15" /></FormField>
        </div>
        <FormField :label="t('attendance.roster.break')" class="max-w-48"><NumberInput v-model="rotationHours.pause" :min="0" :max="480" :step="15" :suffix="t('attendance.unit.min')" /></FormField>
      </section>

      <InlineAlert v-else tone="info" :title="t('attendance.kind.flexible')" :description="t('attendance.schedules.flexibleBody')" />
    </form>
    <template #footer>
      <div class="flex w-full justify-end gap-2">
        <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
        <UiButton variant="primary" :loading="saving" @click="save">{{ schedule ? t("common.save") : t("common.create") }}</UiButton>
      </div>
    </template>
  </UiDrawer>
</template>
