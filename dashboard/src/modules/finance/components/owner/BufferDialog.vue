<script setup lang="ts">
/**
 * What the safe amount keeps back: the cash buffer (one month of fixed costs, worked out from the
 * books, or an amount of one's own) and how many days of payments due it counts.
 */
import { computed, reactive, watch } from "vue";
import { useI18n } from "vue-i18n";

import FormField from "@/components/FormField.vue";
import MoneyInput from "@/components/MoneyInput.vue";
import MoneyText from "@/components/MoneyText.vue";
import RadioCards from "@/components/RadioCards.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";
import { useCompanyStore } from "@/stores/company";

import { ownerMoneyApi, useOwnerMoneyWrite, type OwnerMoney } from "../../ownerMoney";

const open = defineModel<boolean>("open", { default: false });
const props = defineProps<{ data: OwnerMoney }>();

const { t } = useI18n();
const company = useCompanyStore();
const HORIZONS = ["14", "30", "45", "60", "90"] as const;
const form = reactive({ mode: "auto" as "auto" | "own" | null, amount: null as string | null, days: "30" as string });
const error = computed(() => (form.mode === "own" && !form.amount ? t("finance.quick.errAmount") : undefined));

watch(
  open,
  (isOpen) => {
    if (!isOpen) return;
    const own = props.data.settings.cash_buffer;
    form.mode = own === null ? "auto" : "own";
    form.amount = own ?? props.data.buffer.fixed_costs;
    form.days = HORIZONS.includes(String(props.data.settings.draw_horizon_days) as (typeof HORIZONS)[number]) ? String(props.data.settings.draw_horizon_days) : "30";
  },
  { immediate: true },
);

const write = useOwnerMoneyWrite(ownerMoneyApi.settings);
async function save(): Promise<void> {
  if (error.value) return;
  await write.mutateAsync({ cash_buffer: form.mode === "auto" ? null : form.amount, draw_horizon_days: Number(form.days) });
  toast.success(t("finance.myMoney.settingsSaved"));
  open.value = false;
}
</script>

<template>
  <UiDialog v-model:open="open" :title="t('finance.myMoney.settingsTitle')" :description="t('finance.myMoney.settingsDescription')" size="md">
    <div class="flex flex-col gap-5">
      <FormField :label="t('finance.myMoney.bufferLabel')">
        <RadioCards
          v-model="form.mode"
          :options="[
            { value: 'auto', label: t('finance.myMoney.bufferAutoTitle'), description: t('finance.myMoney.bufferAutoBody') },
            { value: 'own', label: t('finance.myMoney.bufferOwnTitle'), description: t('finance.myMoney.bufferOwnBody') },
          ]"
        />
      </FormField>
      <div v-if="form.mode === 'auto'" class="flex items-center justify-between rounded-[10px] bg-surface-2 px-3 py-2.5 text-sm" data-fixed-costs>
        <span class="text-muted">{{ t("finance.myMoney.fixedCosts") }}</span>
        <span class="font-semibold tabular-nums text-fg"><MoneyText :value="data.buffer.fixed_costs" /></span>
      </div>
      <FormField v-else :label="t('finance.myMoney.bufferAmount')" :error="error" required>
        <MoneyInput v-model="form.amount" :currencies="[company.currency]" :invalid="!!error" />
      </FormField>
      <FormField :label="t('finance.myMoney.horizonLabel')" :hint="t('finance.myMoney.horizonHint')">
        <SegmentedControl v-model="form.days" block :options="HORIZONS.map((value) => ({ value, label: t('finance.myMoney.days', { n: Number(value) }, Number(value)) }))" />
      </FormField>
    </div>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="primary" :loading="write.isPending.value" data-save @click="save">{{ t("common.save") }}</UiButton>
    </template>
  </UiDialog>
</template>
