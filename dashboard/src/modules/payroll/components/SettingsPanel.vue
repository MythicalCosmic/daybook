<script setup lang="ts">
/**
 * Settings › Payroll (plan §3.13, §14.11, §14.21): pay day, the advance day and cap, the deductions
 * cap and rounding, overtime, holiday and night multipliers with the night window, the working day
 * in hours, taxes (off by default, with a note) and preparing last month's payroll on the 1st.
 * Saves only what changed; the server audits it.
 */
import { Info } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { unshownFieldError } from "@/api/http";
import ErrorState from "@/components/ErrorState.vue";
import FormField from "@/components/FormField.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import NumberInput from "@/components/NumberInput.vue";
import PageSection from "@/components/PageSection.vue";
import SelectBox from "@/components/SelectBox.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StickyActionBar from "@/components/StickyActionBar.vue";
import TimePicker from "@/components/TimePicker.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import UiButton from "@/components/UiButton.vue";
import { toast } from "@/components/useToast";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { payrollApi, useRefresh, useSettings } from "../api";
import { settingsChanges, settingsForm, type SettingsForm } from "../lib";

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const refresh = useRefresh();
const query = useSettings();
const draft = ref<SettingsForm | null>(null);
const saving = ref(false);
const failure = ref<string | null>(null);
const errors = ref<Record<string, string>>({});

watch(
  () => query.data.value,
  (value) => {
    if (value) draft.value = settingsForm(value);
  },
  { immediate: true },
);

const changes = computed(() => (query.data.value && draft.value ? settingsChanges(query.data.value, draft.value) : {}));
const dirty = computed(() => Object.keys(changes.value).length > 0);
const roundingOptions = computed(() =>
  ["0.01", "100.00", "500.00", "1000.00", "5000.00", "10000.00"].map((value) => ({ value, label: value === "0.01" ? t("payroll.settings.noRounding") : fmt.money(value) })),
);

async function save(): Promise<void> {
  if (!dirty.value || saving.value) return;
  saving.value = true;
  failure.value = null;
  errors.value = {};
  try {
    await payrollApi.updateSettings(company.currentId ?? 0, changes.value);
    toast.success(t("payroll.settings.saved"));
    refresh();
  } catch (error) {
    failure.value = unshownFieldError(error);
  } finally {
    saving.value = false;
  }
}

function reset(): void {
  if (query.data.value) draft.value = settingsForm(query.data.value);
}
</script>

