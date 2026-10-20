<script setup lang="ts">
/**
 * Attendance settings (the `attendance` panel of Settings, and the gear on the attendance pages):
 * how people check in, the grace and alert timings, swaps and the "tasks follow shifts" switch.
 * Saves only what changed; the server audits it.
 */
import { Clock3, MapPin, Repeat2, ListChecks } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import ErrorState from "@/components/ErrorState.vue";
import FormField from "@/components/FormField.vue";
import NumberInput from "@/components/NumberInput.vue";
import RadioCards from "@/components/RadioCards.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StickyActionBar from "@/components/StickyActionBar.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import UiButton from "@/components/UiButton.vue";
import { toast } from "@/components/useToast";

import { saveSettings, useCompanyId, useRefresh, useSettings } from "../api";
import type { AttendanceSettings } from "../types";

const { t } = useI18n();
const companyId = useCompanyId();
const refresh = useRefresh();
const query = useSettings();
const draft = ref<AttendanceSettings | null>(null);
const saving = ref(false);

watch(
  () => query.data.value,
  (value) => {
    if (value) draft.value = { ...value };
  },
  { immediate: true },
);

const changes = computed<Partial<AttendanceSettings>>(() => {
  const base = query.data.value;
  const next = draft.value;
  if (!base || !next) return {};
  const out: Partial<AttendanceSettings> = {};
  for (const key of Object.keys(next) as Array<keyof AttendanceSettings>) {
    if (next[key] !== base[key]) (out as Record<string, unknown>)[key] = next[key];
  }
  return out;
});
const dirty = computed(() => Object.keys(changes.value).length > 0);

async function save(): Promise<void> {
  if (!dirty.value) return;
  saving.value = true;
  try {
    await saveSettings(companyId.value, changes.value);
    toast.success(t("attendance.settings.saved"));
    refresh();
  } catch {
    // Field errors and the toast come from the HTTP client.
  } finally {
    saving.value = false;
  }
}

function reset(): void {
  if (query.data.value) draft.value = { ...query.data.value };
}

const minutes = (n: number) => t("attendance.settings.minutes", { n });
</script>

