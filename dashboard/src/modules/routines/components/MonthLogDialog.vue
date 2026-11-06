<script setup lang="ts">
/**
 * The month's temperature and humidity log of a branch as a PDF (PLAN-OWNER §14.10): every
 * readings routine of the branch grouped by what is measured (a morning and an evening routine of
 * one fridge share a page), each day with its values, who took them, notes, rechecks and a
 * signature line: what an inspector asks to see.
 */
import { FileDown } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import BranchPicker from "@/components/BranchPicker.vue";
import FormField from "@/components/FormField.vue";
import SelectBox from "@/components/SelectBox.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { addMonths, startOfMonth, todayIn } from "@/lib/dates";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { openReadingsPdf } from "../api";

const open = defineModel<boolean>("open", { default: false });

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const branch = ref<number | null>(null);
const months = computed(() => {
  const first = startOfMonth(todayIn(company.timezone));
  return Array.from({ length: 12 }, (_, index) => {
    const day = addMonths(first, -index);
    return { value: day.slice(0, 7), label: fmt.day(day, "monthYear") };
  });
});
const month = ref("");
watch(
  open,
  (value) => {
    if (!value) return;
    month.value ||= months.value[0]?.value ?? "";
    branch.value ??= company.current?.branches[0]?.id ?? null;
  },
  { immediate: true },
);
const busy = ref(false);

async function download(): Promise<void> {
  if (branch.value === null || !month.value) return;
  busy.value = true;
  try {
    await openReadingsPdf(company.currentId ?? 0, branch.value, month.value);
    open.value = false;
  } catch {
    // the HTTP layer showed why
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <UiDialog v-model:open="open" :title="t('routines.readings.logTitle')" :description="t('routines.readings.logHint')" size="sm">
    <div class="flex flex-col gap-4">
      <FormField :label="t('routines.preset.branch')" required>
        <BranchPicker v-model="branch" />
      </FormField>
      <FormField :label="t('routines.readings.month')" required>
        <SelectBox v-model="month" :options="months" />
      </FormField>
    </div>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="primary" :icon="FileDown" :disabled="branch === null || !month" :loading="busy" @click="download">{{ t("routines.readings.pdf") }}</UiButton>
    </template>
  </UiDialog>
</template>