<template>
  <div class="flex flex-col gap-6 pb-16">
    <div v-if="query.isPending.value" class="flex flex-col gap-4">
      <SkeletonBlock v-for="n in 4" :key="n" height="96px" radius="12px" />
    </div>
    <ErrorState v-else-if="query.isError.value" :error="query.error.value" :retry="() => query.refetch()" />
    <template v-else-if="draft">
      <PageSection variant="card" :heading-level="3" :title="t('payroll.settings.payDay')" :description="t('payroll.settings.payDayHint')">
        <div class="flex flex-col gap-4">
          <FormField v-slot="{ id }" layout="inline" :label="t('payroll.settings.payDayLabel')" :hint="t('payroll.settings.payDayFieldHint')">
            <NumberInput :id="id" v-model="draft.pay_day" :min="1" :max="28" class="sm:max-w-[200px]" />
          </FormField>
          <FormField v-slot="{ id }" layout="inline" :label="t('payroll.settings.advanceDay')" :hint="t('payroll.settings.advanceDayHint')" optional>
            <NumberInput :id="id" v-model="draft.advance_day" :min="1" :max="28" :placeholder="t('payroll.settings.off')" class="sm:max-w-[200px]" />
          </FormField>
          <FormField v-slot="{ id }" layout="inline" :label="t('payroll.settings.advanceCap')" :hint="t('payroll.settings.advanceCapHint')">
            <NumberInput :id="id" v-model="draft.advance_cap_percent" :min="0" :max="100" suffix="%" class="sm:max-w-[200px]" />
          </FormField>
        </div>
      </PageSection>

      <PageSection variant="card" :heading-level="3" :title="t('payroll.settings.deductions')" :description="t('payroll.settings.deductionsHint')">
        <div class="flex flex-col gap-4">
          <FormField v-slot="{ id }" layout="inline" :label="t('payroll.settings.deductionsCap')" :hint="t('payroll.settings.deductionsCapHint')">
            <NumberInput :id="id" v-model="draft.deductions_cap_percent" :min="0" :max="100" suffix="%" class="sm:max-w-[200px]" />
          </FormField>
          <FormField v-slot="{ id }" layout="inline" :label="t('payroll.settings.rounding')" :hint="t('payroll.settings.roundingHint')">
            <SelectBox :id="id" v-model="draft.rounding_step" :options="roundingOptions" class="sm:max-w-[200px]" />
          </FormField>
        </div>
      </PageSection>

      <PageSection variant="card" :heading-level="3" :title="t('payroll.settings.extraPay')" :description="t('payroll.settings.extraPayHint')">
        <div class="flex flex-col gap-4">
          <FormField v-slot="{ id }" layout="inline" :label="t('payroll.settings.overtime')" :hint="t('payroll.settings.overtimeHint')">
            <NumberInput :id="id" v-model="draft.overtime_multiplier" :min="1" :max="5" :step="0.25" :decimals="2" suffix="×" class="sm:max-w-[200px]" />
          </FormField>
          <FormField v-slot="{ id }" layout="inline" :label="t('payroll.settings.holiday')" :hint="t('payroll.settings.holidayHint')">
            <NumberInput :id="id" v-model="draft.holiday_work_multiplier" :min="1" :max="5" :step="0.25" :decimals="2" suffix="×" class="sm:max-w-[200px]" />
          </FormField>
          <FormField v-slot="{ id }" layout="inline" :label="t('payroll.settings.night')" :hint="t('payroll.settings.nightHint')">
            <NumberInput :id="id" v-model="draft.night_multiplier" :min="1" :max="5" :step="0.25" :decimals="2" suffix="×" class="sm:max-w-[200px]" />
          </FormField>
          <FormField layout="inline" :label="t('payroll.settings.nightWindow')" :hint="t('payroll.settings.nightWindowHint')">
            <div class="flex items-center gap-2 sm:max-w-[260px]">
              <TimePicker v-model="draft.night_starts_at" :step="30" :aria-label="t('payroll.settings.nightFrom')" class="min-w-0 flex-1" />
              <span class="text-muted">–</span>
              <TimePicker v-model="draft.night_ends_at" :step="30" :aria-label="t('payroll.settings.nightTo')" class="min-w-0 flex-1" />
            </div>
          </FormField>
          <FormField v-slot="{ id }" layout="inline" :label="t('payroll.settings.dailyHours')" :hint="t('payroll.settings.dailyHoursHint')">
            <NumberInput :id="id" v-model="draft.daily_hours" :min="1" :max="24" :step="0.5" :decimals="2" :suffix="t('payroll.rules.unit.h')" class="sm:max-w-[200px]" />
          </FormField>
          <p class="flex items-start gap-2 rounded-[10px] bg-surface-2 px-3 py-2.5 text-sm text-muted"><Info :size="15" class="mt-0.5 shrink-0" />{{ t("payroll.settings.nightNote") }}</p>
        </div>
      </PageSection>

      <PageSection variant="card" :heading-level="3" :title="t('payroll.settings.taxes')" :description="t('payroll.settings.taxesHint')">
        <div class="flex flex-col gap-4">
          <ToggleSwitch v-model="draft.amounts_are_net" layout="row" :label="t('payroll.settings.net')" :description="t('payroll.settings.netHint')" />
          <ToggleSwitch v-model="draft.taxes_enabled" layout="row" :label="t('payroll.settings.taxesOn')" :description="t('payroll.settings.taxesOnHint')" data-testid="taxes-toggle" />
          <InlineAlert v-if="!draft.taxes_enabled" tone="neutral" size="sm" :description="t('payroll.settings.taxesOffNote')" />
          <template v-else>
            <InlineAlert tone="warning" size="sm" :description="t('payroll.settings.taxesOnNote')" />
            <FormField v-slot="{ id }" layout="inline" :label="t('payroll.settings.incomeTax')">
              <NumberInput :id="id" v-model="draft.income_tax_percent" :min="0" :max="100" :step="0.5" :decimals="2" suffix="%" class="sm:max-w-[200px]" />
            </FormField>
            <FormField v-slot="{ id }" layout="inline" :label="t('payroll.settings.socialTax')">
              <NumberInput :id="id" v-model="draft.social_tax_percent" :min="0" :max="100" :step="0.5" :decimals="2" suffix="%" class="sm:max-w-[200px]" />
            </FormField>
            <FormField v-slot="{ id }" layout="inline" :label="t('payroll.settings.inps')">
              <NumberInput :id="id" v-model="draft.inps_percent" :min="0" :max="100" :step="0.1" :decimals="2" suffix="%" class="sm:max-w-[200px]" />
            </FormField>
          </template>
        </div>
      </PageSection>

      <PageSection variant="card" :heading-level="3" :title="t('payroll.settings.automation')">
        <ToggleSwitch v-model="draft.auto_prepare" layout="row" :label="t('payroll.settings.autoPrepare')" :description="t('payroll.settings.autoPrepareHint')" />
      </PageSection>

      <InlineAlert v-if="failure && dirty" tone="danger" :description="failure" />
      <StickyActionBar :show="dirty" :message="t('common.unsaved')" tone="warning">
        <UiButton variant="ghost" @click="reset">{{ t("common.discard") }}</UiButton>
        <UiButton variant="primary" :loading="saving" data-testid="save-settings" @click="save">{{ t("common.save") }}</UiButton>
      </StickyActionBar>
    </template>
  </div>
</template>
