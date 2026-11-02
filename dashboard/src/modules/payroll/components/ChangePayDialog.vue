<script setup lang="ts">
/**
 * "Change pay" (and "Set pay" for someone without one): from which day, how they are paid
 * (monthly, daily, hourly, per task), how much and in which currency, how a monthly amount is
 * prorated, overtime and task rates. A change is a new row from that day; the row starting that
 * very day is edited instead while no finalized payroll used it, and can't change once one did.
 */
import { CalendarDays, Clock3, Hourglass, ListChecks } from "@lucide/vue";
import { computed, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { isApiError } from "@/api/http";
import type { Currency } from "@/api/types";
import DatePicker from "@/components/DatePicker.vue";
import FormField from "@/components/FormField.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import MoneyInput from "@/components/MoneyInput.vue";
import RadioCards from "@/components/RadioCards.vue";
import SelectBox from "@/components/SelectBox.vue";
import TextInput from "@/components/TextInput.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";
import { todayIn } from "@/lib/dates";
import { dec } from "@/lib/decimal";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { payrollApi, useRefresh } from "../api";
import { changePlan, payHistory, suggestedEffectiveFrom } from "../lib";
import type { Compensation, Member, PayType, Proration } from "../types";

const open = defineModel<boolean>("open", { default: false });
const props = withDefaults(defineProps<{ member: Member; history: Compensation[]; start?: Compensation | null }>(), { start: null });

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const refresh = useRefresh();
const saving = ref(false);
const errors = reactive<Record<string, string | undefined>>({});
const form = reactive({
  effective_from: null as string | null,
  pay_type: "monthly" as PayType,
  amount: null as string | null,
  currency: "UZS" as Currency,
  proration: "attendance" as Proration,
  overtime_eligible: false,
  pays_task_rates: false,
  note: "",
});

const today = computed(() => todayIn(company.timezone));
watch(
  open,
  (isOpen) => {
    if (!isOpen) return;
    for (const key of Object.keys(errors)) delete errors[key];
    // A planned change not used yet is what they most likely want to adjust: start from it.
    const { current, upcoming } = payHistory(props.history, today.value);
    const editing = props.start ?? (upcoming && !upcoming.locked ? upcoming : null);
    const base = editing ?? current;
    Object.assign(form, {
      effective_from: editing?.effective_from ?? suggestedEffectiveFrom(today.value),
      pay_type: base?.pay_type ?? "monthly",
      amount: base?.amount ?? null,
      currency: base?.currency ?? company.currency,
      proration: base?.proration ?? "attendance",
      overtime_eligible: base?.overtime_eligible ?? false,
      pays_task_rates: base?.pays_task_rates ?? false,
      note: editing?.note ?? "",
    });
  },
  { immediate: true },
);

const plan = computed(() => (form.effective_from ? changePlan(props.history, form.effective_from) : null));
const typeOptions = computed(() =>
  (["monthly", "daily", "hourly", "per_task"] as const).map((value) => ({
    value,
    label: t(`payroll.payType.${value}`),
    description: t(`payroll.payTypeHint.${value}`),
    icon: { monthly: CalendarDays, daily: Clock3, hourly: Hourglass, per_task: ListChecks }[value],
  })),
);
const prorationOptions = computed(() => (["attendance", "calendar", "none"] as const).map((value) => ({ value, label: t(`payroll.proration.${value}`) })));
const needsAmount = computed(() => form.pay_type !== "per_task");

async function save(): Promise<void> {
  for (const key of Object.keys(errors)) delete errors[key];
  if (!form.effective_from) errors.effective_from = t("common.form.required");
  if (needsAmount.value && (!form.amount || !dec(form.amount).greaterThan(0))) errors.amount = t("payroll.pay.errAmount");
  if (plan.value?.mode === "locked") errors.effective_from = t("payroll.pay.errLocked");
  if (Object.keys(errors).length || saving.value) return;
  saving.value = true;
  const input = {
    membership: props.member.id,
    effective_from: form.effective_from!,
    pay_type: form.pay_type,
    amount: needsAmount.value ? form.amount! : "0.00",
    currency: form.currency,
    proration: form.pay_type === "monthly" ? form.proration : "none",
    pays_task_rates: form.pay_type === "per_task" ? true : form.pays_task_rates,
    overtime_eligible: form.pay_type === "monthly" || form.pay_type === "hourly" ? form.overtime_eligible : false,
    note: form.note.trim(),
  };
  try {
    if (plan.value?.mode === "update") await payrollApi.updateCompensation(company.currentId ?? 0, plan.value.id, input);
    else await payrollApi.createCompensation(company.currentId ?? 0, input);
    toast.success(t("payroll.pay.saved", { date: fmt.day(input.effective_from, "long") }));
    refresh();
    open.value = false;
  } catch (error) {
    if (isApiError(error)) for (const [field, messages] of Object.entries(error.fieldErrors)) errors[field] = messages[0];
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <UiDialog v-model:open="open" :title="start || history.length ? t('payroll.pay.changeTitle') : t('payroll.pay.setTitle')" :description="member.name" size="lg">
    <div class="flex flex-col gap-5">
      <FormField :label="t('payroll.pay.effectiveFrom')" :error="errors.effective_from" required :hint="t('payroll.pay.effectiveFromHint')">
        <DatePicker v-model="form.effective_from" :invalid="!!errors.effective_from" />
      </FormField>
      <InlineAlert v-if="plan?.mode === 'create' && history.length" tone="info" size="sm" :description="t('payroll.pay.planCreate', { date: fmt.day(form.effective_from!, 'long') })" />
      <InlineAlert v-else-if="plan?.mode === 'update'" tone="info" size="sm" :description="t('payroll.pay.planUpdate', { date: fmt.day(form.effective_from!, 'long') })" />
      <InlineAlert v-else-if="plan?.mode === 'locked'" tone="danger" size="sm" :title="t('payroll.pay.planLockedTitle')" :description="plan.row.locked_reason || t('payroll.pay.planLocked')" />

      <FormField :label="t('payroll.pay.type')" required>
        <RadioCards v-model="form.pay_type" :options="typeOptions" :columns="2" />
      </FormField>

      <FormField v-if="needsAmount" :label="t(`payroll.pay.amountLabel.${form.pay_type}`)" :error="errors.amount" required>
        <MoneyInput v-model="form.amount" v-model:currency="form.currency" :currencies="['UZS', 'USD']" :invalid="!!errors.amount" />
      </FormField>
      <InlineAlert v-else tone="neutral" size="sm" :description="t('payroll.pay.perTaskNote')" />

      <FormField v-if="form.pay_type === 'monthly'" :label="t('payroll.pay.proration')" :error="errors.proration" :hint="t(`payroll.prorationHint.${form.proration}`)">
        <SelectBox v-model="form.proration" :options="prorationOptions" />
      </FormField>

      <div class="flex flex-col divide-y divide-line rounded-[12px] border border-line">
        <ToggleSwitch
          v-if="form.pay_type === 'monthly' || form.pay_type === 'hourly'"
          v-model="form.overtime_eligible"
          layout="row"
          class="px-4 py-3"
          :label="t('payroll.pay.overtimeLabel')"
          :description="t('payroll.pay.overtimeHint')"
        />
        <ToggleSwitch v-if="form.pay_type !== 'per_task'" v-model="form.pays_task_rates" layout="row" class="px-4 py-3" :label="t('payroll.pay.taskRatesLabel')" :description="t('payroll.pay.taskRatesHint')" />
        <p class="px-4 py-3 text-sm text-muted">{{ t("payroll.pay.nightNote") }}</p>
      </div>

      <FormField :label="t('payroll.pay.note')" optional :error="errors.note">
        <TextInput v-model="form.note" :maxlength="200" :placeholder="t('payroll.pay.notePlaceholder')" />
      </FormField>
    </div>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="primary" :loading="saving" :disabled="plan?.mode === 'locked'" data-testid="save-pay" @click="save">{{ t("payroll.pay.save") }}</UiButton>
    </template>
  </UiDialog>
</template>