<template>
  <div class="flex flex-col gap-6 pb-16">
    <div v-if="query.isPending.value" class="flex flex-col gap-4">
      <SkeletonBlock v-for="n in 4" :key="n" height="64px" radius="12px" />
    </div>
    <ErrorState v-else-if="query.isError.value" :error="query.error.value" :retry="() => query.refetch()" />
    <template v-else-if="draft">
      <section class="flex flex-col gap-3">
        <h3 class="flex items-center gap-2 text-sm font-semibold text-fg"><MapPin :size="15" class="text-subtle" />{{ t("attendance.settings.checkIn") }}</h3>
        <div class="ui-card flex flex-col divide-y divide-line">
          <ToggleSwitch v-model="draft.require_location" layout="row" class="p-3" :label="t('attendance.settings.requireLocation')" :description="t('attendance.settings.requireLocationHint')" />
          <ToggleSwitch v-model="draft.require_photo" layout="row" class="p-3" :label="t('attendance.settings.requirePhoto')" :description="t('attendance.settings.requirePhotoHint')" />
          <div class="flex flex-col gap-2 p-3">
            <p class="text-sm font-medium text-fg">{{ t("attendance.settings.outside") }}</p>
            <RadioCards
              v-model="draft.outside_action"
              :columns="2"
              :options="[
                { value: 'flag', label: t('attendance.settings.outsideFlag'), description: t('attendance.settings.outsideFlagHint') },
                { value: 'reject', label: t('attendance.settings.outsideReject'), description: t('attendance.settings.outsideRejectHint') },
              ]"
            />
          </div>
          <FormField class="p-3" :label="t('attendance.settings.maxAccuracy')" :hint="t('attendance.settings.maxAccuracyHint')" layout="inline">
            <NumberInput v-model="draft.max_accuracy_m" :min="10" :max="5000" :step="10" :suffix="t('attendance.unit.m')" class="w-36" />
          </FormField>
        </div>
      </section>

      <section class="flex flex-col gap-3">
        <h3 class="flex items-center gap-2 text-sm font-semibold text-fg"><Clock3 :size="15" class="text-subtle" />{{ t("attendance.settings.timing") }}</h3>
        <div class="ui-card grid divide-y divide-line">
          <FormField class="p-3" layout="inline" :label="t('attendance.settings.grace')" :hint="t('attendance.settings.graceHint')">
            <NumberInput v-model="draft.grace_minutes" :min="0" :max="240" :suffix="minutes(draft.grace_minutes)" class="w-40" />
          </FormField>
          <FormField class="p-3" layout="inline" :label="t('attendance.settings.earlyLeave')" :hint="t('attendance.settings.earlyLeaveHint')">
            <NumberInput v-model="draft.early_leave_grace_minutes" :min="0" :max="240" :suffix="minutes(draft.early_leave_grace_minutes)" class="w-40" />
          </FormField>
          <FormField class="p-3" layout="inline" :label="t('attendance.settings.preShift')" :hint="t('attendance.settings.preShiftHint')">
            <NumberInput v-model="draft.pre_shift_reminder_minutes" :min="0" :max="240" :step="5" :suffix="minutes(draft.pre_shift_reminder_minutes)" class="w-40" />
          </FormField>
          <FormField class="p-3" layout="inline" :label="t('attendance.settings.remind')" :hint="t('attendance.settings.remindHint')">
            <NumberInput v-model="draft.remind_after_minutes" :min="0" :max="240" :step="5" :suffix="minutes(draft.remind_after_minutes)" class="w-40" />
          </FormField>
          <FormField class="p-3" layout="inline" :label="t('attendance.settings.noShow')" :hint="t('attendance.settings.noShowHint')">
            <NumberInput v-model="draft.no_show_alert_minutes" :min="0" :max="480" :step="5" :suffix="minutes(draft.no_show_alert_minutes)" class="w-40" />
          </FormField>
          <FormField class="p-3" layout="inline" :label="t('attendance.settings.earlyCheckIn')" :hint="t('attendance.settings.earlyCheckInHint')">
            <NumberInput v-model="draft.early_check_in_minutes" :min="0" :max="480" :step="15" :suffix="minutes(draft.early_check_in_minutes)" class="w-40" />
          </FormField>
          <FormField class="p-3" layout="inline" :label="t('attendance.settings.autoClose')" :hint="t('attendance.settings.autoCloseHint')">
            <NumberInput v-model="draft.auto_close_after_hours" :min="1" :max="24" :suffix="t('attendance.settings.hours', { n: draft.auto_close_after_hours })" class="w-40" />
          </FormField>
          <FormField class="p-3" layout="inline" :label="t('attendance.settings.overtime')" :hint="t('attendance.settings.overtimeHint')">
            <NumberInput v-model="draft.overtime_after_minutes" :min="0" :max="240" :step="5" :suffix="minutes(draft.overtime_after_minutes)" class="w-40" />
          </FormField>
        </div>
      </section>

      <section class="flex flex-col gap-3">
        <h3 class="flex items-center gap-2 text-sm font-semibold text-fg"><Repeat2 :size="15" class="text-subtle" />{{ t("attendance.settings.swaps") }}</h3>
        <div class="ui-card flex flex-col divide-y divide-line">
          <ToggleSwitch v-model="draft.swaps_need_approval" layout="row" class="p-3" :label="t('attendance.settings.swapsApproval')" :description="t('attendance.settings.swapsApprovalHint')" />
          <ToggleSwitch v-model="draft.open_shift_claim_needs_approval" layout="row" class="p-3" :label="t('attendance.settings.claimApproval')" :description="t('attendance.settings.claimApprovalHint')" />
        </div>
      </section>

      <section class="flex flex-col gap-3">
        <h3 class="flex items-center gap-2 text-sm font-semibold text-fg"><ListChecks :size="15" class="text-subtle" />{{ t("attendance.settings.tasks") }}</h3>
        <div class="ui-card">
          <ToggleSwitch v-model="draft.tasks_follow_shifts" layout="row" class="p-3" :label="t('attendance.settings.tasksFollow')" :description="t('attendance.settings.tasksFollowHint')" />
        </div>
      </section>

      <StickyActionBar :show="dirty" :message="t('common.unsaved')" tone="warning">
        <UiButton size="sm" variant="ghost" @click="reset">{{ t("common.discard") }}</UiButton>
        <UiButton size="sm" variant="primary" :loading="saving" @click="save">{{ t("common.save") }}</UiButton>
      </StickyActionBar>
    </template>
  </div>
</template>
