<script setup lang="ts">
/**
 * Settings › Contracts: how many days ahead the owner bot and the inbox warn before a contract
 * ends, and before the notice deadline of one that renews by itself. Each reminder comes at the
 * company's morning report time, and once more on the day itself.
 */
import { reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { isApiError } from "@/api/http";
import FormField from "@/components/FormField.vue";
import NumberInput from "@/components/NumberInput.vue";
import UiButton from "@/components/UiButton.vue";
import { toast } from "@/components/useToast";
import { useCompanyStore } from "@/stores/company";

import { contractsApi, useContractSettings, useRefresh } from "../api";

const { t } = useI18n();
const company = useCompanyStore();
const refresh = useRefresh();
const settings = useContractSettings();

const form = reactive({ remind_days: 30 as number | null, notice_remind_days: 14 as number | null });
const errors = reactive<Record<string, string | undefined>>({});
const saving = ref(false);

watch(
  () => settings.data.value,
  (data) => data && Object.assign(form, data),
  { immediate: true },
);

async function save(): Promise<void> {
  for (const key of Object.keys(errors)) delete errors[key];
  saving.value = true;
  try {
    await contractsApi.updateSettings(company.currentId ?? 0, { remind_days: form.remind_days ?? 30, notice_remind_days: form.notice_remind_days ?? 14 });
    toast.success(t("contracts.settings.saved"));
    refresh();
  } catch (error) {
    if (isApiError(error)) for (const [field, messages] of Object.entries(error.fieldErrors)) errors[field] = messages[0];
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <section class="flex flex-col gap-4">
    <div>
      <h3 class="text-md font-semibold text-fg">{{ t("contracts.settings.remindersTitle") }}</h3>
      <p class="mt-1 text-sm text-muted">{{ t("contracts.settings.remindersBody") }}</p>
    </div>
    <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
      <FormField :label="t('contracts.settings.remind')" :hint="t('contracts.settings.remindHint')" :error="errors.remind_days">
        <NumberInput v-model="form.remind_days" :min="1" :max="365" :suffix="t('contracts.form.days')" data-testid="contracts-remind-days" />
      </FormField>
      <FormField :label="t('contracts.settings.notice')" :hint="t('contracts.settings.noticeHint')" :error="errors.notice_remind_days">
        <NumberInput v-model="form.notice_remind_days" :min="1" :max="180" :suffix="t('contracts.form.days')" />
      </FormField>
    </div>
    <div>
      <UiButton variant="primary" :loading="saving" :disabled="!company.can('finance.manage')" data-testid="contracts-settings-save" @click="save">{{ t("contracts.settings.save") }}</UiButton>
    </div>
  </section>
</template>
