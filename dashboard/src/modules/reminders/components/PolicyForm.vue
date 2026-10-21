<script setup lang="ts">
/**
 * The fields of a reminder policy with a live timeline (plan §6.2: "Policy editor with
 * ReminderTimelinePreview … texts per step"): before the deadline, after it, the manager, quiet
 * hours and days, snoozes, and the owner's own wording from a given reminder on, previewed as the
 * Telegram message.
 */
import { MessageSquareText, Plus, Trash2 } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import FormField from "@/components/FormField.vue";
import IconButton from "@/components/IconButton.vue";
import NumberInput from "@/components/NumberInput.vue";
import SelectBox from "@/components/SelectBox.vue";
import TextArea from "@/components/TextArea.vue";
import TextInput from "@/components/TextInput.vue";
import TimePicker from "@/components/TimePicker.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import WeekdayPicker from "@/components/WeekdayPicker.vue";
import { zonedNow } from "@/lib/dates";
import { useCompanyStore } from "@/stores/company";

import { parseClock } from "../schedule";
import type { ReminderText } from "../types";
import ReminderTimelinePreview from "./ReminderTimelinePreview.vue";
import TelegramBubble from "./TelegramBubble.vue";

export interface PolicyDraft {
  name: string;
  heads_up_minutes: number;
  repeat_every_minutes: number;
  max_reminders: number;
  escalate_after: number;
  quiet: boolean;
  quiet_from: string | null;
  quiet_until: string | null;
  quiet_days: number[];
  snooze_minutes: number;
  max_snoozes: number;
  replace_previous: boolean;
  texts: ReminderText[];
}

const draft = defineModel<PolicyDraft>({ required: true });
const props = withDefaults(defineProps<{ errors?: Record<string, string>; hideName?: boolean }>(), { errors: () => ({}), hideName: false });

const { t } = useI18n();
const company = useCompanyStore();
const sampleDue = ref<string | null>("18:00");
const sampleDay = ref((zonedNow(company.timezone).getDay() + 6) % 7);
const dayOptions = computed(() => [0, 1, 2, 3, 4, 5, 6].map((day) => ({ value: day, label: t(`reminders.weekday.${day}`) })));

function set<K extends keyof PolicyDraft>(key: K, value: PolicyDraft[K]): void {
  draft.value = { ...draft.value, [key]: value };
}
const num = (value: number | null, fallback = 0) => (value === null || Number.isNaN(value) ? fallback : value);

const shape = computed(() => ({
  heads_up_minutes: draft.value.heads_up_minutes,
  repeat_every_minutes: draft.value.repeat_every_minutes,
  max_reminders: draft.value.max_reminders,
  escalate_after: draft.value.escalate_after,
  quiet_from: draft.value.quiet ? draft.value.quiet_from : null,
  quiet_until: draft.value.quiet ? draft.value.quiet_until : null,
  quiet_days: draft.value.quiet_days,
}));

const PLACEHOLDERS = ["{name}", "{task}", "{due}", "{late}"] as const;

function setText(index: number, patch: Partial<ReminderText>): void {
  set("texts", draft.value.texts.map((row, i) => (i === index ? { ...row, ...patch } : row)));
}
function addText(): void {
  const next = Math.max(0, ...draft.value.texts.map((row) => row.from_step)) + 1;
  set("texts", [...draft.value.texts, { from_step: next, text: t("reminders.text.starter") }]);
}
function removeText(index: number): void {
  set("texts", draft.value.texts.filter((_, i) => i !== index));
}
function insert(index: number, token: string): void {
  const row = draft.value.texts[index];
  if (!row) return;
  setText(index, { text: `${row.text}${row.text.endsWith(" ") || !row.text ? "" : " "}${token}` });
}
</script>

