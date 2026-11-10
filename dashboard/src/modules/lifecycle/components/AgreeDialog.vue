<script setup lang="ts">
/**
 * Agree someone's last working day (the day they asked for, or another from today on), or move an
 * agreed one. With payroll on, also what their final payslip pays: the unused leave days and
 * whether one is prepared at all. They hear the day in the bot; the handover list is made.
 */
import { CalendarCheck2 } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import DatePicker from "@/components/DatePicker.vue";
import FormField from "@/components/FormField.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import NumberInput from "@/components/NumberInput.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";
import { diffDays } from "@/lib/dates";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore, useCompanyToday } from "@/stores/company";

import { lifecycleApi, useLifecycleMutation } from "../api";
import { NOTICE_DAYS, suggestedLastDay } from "../lib";
import type { LeaveAgreeInput, Leaving, LeavingRow } from "../types";

const open = defineModel<boolean>("open", { default: false });
const props = defineProps<{ leaving: LeavingRow | Leaving }>();
const emit = defineEmits<{ saved: [leaving: Leaving] }>();

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const today = useCompanyToday();

const moving = computed(() => props.leaving.status === "agreed");
const day = ref<string | null>(null);
const leaveDays = ref<number | null>(null);
const finalPayslip = ref(true);
const error = ref<string | null>(null);
const full = computed(() => ("leave_days" in props.leaving ? (props.leaving as Leaving) : null));

watch(
  open,
  (isOpen) => {
    if (!isOpen) return;
    error.value = null;
    const asked = props.leaving.last_day ?? props.leaving.wished_last_day;
    day.value = asked && asked >= today.value ? asked : suggestedLastDay(today.value);
    leaveDays.value = full.value ? Number(full.value.leave_days) : null;
    finalPayslip.value = full.value?.final_payslip ?? true;
  },
  { immediate: true },
);

/** Days of notice the chosen day gives, from the day they asked. */
const notice = computed(() => {
  if (!day.value) return null;
  return diffDays(props.leaving.requested_at.slice(0, 10), day.value);
});

const save = useLifecycleMutation((cid, input: LeaveAgreeInput) => lifecycleApi.agreeLeaving(cid, props.leaving.id, input));

async function submit(): Promise<void> {
  if (!day.value) {
    error.value = t("lifecycle.form.required");
    return;
  }
  const input: LeaveAgreeInput = { last_day: day.value };
  if (company.enabled("payroll")) {
    if (leaveDays.value !== null) input.leave_days = String(leaveDays.value);
    input.final_payslip = finalPayslip.value;
  }
  try {
    const saved = await save.mutateAsync(input);
    toast.success(moving.value ? t("lifecycle.agree.moved", { name: saved.member.name }) : t("lifecycle.leaving.agreed", { name: saved.member.name }));
    emit("saved", saved);
    open.value = false;
  } catch {
    // The HTTP layer showed the server's reason.
  }
}
</script>

<template>
  <UiDialog
    v-model:open="open"
    size="sm"
    :title="moving ? t('lifecycle.agree.moveTitle', { name: leaving.member.name }) : t('lifecycle.agree.title', { name: leaving.member.name })"
    :description="t('lifecycle.agree.description')"
  >
    <div class="flex flex-col gap-4">
      <FormField
        :label="t('lifecycle.agree.lastDay')"
        :hint="leaving.wished_last_day ? t('lifecycle.agree.asked', { date: fmt.day(leaving.wished_last_day, 'weekday') }) : undefined"
        :error="error"
        required
      >
        <DatePicker v-model="day" :min="today" format="weekday" :invalid="!!error" />
      </FormField>
      <InlineAlert
        v-if="notice !== null && notice < NOTICE_DAYS"
        tone="warning"
        size="sm"
        :description="t('lifecycle.agree.shortNotice', { n: notice }, notice)"
        data-agree-short-notice
      />
      <template v-if="company.enabled('payroll')">
        <ToggleSwitch v-model="finalPayslip" layout="row" :label="t('lifecycle.agree.finalPayslip')" :description="t('lifecycle.agree.finalPayslipHint')" />
        <FormField v-if="finalPayslip" :label="t('lifecycle.agree.leaveDays')" :hint="t('lifecycle.agree.leaveDaysHint')">
          <NumberInput v-model="leaveDays" :min="0" :max="366" :decimals="2" :step="0.5" :placeholder="'0'" />
        </FormField>
      </template>
    </div>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="primary" :icon="CalendarCheck2" :loading="save.isPending.value" @click="submit">
        {{ moving ? t("lifecycle.agree.move") : t("lifecycle.agree.confirm") }}
      </UiButton>
    </template>
  </UiDialog>
</template>
