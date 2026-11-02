<script setup lang="ts">
/**
 * The actions that need a date: renew (the new end), terminate (the last day and why) and extend
 * probation (the new end of probation). Opened by useContractActions with `v-model:request`.
 */
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import DatePicker from "@/components/DatePicker.vue";
import FormField from "@/components/FormField.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import TextArea from "@/components/TextArea.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { addDays, addMonths } from "@/lib/dates";
import { useFormat } from "@/lib/useFormat";
import { useCompanyToday } from "@/stores/company";

import { ACTION_ICONS } from "../icons";
import type { Contract, ContractAction } from "../types";
import type { ActionRequest, ContractRef } from "../useContractActions";

const request = defineModel<ActionRequest | null>("request", { default: null });
const props = defineProps<{ perform: (contract: ContractRef, action: ContractAction, payload?: Record<string, unknown>) => Promise<Contract | null> }>();

const { t } = useI18n();
const fmt = useFormat();
const today = useCompanyToday();

const open = computed({
  get: () => request.value !== null,
  set: (value: boolean) => {
    if (!value) request.value = null;
  },
});
const action = computed(() => request.value?.action ?? null);
const contract = computed(() => request.value?.contract ?? null);

const day = ref<string | null>(null);
const reason = ref("");
const error = ref<string | null>(null);
const saving = ref(false);

/** The earliest day the date may take. */
const min = computed(() => {
  const c = contract.value;
  if (!c) return today.value;
  if (action.value === "renew") return c.ends_on && c.ends_on >= today.value ? addDays(c.ends_on, 1) : today.value;
  if (action.value === "extend-probation") return c.probation_until ? addDays(c.probation_until, 1) : today.value;
  return c.starts_on ?? null;
});

watch(
  request,
  (next) => {
    error.value = null;
    reason.value = "";
    if (!next) return;
    const c = next.contract;
    if (next.action === "renew") day.value = addMonths(c.ends_on && c.ends_on >= today.value ? c.ends_on : today.value, 12);
    else if (next.action === "extend-probation") day.value = addMonths(c.probation_until ?? today.value, 1);
    else day.value = today.value;
  },
  { immediate: true },
);

const current = computed(() => {
  const c = contract.value;
  if (!c) return "";
  if (action.value === "renew") return c.ends_on ? t("hr.contract.dialog.currentEnd", { date: fmt.day(c.ends_on, "long") }) : "";
  if (action.value === "extend-probation") return c.probation_until ? t("hr.contract.dialog.currentProbation", { date: fmt.day(c.probation_until, "long") }) : "";
  return "";
});

async function submit(): Promise<void> {
  const c = contract.value;
  const a = action.value;
  if (!c || !a) return;
  error.value = null;
  if (!day.value) {
    error.value = t("hr.form.required");
    return;
  }
  if (a === "terminate" && !reason.value.trim()) {
    error.value = t("hr.contract.dialog.reasonRequired");
    return;
  }
  const payload: Record<string, unknown> =
    a === "renew" ? { ends_on: day.value } : a === "extend-probation" ? { until: day.value } : { terminated_on: day.value, reason: reason.value.trim() };
  saving.value = true;
  try {
    const done = await props.perform(c, a, payload);
    if (done) request.value = null;
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <UiDialog v-model:open="open" size="sm" :title="action && contract ? t(`hr.contract.dialog.${action}.title`, { name: contract.member.name }) : ''" :description="action ? t(`hr.contract.dialog.${action}.body`) : undefined">
    <div v-if="action && contract" class="flex flex-col gap-4">
      <p v-if="current" class="rounded-[10px] bg-surface-2 px-3 py-2 text-sm text-muted">{{ current }}</p>
      <FormField :label="t(`hr.contract.dialog.${action}.date`)" :error="action !== 'terminate' || reason.trim() ? error : null" required>
        <DatePicker v-model="day" :min="min" format="long" />
      </FormField>
      <template v-if="action === 'terminate'">
        <FormField :label="t('hr.contract.dialog.reason')" :error="!reason.trim() ? error : null" required>
          <TextArea v-model="reason" :rows="3" :maxlength="300" :placeholder="t('hr.contract.dialog.reasonPlaceholder')" />
        </FormField>
        <InlineAlert tone="warning" size="sm" :description="t('hr.contract.dialog.terminateNote')" />
      </template>
    </div>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton v-if="action" :variant="action === 'terminate' ? 'danger' : 'primary'" :icon="ACTION_ICONS[action]" :loading="saving" @click="submit">{{ t(`hr.contract.action.${action}`) }}</UiButton>
    </template>
  </UiDialog>
</template>
