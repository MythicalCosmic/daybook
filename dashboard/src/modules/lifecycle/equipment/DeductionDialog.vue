<script setup lang="ts">
/**
 * Propose a deduction from someone's pay for something they hold that is damaged or will not come
 * back. It goes to payroll as a proposal; payroll's managers approve it as usual, and the item shows
 * the proposal's state.
 */
import { HandCoins } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import type { Money } from "@/api/types";
import FormField from "@/components/FormField.vue";
import MoneyInput from "@/components/MoneyInput.vue";
import TextInput from "@/components/TextInput.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";
import { moneySign } from "@/lib/money";
import { useCompanyStore } from "@/stores/company";

import { equipmentApi, useEquipmentMutation } from "./api";
import type { DeductionInput, HeldItem, Holder } from "./types";

const open = defineModel<boolean>("open", { default: false });
const props = defineProps<{ holder: Pick<Holder, "person">; item: HeldItem }>();
const emit = defineEmits<{ saved: [holder: Holder] }>();

const { t } = useI18n();
const company = useCompanyStore();
const amount = ref<Money | null>(null);
const reason = ref("");
const error = ref(false);
watch(
  open,
  (isOpen) => {
    if (!isOpen) return;
    amount.value = props.item.value;
    reason.value = "";
    error.value = false;
  },
  { immediate: true },
);

const save = useEquipmentMutation((cid, input: DeductionInput) => equipmentApi.deduct(cid, props.item.assignment_id, input));
const valid = computed(() => moneySign(amount.value) === 1);
async function submit(): Promise<void> {
  error.value = !valid.value;
  if (error.value) return;
  try {
    const holder = await save.mutateAsync({ amount: amount.value!, ...(reason.value.trim() ? { reason: reason.value.trim() } : {}) });
    toast.success(t("lifecycle.equipment.deduction.sent"));
    emit("saved", holder);
    open.value = false;
  } catch {
    // The HTTP layer showed why (they have left, one is already with payroll).
  }
}
</script>

<template>
  <UiDialog v-model:open="open" size="sm" :title="t('lifecycle.equipment.deduction.title', { item: item.name })" :description="t('lifecycle.equipment.deduction.description', { name: holder.person.name })">
    <div class="flex flex-col gap-4">
      <FormField :label="t('lifecycle.equipment.deduction.amount')" :error="error ? t('lifecycle.equipment.error.amount') : null" :hint="item.value ? undefined : t('lifecycle.equipment.deduction.amountHint')" required>
        <MoneyInput v-model="amount" :currencies="[company.currency]" :invalid="error" data-deduction-amount />
      </FormField>
      <FormField :label="t('lifecycle.equipment.deduction.reason')" optional>
        <TextInput v-model="reason" :maxlength="300" :placeholder="t('lifecycle.equipment.deduction.reasonPlaceholder', { item: item.name })" />
      </FormField>
      <p class="text-xs text-muted">{{ t("lifecycle.equipment.deduction.hint") }}</p>
    </div>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="primary" :icon="HandCoins" :loading="save.isPending.value" data-deduction-submit @click="submit">{{ t("lifecycle.equipment.deduction.submit") }}</UiButton>
    </template>
  </UiDialog>
</template>
