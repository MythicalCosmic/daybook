<script setup lang="ts">
/**
 * "Give a bonus" / "Record a fine" (plan §6.2): what (bonus, fine, allowance, deduction), for whom,
 * how much, for which month and why (the person sees the reason). It is a proposal until someone
 * with payroll rights approves it; they may approve it here at once. A fine is checked against
 * the deductions cap when the payroll is worked out.
 */
import { Gift, Minus, Plus, Scale } from "@lucide/vue";
import { computed, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { isApiError } from "@/api/http";
import FormField from "@/components/FormField.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import MoneyInput from "@/components/MoneyInput.vue";
import PersonPicker from "@/components/PersonPicker.vue";
import RadioCards from "@/components/RadioCards.vue";
import SelectBox from "@/components/SelectBox.vue";
import TextArea from "@/components/TextArea.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";
import { todayIn } from "@/lib/dates";
import { dec } from "@/lib/decimal";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { payrollApi, useRefresh } from "../api";
import { periodOf, shiftPeriod } from "../lib";
import type { AdjustmentKind } from "../types";

const open = defineModel<boolean>("open", { default: false });
const props = withDefaults(defineProps<{ kind?: AdjustmentKind; member?: number | null }>(), { kind: "bonus", member: null });

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const refresh = useRefresh();
const canManage = computed(() => company.can("payroll.manage"));
const saving = ref(false);
const errors = reactive<Record<string, string | undefined>>({});
const form = reactive({ kind: "bonus" as AdjustmentKind, member: null as number | null, amount: null as string | null, period: "", reason: "", approve: true });

const current = computed(() => periodOf(todayIn(company.timezone)));
const periods = computed(() => [-1, 0, 1].map((shift) => ({ value: shiftPeriod(current.value, shift), label: fmt.day(shiftPeriod(current.value, shift), "monthYear") })));

watch(
  open,
  (isOpen) => {
    if (!isOpen) return;
    for (const key of Object.keys(errors)) delete errors[key];
    Object.assign(form, { kind: props.kind, member: props.member, amount: null, period: current.value, reason: "", approve: true });
  },
  { immediate: true },
);

const kinds = computed(() =>
  (["bonus", "fine", "allowance", "deduction"] as const).map((value) => ({
    value,
    label: t(`payroll.adjustmentKind.${value}`),
    description: t(`payroll.adjustmentKindHint.${value}`),
    icon: { bonus: Gift, fine: Scale, allowance: Plus, deduction: Minus }[value],
  })),
);

async function save(): Promise<void> {
  for (const key of Object.keys(errors)) delete errors[key];
  if (!form.member) errors.member = t("payroll.propose.errMember");
  if (!form.amount || !dec(form.amount).greaterThan(0)) errors.amount = t("payroll.propose.errAmount");
  if (!form.reason.trim()) errors.reason = t("payroll.propose.errReason");
  if (Object.keys(errors).length || saving.value) return;
  saving.value = true;
  try {
    const created = await payrollApi.createAdjustment(company.currentId ?? 0, { member: form.member!, period: form.period, kind: form.kind, amount: form.amount!, reason: form.reason.trim() });
    if (canManage.value && form.approve && created.status === "proposed") {
      await payrollApi.decideAdjustment(company.currentId ?? 0, created.id, "approve");
      toast.success(t("payroll.propose.doneApproved"));
    } else {
      toast.success(created.status === "approved" ? t("payroll.propose.doneApproved") : t("payroll.propose.done"));
    }
    refresh();
    open.value = false;
  } catch (error) {
    if (isApiError(error)) for (const [field, messages] of Object.entries(error.fieldErrors)) errors[field] = messages[0];
    refresh();
  } finally {
    saving.value = false;
  }
}

const title = computed(() => t(`payroll.propose.title.${form.kind}`));
</script>

<template>
  <UiDialog v-model:open="open" :title="title" :description="t('payroll.propose.description')" size="md">
    <div class="flex flex-col gap-4">
      <RadioCards v-model="form.kind" :options="kinds" :columns="2" />
      <FormField :label="t('payroll.propose.person')" :error="errors.member" required>
        <PersonPicker v-model="form.member" :invalid="!!errors.member" />
      </FormField>
      <div class="grid gap-4 sm:grid-cols-2">
        <FormField :label="t('payroll.field.amount')" :error="errors.amount" required>
          <MoneyInput v-model="form.amount" :currencies="[company.currency]" :invalid="!!errors.amount" />
        </FormField>
        <FormField :label="t('payroll.adjustments.month')" :error="errors.period" required>
          <SelectBox v-model="form.period" :options="periods" />
        </FormField>
      </div>
      <FormField :label="t('payroll.adjustments.reason')" :error="errors.reason" required :hint="t('payroll.propose.reasonHint')" :count="form.reason.length" :max="300">
        <TextArea v-model="form.reason" :rows="2" :maxlength="300" :placeholder="t(`payroll.propose.reasonPlaceholder.${form.kind}`)" :invalid="!!errors.reason" />
      </FormField>
      <ToggleSwitch v-if="canManage" v-model="form.approve" layout="row" :label="t('payroll.propose.approveNow')" :description="t('payroll.propose.approveNowHint')" />
      <InlineAlert v-else tone="info" size="sm" :description="t('payroll.propose.needsApproval')" />
    </div>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="primary" :loading="saving" data-testid="propose-save" @click="save">{{ canManage && form.approve ? t("payroll.propose.saveApprove") : t("payroll.propose.save") }}</UiButton>
    </template>
  </UiDialog>
</template>
