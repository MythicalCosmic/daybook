<script setup lang="ts">
/**
 * "Give an advance" for someone who asked in person: who, how much, repaid over how many months
 * and from which month's payslip, and why. It is approved as it is given; paying it out comes
 * next (method and account). The cap in the payroll settings applies (the server checks it).
 */
import { computed, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { isApiError } from "@/api/http";
import FormField from "@/components/FormField.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import MoneyInput from "@/components/MoneyInput.vue";
import NumberInput from "@/components/NumberInput.vue";
import PersonPicker from "@/components/PersonPicker.vue";
import SelectBox from "@/components/SelectBox.vue";
import TextInput from "@/components/TextInput.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";
import { todayIn } from "@/lib/dates";
import { dec } from "@/lib/decimal";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { payrollApi, useRefresh, useSettings } from "../api";
import { periodOf, shiftPeriod } from "../lib";

const open = defineModel<boolean>("open", { default: false });
const props = withDefaults(defineProps<{ member?: number | null }>(), { member: null });

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const refresh = useRefresh();
const settings = useSettings(open);
const saving = ref(false);
const errors = reactive<Record<string, string | undefined>>({});
const form = reactive({ member: null as number | null, amount: null as string | null, installments: 1 as number | null, first_period: "", reason: "" });

const current = computed(() => periodOf(todayIn(company.timezone)));
const periods = computed(() => [0, 1, 2, 3].map((shift) => ({ value: shiftPeriod(current.value, shift), label: fmt.day(shiftPeriod(current.value, shift), "monthYear") })));
watch(
  open,
  (isOpen) => {
    if (!isOpen) return;
    for (const key of Object.keys(errors)) delete errors[key];
    Object.assign(form, { member: props.member, amount: null, installments: 1, first_period: current.value, reason: "" });
  },
  { immediate: true },
);

async function save(): Promise<void> {
  for (const key of Object.keys(errors)) delete errors[key];
  if (!form.member) errors.member = t("payroll.propose.errMember");
  if (!form.amount || !dec(form.amount).greaterThan(0)) errors.amount = t("payroll.propose.errAmount");
  if (Object.keys(errors).length || saving.value) return;
  saving.value = true;
  try {
    await payrollApi.createAdvance(company.currentId ?? 0, {
      membership: form.member!,
      amount: form.amount!,
      installments: Math.max(1, Math.min(12, form.installments ?? 1)),
      first_period: form.first_period,
      reason: form.reason.trim(),
    });
    toast.success(t("payroll.advances.given"));
    refresh();
    open.value = false;
  } catch (error) {
    if (isApiError(error)) for (const [field, messages] of Object.entries(error.fieldErrors)) errors[field === "membership" ? "member" : field] = messages[0];
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <UiDialog v-model:open="open" :title="t('payroll.advances.giveTitle')" :description="t('payroll.advances.giveDescription')" size="md">
    <div class="flex flex-col gap-4">
      <FormField :label="t('payroll.propose.person')" :error="errors.member" required>
        <PersonPicker v-model="form.member" :invalid="!!errors.member" />
      </FormField>
      <FormField :label="t('payroll.field.amount')" :error="errors.amount" required>
        <MoneyInput v-model="form.amount" :currencies="[company.currency]" :invalid="!!errors.amount" />
      </FormField>
      <div class="grid gap-4 sm:grid-cols-2">
        <FormField :label="t('payroll.advances.installments')" :error="errors.installments" :hint="t('payroll.advances.installmentsHint')">
          <NumberInput v-model="form.installments" :min="1" :max="12" :suffix="t('payroll.advances.months')" />
        </FormField>
        <FormField :label="t('payroll.advances.firstPeriod')" :error="errors.first_period">
          <SelectBox v-model="form.first_period" :options="periods" />
        </FormField>
      </div>
      <FormField :label="t('payroll.adjustments.reason')" optional :error="errors.reason">
        <TextInput v-model="form.reason" :maxlength="300" :placeholder="t('payroll.advances.reasonPlaceholder')" />
      </FormField>
      <InlineAlert v-if="settings.data.value" tone="info" size="sm" :description="t('payroll.advances.capNote', { n: settings.data.value.advance_cap_percent })" />
    </div>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="primary" :loading="saving" data-testid="give-save" @click="save">{{ t("payroll.advances.giveSave") }}</UiButton>
    </template>
  </UiDialog>
</template>
