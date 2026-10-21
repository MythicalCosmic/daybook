<script setup lang="ts">
/**
 * Settings → Sales (plan §6.2, the `sales` panel): how sales are recorded (shift totals or single
 * receipts; invoices arrive with package J), when the business day ends, the cash tolerance, the
 * blind count and photo rules, and when owners hear about late openings, open tills, unconfirmed
 * handovers and big payouts. Saved together; the page warns before leaving unsaved changes.
 */
import { computed, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import ErrorState from "@/components/ErrorState.vue";
import FormField from "@/components/FormField.vue";
import MoneyInput from "@/components/MoneyInput.vue";
import NumberInput from "@/components/NumberInput.vue";
import PageSection from "@/components/PageSection.vue";
import RadioCards from "@/components/RadioCards.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StickyActionBar from "@/components/StickyActionBar.vue";
import TimePicker from "@/components/TimePicker.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import UiButton from "@/components/UiButton.vue";
import { toast } from "@/components/useToast";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { useCompanyStore } from "@/stores/company";

import { salesApi, useSalesMutation, useSettings } from "../api";
import type { SalesSettings } from "../types";

const { t } = useI18n();
const company = useCompanyStore();
const query = useSettings();
const skeleton = useDelayedPending(computed(() => query.isPending.value));
const canEdit = computed(() => company.can("sales.manage"));

const form = reactive<SalesSettings>({
  business_day_ends_at: "04:00",
  cash_tolerance: "0",
  blind_cash_count: true,
  require_z_photo: true,
  require_terminal_photo: true,
  mode: "shift_totals",
  handover_confirm_hours: 2,
  big_payout_alert: null,
  late_open_minutes: 10,
  close_alert_minutes: 60,
});
const loaded = ref("");
watch(
  () => query.data.value,
  (data) => {
    if (!data) return;
    Object.assign(form, data);
    loaded.value = JSON.stringify(data);
  },
  { immediate: true },
);
const dirty = computed(() => !!loaded.value && JSON.stringify({ ...form }) !== loaded.value);
const modes = computed(() => [
  { value: "shift_totals" as const, label: t("sales.settings.mode.shift_totals"), description: t("sales.settings.mode.shift_totalsHint") },
  { value: "receipts" as const, label: t("sales.settings.mode.receipts"), description: t("sales.settings.mode.receiptsHint") },
  { value: "invoices" as const, label: t("sales.settings.mode.invoices"), description: t("sales.settings.mode.invoicesHint"), disabled: true },
]);

const save = useSalesMutation((cid, input: Partial<SalesSettings>) => salesApi.saveSettings(cid, input));
async function submit(): Promise<void> {
  const saved = await save.mutateAsync({ ...form });
  loaded.value = JSON.stringify(saved);
  toast.success(t("sales.settings.saved"));
}
</script>

<template>
  <div>
    <div v-if="skeleton" class="flex flex-col gap-3"><SkeletonBlock v-for="n in 3" :key="n" height="120px" radius="12px" /></div>
    <ErrorState v-else-if="query.isError.value" :error="query.error.value" :retry="() => query.refetch()" />
    <form v-else class="flex flex-col gap-4" @submit.prevent="submit">
      <PageSection variant="card" :title="t('sales.settings.recording')" :description="t('sales.settings.recordingHint')">
        <div class="flex flex-col gap-4">
          <RadioCards v-model="form.mode" :options="modes" :columns="3" :disabled="!canEdit" />
          <div class="grid gap-4 sm:grid-cols-2">
            <FormField :label="t('sales.settings.dayEnds')" :hint="t('sales.settings.dayEndsHint')">
              <TimePicker v-model="form.business_day_ends_at" :disabled="!canEdit" :step="30" />
            </FormField>
            <FormField :label="t('sales.settings.tolerance')" :hint="t('sales.settings.toleranceHint')">
              <MoneyInput v-model="form.cash_tolerance" :disabled="!canEdit" />
            </FormField>
          </div>
        </div>
      </PageSection>
      <PageSection variant="card" :title="t('sales.settings.control')" :description="t('sales.settings.controlHint')">
        <div class="flex flex-col divide-y divide-line">
          <ToggleSwitch v-model="form.blind_cash_count" layout="row" :label="t('sales.settings.blind')" :description="t('sales.settings.blindHint')" :disabled="!canEdit" class="py-3 first:pt-0" />
          <ToggleSwitch v-model="form.require_z_photo" layout="row" :label="t('sales.settings.zPhoto')" :description="t('sales.settings.zPhotoHint')" :disabled="!canEdit" class="py-3" />
          <ToggleSwitch v-model="form.require_terminal_photo" layout="row" :label="t('sales.settings.terminalPhoto')" :description="t('sales.settings.terminalPhotoHint')" :disabled="!canEdit" class="py-3 last:pb-0" />
        </div>
      </PageSection>
      <PageSection variant="card" :title="t('sales.settings.alerts')" :description="t('sales.settings.alertsHint')">
        <div class="grid gap-4 sm:grid-cols-2">
          <FormField :label="t('sales.settings.lateOpen')" :hint="t('sales.settings.lateOpenHint')">
            <NumberInput v-model="form.late_open_minutes" :min="1" :max="240" :suffix="t('sales.settings.minutes')" :disabled="!canEdit" />
          </FormField>
          <FormField :label="t('sales.settings.closeAlert')" :hint="t('sales.settings.closeAlertHint')">
            <NumberInput v-model="form.close_alert_minutes" :min="1" :max="720" :suffix="t('sales.settings.minutes')" :disabled="!canEdit" />
          </FormField>
          <FormField :label="t('sales.settings.handover')" :hint="t('sales.settings.handoverHint')">
            <NumberInput v-model="form.handover_confirm_hours" :min="0" :max="72" :suffix="t('sales.settings.hours')" :disabled="!canEdit" />
          </FormField>
          <FormField :label="t('sales.settings.bigPayout')" :hint="t('sales.settings.bigPayoutHint')" optional>
            <MoneyInput v-model="form.big_payout_alert" :disabled="!canEdit" />
          </FormField>
        </div>
      </PageSection>
      <!-- The same bar as every other settings form. -->
      <StickyActionBar :show="canEdit && dirty" :message="t('common.unsaved')" tone="warning">
        <UiButton variant="ghost" @click="Object.assign(form, JSON.parse(loaded))">{{ t("common.discard") }}</UiButton>
        <UiButton type="submit" variant="primary" :loading="save.isPending.value">{{ t("common.save") }}</UiButton>
      </StickyActionBar>
    </form>
  </div>
</template>
