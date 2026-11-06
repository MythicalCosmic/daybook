<script setup lang="ts">
/**
 * A final settlement's own facts (plan §3.17), above its one payslip: the last working day and
 * the unused leave days paid out (payroll managers change them on a draft; the payslip is worked
 * out again at once), then what the reader must know: the month's payroll had paid their month
 * already, or they owe money that stays as a debt in Finance.
 */
import { UserRoundMinus } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { unshownFieldError } from "@/api/http";
import FormField from "@/components/FormField.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import NumberInput from "@/components/NumberInput.vue";
import UiButton from "@/components/UiButton.vue";
import { toast } from "@/components/useToast";
import { dec } from "@/lib/decimal";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { payrollApi, useRefresh } from "../api";
import { owedAfterSettlement, quantityText } from "../lib";
import type { Run } from "../types";

const props = withDefaults(defineProps<{ run: Run; editable?: boolean }>(), { editable: false });

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const refresh = useRefresh();

const days = ref<number | null>(0);
watch(
  () => props.run.leave_days,
  (value) => {
    days.value = value ? dec(value).toNumber() : 0;
  },
  { immediate: true },
);
const saved = computed(() => dec(props.run.leave_days ?? "0"));
const changed = computed(() => days.value !== null && !dec(days.value).eq(saved.value));
const daysText = computed(() => t("payroll.settlement.daysValue", { n: quantityText(saved.value.toString(), fmt.lang.value) }));
const month = computed(() => fmt.day(props.run.period, "monthYear"));
const owed = computed(() => owedAfterSettlement(props.run));

const saving = ref(false);
const failure = ref<string | null>(null);

async function save(): Promise<void> {
  if (!changed.value || saving.value || days.value === null) return;
  saving.value = true;
  failure.value = null;
  try {
    await payrollApi.setLeavePayout(company.currentId ?? 0, props.run.id, dec(days.value).toFixed(2));
    toast.success(t("payroll.settlement.saved"));
    refresh();
  } catch (error) {
    failure.value = unshownFieldError(error);
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <section class="ui-card flex flex-col gap-4 px-4 py-4 md:px-5" :aria-label="t('payroll.settlement.title')" data-testid="settlement">
    <header class="flex items-start gap-3">
      <span class="grid size-9 shrink-0 place-items-center rounded-[10px] bg-warning-soft text-warning" aria-hidden="true"><UserRoundMinus :size="18" /></span>
      <div class="min-w-0">
        <h2 class="text-base font-semibold text-fg">{{ t("payroll.settlement.title") }}</h2>
        <p class="text-sm text-muted">{{ t("payroll.settlement.hint") }}</p>
      </div>
    </header>

    <dl class="grid grid-cols-1 gap-3 sm:grid-cols-2">
      <div>
        <dt class="kpi-label">{{ t("payroll.settlement.lastDay") }}</dt>
        <dd class="mt-1 text-base font-semibold text-fg" data-testid="settlement-last-day">{{ run.last_day ? fmt.day(run.last_day, "long") : "—" }}</dd>
      </div>
      <div v-if="!editable">
        <dt class="kpi-label">{{ t("payroll.settlement.leaveDays") }}</dt>
        <dd class="mt-1 text-base font-semibold tabular-nums text-fg" data-testid="settlement-days">{{ daysText }}</dd>
      </div>
    </dl>

    <div v-if="editable" class="flex flex-col gap-2 sm:flex-row sm:items-end">
      <FormField v-slot="{ id }" :label="t('payroll.settlement.leaveDays')" :hint="t('payroll.settlement.leaveDaysHint')" class="min-w-0 sm:max-w-[360px] sm:flex-1">
        <NumberInput :id="id" v-model="days" :min="0" :max="366" :step="0.5" :decimals="2" data-testid="settlement-days-input" />
      </FormField>
      <UiButton :disabled="!changed" :loading="saving" class="sm:mb-6" data-testid="settlement-save" @click="save">{{ t("payroll.settlement.recalculate") }}</UiButton>
    </div>

    <InlineAlert v-if="failure" tone="danger" size="sm" :description="failure" />
    <InlineAlert v-if="run.after_regular" tone="info" size="sm" :description="t('payroll.settlement.afterRegular', { month })" />
    <InlineAlert v-if="owed" tone="warning" size="sm" :description="t('payroll.settlement.owes', { amount: fmt.money(owed, run.totals?.currency) })" data-testid="settlement-owes" />
  </section>
</template>
