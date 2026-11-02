<script setup lang="ts">
/**
 * "Prepare payroll": pick the month (last month, this month, or the two around them) and the
 * server creates the draft run and works out everyone's pay for it; the run's page opens next.
 * Months that already have a run are shown, but can't be picked again.
 */
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";

import RadioCards from "@/components/RadioCards.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";
import { todayIn } from "@/lib/dates";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { payrollApi, useRefresh } from "../api";
import { periodOf, shiftPeriod, takenPeriods } from "../lib";
import type { Run } from "../types";

const open = defineModel<boolean>("open", { default: false });
const props = defineProps<{ runs: Run[]; suggested: string | null }>();

const { t } = useI18n();
const fmt = useFormat();
const router = useRouter();
const company = useCompanyStore();
const refresh = useRefresh();
const saving = ref(false);
const period = ref<string | null>(null);

const options = computed(() => {
  const current = periodOf(todayIn(company.timezone));
  const taken = takenPeriods(props.runs);
  return [-2, -1, 0, 1].map((shift) => {
    const value = shiftPeriod(current, shift);
    const done = taken.has(value);
    return {
      value,
      label: fmt.day(value, "monthYear"),
      description: done ? t("payroll.prepare.taken") : shift === 0 ? t("payroll.prepare.thisMonth") : shift === -1 ? t("payroll.prepare.lastMonth") : shift === 1 ? t("payroll.prepare.nextMonth") : t("payroll.prepare.earlier"),
      disabled: done,
    };
  });
});

watch(
  open,
  (isOpen) => {
    if (!isOpen) return;
    period.value = props.suggested ?? options.value.find((option) => !option.disabled)?.value ?? null;
  },
  { immediate: true },
);

async function prepare(): Promise<void> {
  if (!period.value || saving.value) return;
  saving.value = true;
  try {
    const run = await payrollApi.createRun(company.currentId ?? 0, period.value);
    toast.success(t("payroll.prepare.done", { month: fmt.day(run.period, "monthYear") }));
    refresh();
    open.value = false;
    void router.push(`/c/${company.currentId}/payroll/runs/${run.id}`);
  } catch {
    // The HTTP layer showed why (a run for that month appeared meanwhile, the module is off…).
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <UiDialog v-model:open="open" :title="t('payroll.prepare.title')" :description="t('payroll.prepare.description')" size="md">
    <RadioCards v-model="period" :options="options" :columns="2" />
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="primary" :loading="saving" :disabled="!period" data-testid="prepare-confirm" @click="prepare">{{ t("payroll.prepare.confirm") }}</UiButton>
    </template>
  </UiDialog>
</template>