<template>
  <div class="flex flex-col gap-5">
    <FormField v-if="!hideName" :label="t('reminders.field.name')" :error="props.errors.name" required>
      <TextInput :model-value="draft.name" :maxlength="100" :placeholder="t('reminders.form.namePlaceholder')" @update:model-value="(v) => set('name', v ?? '')" />
    </FormField>

    <!-- Live preview -->
    <section class="rounded-[12px] border border-line bg-surface-2/50 p-3">
      <div class="mb-2 flex flex-wrap items-center gap-2 text-sm text-muted">
        <span class="font-semibold text-fg">{{ t("reminders.form.previewTitle") }}</span>
        <span class="flex-1" />
        <span>{{ t("reminders.form.ifDue") }}</span>
        <SelectBox v-model="sampleDay" :options="dayOptions" size="sm" class="w-[130px]" />
        <TimePicker v-model="sampleDue" :step="30" size="sm" class="w-[96px]" />
      </div>
      <ReminderTimelinePreview :policy="shape" :due="parseClock(sampleDue) ?? 18 * 60" :weekday="sampleDay" />
    </section>

    <section class="grid gap-4 sm:grid-cols-2">
      <FormField :label="t('reminders.field.headsUp')" :hint="t('reminders.form.headsUpHint')" :error="props.errors.heads_up_minutes">
        <NumberInput :model-value="draft.heads_up_minutes" :min="0" :max="1440" :step="5" :suffix="t('reminders.unit.minBefore')" steppers @update:model-value="(v) => set('heads_up_minutes', num(v))" />
      </FormField>
      <FormField :label="t('reminders.field.every')" :hint="t('reminders.form.everyHint')" :error="props.errors.repeat_every_minutes">
        <NumberInput :model-value="draft.repeat_every_minutes" :min="5" :max="1440" :step="5" :suffix="t('reminders.unit.min')" steppers @update:model-value="(v) => set('repeat_every_minutes', num(v, 5))" />
      </FormField>
      <FormField :label="t('reminders.field.maxReminders')" :hint="t('reminders.form.maxHint')" :error="props.errors.max_reminders">
        <NumberInput :model-value="draft.max_reminders" :min="0" :max="100" steppers @update:model-value="(v) => set('max_reminders', num(v))" />
      </FormField>
      <FormField :label="t('reminders.field.escalateAfter')" :hint="t('reminders.form.escalateHint')" :error="props.errors.escalate_after">
        <NumberInput :model-value="draft.escalate_after" :min="0" :max="100" steppers @update:model-value="(v) => set('escalate_after', num(v))" />
      </FormField>
    </section>

    <section class="flex flex-col gap-3 border-t border-line pt-5">
      <ToggleSwitch :model-value="draft.quiet" layout="row" :label="t('reminders.field.quietHours')" :description="t('reminders.form.quietHint')" @update:model-value="(v) => set('quiet', v)" />
      <div v-if="draft.quiet" class="grid grid-cols-2 gap-3 sm:max-w-[320px]">
        <FormField :label="t('reminders.field.quietFrom')"><TimePicker :model-value="draft.quiet_from" :step="30" @update:model-value="(v) => set('quiet_from', v)" /></FormField>
        <FormField :label="t('reminders.field.quietUntil')"><TimePicker :model-value="draft.quiet_until" :step="30" @update:model-value="(v) => set('quiet_until', v)" /></FormField>
      </div>
      <FormField :label="t('reminders.field.quietDays')" :hint="t('reminders.form.quietDaysHint')" :error="props.errors.quiet_days">
        <WeekdayPicker :model-value="draft.quiet_days" size="sm" @update:model-value="(v) => set('quiet_days', v)" />
      </FormField>
    </section>

    <section class="grid gap-4 border-t border-line pt-5 sm:grid-cols-2">
      <FormField :label="t('reminders.field.snooze')" :hint="t('reminders.form.snoozeHint')">
        <NumberInput :model-value="draft.snooze_minutes" :min="5" :max="1440" :step="5" :suffix="t('reminders.unit.min')" steppers @update:model-value="(v) => set('snooze_minutes', num(v, 5))" />
      </FormField>
      <FormField :label="t('reminders.field.maxSnoozes')">
        <NumberInput :model-value="draft.max_snoozes" :min="0" :max="10" steppers @update:model-value="(v) => set('max_snoozes', num(v))" />
      </FormField>
      <ToggleSwitch class="sm:col-span-2" :model-value="draft.replace_previous" layout="row" :label="t('reminders.field.replacePrevious')" :description="t('reminders.form.replaceHint')" @update:model-value="(v) => set('replace_previous', v)" />
    </section>

    <section class="flex flex-col gap-3 border-t border-line pt-5">
      <div>
        <h3 class="flex items-center gap-1.5 text-sm font-semibold text-fg"><MessageSquareText :size="15" />{{ t("reminders.form.textsTitle") }}</h3>
        <p class="mt-0.5 text-sm text-muted">{{ t("reminders.form.textsHint") }}</p>
      </div>
      <p v-if="props.errors.texts" class="text-sm text-danger">{{ props.errors.texts }}</p>
      <div v-for="(row, index) in draft.texts" :key="index" class="grid gap-3 rounded-[12px] border border-line p-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,300px)]">
        <div class="flex min-w-0 flex-col gap-2">
          <div class="flex items-center gap-2 text-sm text-muted">
            <span>{{ t("reminders.text.fromStep") }}</span>
            <NumberInput :model-value="row.from_step" :min="1" :max="100" size="sm" class="w-[92px]" @update:model-value="(v) => setText(index, { from_step: num(v, 1) })" />
            <span class="flex-1" />
            <IconButton :icon="Trash2" :label="t('reminders.text.remove')" size="sm" @click="removeText(index)" />
          </div>
          <TextArea :model-value="row.text" :rows="2" :maxlength="1000" @update:model-value="(v) => setText(index, { text: v ?? '' })" />
          <div class="flex flex-wrap items-center gap-1.5">
            <span class="text-xs text-subtle">{{ t("reminders.text.insert") }}</span>
            <button
              v-for="token in PLACEHOLDERS"
              :key="token"
              type="button"
              class="pressable rounded-full border border-line bg-surface px-2 py-0.5 font-mono text-[11px] text-muted transition-colors hover:border-primary hover:text-fg"
              :title="t(`reminders.placeholder.${token.slice(1, -1)}`)"
              @click="insert(index, token)"
            >
              {{ token }}
            </button>
          </div>
        </div>
        <div class="min-w-0 rounded-[12px] bg-[color-mix(in_srgb,var(--c-info)_10%,var(--c-surface-2))] p-3">
          <TelegramBubble :text="row.text" :step="row.from_step" :snooze="draft.max_snoozes ? draft.snooze_minutes : null" :time="sampleDue ?? '18:00'" />
        </div>
      </div>
      <button
        v-if="draft.texts.length < 12"
        type="button"
        class="flex h-9 items-center gap-1.5 self-start rounded-[8px] border border-dashed border-line-strong px-3 text-sm font-medium text-muted transition-colors hover:border-primary hover:text-fg"
        @click="addText"
      >
        <Plus :size="15" />{{ t("reminders.text.add") }}
      </button>
    </section>
  </div>
</template>
