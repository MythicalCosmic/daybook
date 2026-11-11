<script setup lang="ts">
/**
 * Two steps of a contract: renew it (a new end date: an extension signed, or a lapsed contract
 * signed again; the next term is suggested) or terminate it early (its last day, today or after
 * the notice, and why). Either way its recurring payment follows: it runs on to the new end, or
 * stops with the contract.
 */
import { computed, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { isApiError } from "@/api/http";
import DatePicker from "@/components/DatePicker.vue";
import FormField from "@/components/FormField.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import TextArea from "@/components/TextArea.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore, useCompanyToday } from "@/stores/company";

import { contractsApi, useRefresh } from "../api";
import { addDays } from "../lib";
import type { ContractDetail } from "../types";

const open = defineModel<boolean>("open", { default: false });
const props = defineProps<{ contract: ContractDetail; kind: "renew" | "terminate" }>();

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const today = useCompanyToday();
const refresh = useRefresh();

const saving = ref(false);
const errors = reactive<Record<string, string | undefined>>({});
const form = reactive({ day: null as string | null, reason: "" });

/** The next term's last day: as many months as a renewal lasts, from the day after the end. */
function nextEnd(): string {
  const from = props.contract.ends_on && props.contract.ends_on >= today.value ? props.contract.ends_on : today.value;
  const [year, month, day] = addDays(from, 1).split("-").map(Number) as [number, number, number];
  const target = new Date(Date.UTC(year, month - 1 + props.contract.renewal_months, day));
  return addDays(target.toISOString().slice(0, 10), -1);
}

watch(
  open,
  (value) => {
    if (!value) return;
    for (const key of Object.keys(errors)) delete errors[key];
    form.reason = "";
    form.day = props.kind === "renew" ? nextEnd() : today.value;
  },
  { immediate: true },
);

const ahead = computed(() => props.kind === "terminate" && form.day !== null && form.day > today.value);

async function submit(): Promise<void> {
  for (const key of Object.keys(errors)) delete errors[key];
  if (!form.day) {
    errors.day = t("contracts.action.errDay");
    return;
  }
  saving.value = true;
  const cid = company.currentId ?? 0;
  try {
    if (props.kind === "renew") await contractsApi.renew(cid, props.contract.id, form.day);
    else await contractsApi.terminate(cid, props.contract.id, form.day, form.reason);
    toast.success(props.kind === "renew" ? t("contracts.action.renewed", { day: fmt.day(form.day, "medium") }) : t("contracts.action.terminated"));
    refresh();
    open.value = false;
  } catch (error) {
    if (isApiError(error)) for (const [field, messages] of Object.entries(error.fieldErrors)) errors[field === "ends_on" || field === "on" ? "day" : field] = messages[0];
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <UiDialog
    v-model:open="open"
    :title="kind === 'renew' ? t('contracts.action.renewTitle') : t('contracts.action.terminateTitle')"
    :description="kind === 'renew' ? t('contracts.action.renewBody') : t('contracts.action.terminateBody')"
    size="sm"
  >
    <div class="flex flex-col gap-4">
      <FormField :label="kind === 'renew' ? t('contracts.action.newEnd') : t('contracts.action.lastDay')" :error="errors.day" required>
        <DatePicker v-model="form.day" :min="kind === 'renew' ? (contract.ends_on ?? today) : (contract.starts_on ?? undefined)" data-testid="contract-action-day" />
      </FormField>
      <FormField v-if="kind === 'terminate'" :label="t('contracts.action.reason')" :error="errors.reason" optional>
        <TextArea v-model="form.reason" :rows="2" :maxlength="300" :placeholder="t('contracts.action.reasonPlaceholder')" />
      </FormField>
      <InlineAlert v-if="contract.rule?.is_active" tone="info" size="sm">
        {{ kind === "renew" ? t("contracts.action.ruleRuns") : ahead ? t("contracts.action.ruleEndsOn", { day: fmt.day(form.day ?? today, "medium") }) : t("contracts.action.ruleStops") }}
      </InlineAlert>
    </div>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton :variant="kind === 'terminate' ? 'danger' : 'primary'" :loading="saving" data-testid="contract-action-submit" @click="submit">
        {{ kind === "renew" ? t("contracts.action.renew") : t("contracts.action.terminate") }}
      </UiButton>
    </template>
  </UiDialog>
</template>
