<script setup lang="ts">
/**
 * HR starts someone's leaving with the last day agreed at once: a resignation handed in on paper,
 * the company ending the work, a fixed-term contract running out. They hear the day in the bot;
 * the handover list is made; on that day's evening they leave and Payroll prepares the final
 * payslip. The server refuses what it must (someone already leaving, an owner by a non-owner).
 */
import { CalendarClock, FileX2, Handshake, LogOut, PenLine } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import DatePicker from "@/components/DatePicker.vue";
import FormField from "@/components/FormField.vue";
import NumberInput from "@/components/NumberInput.vue";
import PersonPicker from "@/components/PersonPicker.vue";
import RadioCards, { type RadioCardOption } from "@/components/RadioCards.vue";
import TextArea from "@/components/TextArea.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";
import { useCompanyStore, useCompanyToday } from "@/stores/company";

import { lifecycleApi, useLifecycleMutation } from "../api";
import { startFormErrors, startPayload, suggestedLastDay, type StartForm, type StartFormErrors } from "../lib";
import { LEAVING_KINDS, type LeaveStartInput, type Leaving, type LeavingKind } from "../types";

const open = defineModel<boolean>("open", { default: false });
const props = withDefaults(defineProps<{ member?: { id: number; name: string } | null }>(), { member: null });
const emit = defineEmits<{ saved: [leaving: Leaving] }>();

const { t } = useI18n();
const company = useCompanyStore();
const today = useCompanyToday();

const blank = (): StartForm => ({
  member: props.member?.id ?? null,
  kind: "resignation",
  last_day: suggestedLastDay(today.value),
  reason: "",
  final_payslip: true,
  leave_days: null,
});
const form = ref<StartForm>(blank());
const errors = ref<StartFormErrors>({});
watch(
  open,
  (isOpen) => {
    if (!isOpen) return;
    form.value = blank();
    errors.value = {};
  },
  { immediate: true },
);

const ICONS: Record<LeavingKind, typeof LogOut> = { resignation: PenLine, company: LogOut, contract_end: FileX2, other: Handshake };
const kinds = computed<RadioCardOption<LeavingKind>[]>(() =>
  LEAVING_KINDS.map((kind) => ({ value: kind, label: t(`lifecycle.leavingKind.${kind}`), description: t(`lifecycle.leavingKindHint.${kind}`), icon: ICONS[kind] })),
);
const message = (key: string | undefined) => (key ? t(`lifecycle.start.error.${key}`) : null);

const save = useLifecycleMutation((cid, input: LeaveStartInput) => lifecycleApi.startLeaving(cid, input));

async function submit(): Promise<void> {
  errors.value = startFormErrors(form.value, today.value);
  if (Object.keys(errors.value).length) return;
  const payload = startPayload(form.value);
  if (!company.enabled("payroll")) {
    delete payload.leave_days;
    delete payload.final_payslip;
  }
  try {
    const saved = await save.mutateAsync(payload);
    toast.success(t("lifecycle.start.done", { name: saved.member.name }));
    emit("saved", saved);
    open.value = false;
  } catch {
    // The HTTP layer showed the server's reason (already leaving, no permission).
  }
}
</script>

<template>
  <UiDialog
    v-model:open="open"
    size="md"
    :title="member ? t('lifecycle.start.titleFor', { name: member.name }) : t('lifecycle.start.title')"
    :description="t('lifecycle.start.description')"
  >
    <div class="flex flex-col gap-4">
      <FormField v-if="!member" :label="t('lifecycle.field.person')" :error="message(errors.member)" required>
        <PersonPicker v-model="form.member" :invalid="!!errors.member" />
      </FormField>
      <FormField :label="t('lifecycle.start.kind')" required>
        <RadioCards v-model="form.kind" :options="kinds" :columns="2" />
      </FormField>
      <FormField :label="t('lifecycle.agree.lastDay')" :hint="t('lifecycle.start.lastDayHint')" :error="message(errors.last_day)" required>
        <DatePicker v-model="form.last_day" :min="today" format="weekday" :invalid="!!errors.last_day" />
      </FormField>
      <FormField :label="t('lifecycle.start.reason')">
        <TextArea v-model="form.reason" :rows="3" :maxlength="2000" :placeholder="t('lifecycle.start.reasonPlaceholder')" />
      </FormField>
      <template v-if="company.enabled('payroll')">
        <ToggleSwitch v-model="form.final_payslip" layout="row" :label="t('lifecycle.agree.finalPayslip')" :description="t('lifecycle.agree.finalPayslipHint')" />
        <FormField v-if="form.final_payslip" :label="t('lifecycle.agree.leaveDays')" :hint="t('lifecycle.agree.leaveDaysHint')" :error="message(errors.leave_days)">
          <NumberInput v-model="form.leave_days" :min="0" :max="366" :decimals="2" :step="0.5" placeholder="0" />
        </FormField>
      </template>
    </div>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="primary" :icon="CalendarClock" :loading="save.isPending.value" @click="submit">{{ t("lifecycle.start.confirm") }}</UiButton>
    </template>
  </UiDialog>
</template>
