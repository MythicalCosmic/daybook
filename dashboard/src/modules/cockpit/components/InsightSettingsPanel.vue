<script setup lang="ts">
/**
 * Settings › Insights (`insights/settings/`, ai.configure or company.settings): urgent insights in
 * the owner bot and the quiet hours, how sensitive the checks are, the cash buffer, the smallest
 * expense jump worth a word, and which checks run.
 */
import { computed, reactive, watch } from "vue";
import { useI18n } from "vue-i18n";

import FormField from "@/components/FormField.vue";
import MoneyInput from "@/components/MoneyInput.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import TimePicker from "@/components/TimePicker.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import UiButton from "@/components/UiButton.vue";
import { toast } from "@/components/useToast";
import { useFormat } from "@/lib/useFormat";

import { useInsightSettings, useSaveSettings, type InsightSettings } from "../api";

const { t } = useI18n();
const fmt = useFormat();
const settings = useInsightSettings();
const save = useSaveSettings();

const form = reactive({
  notify_critical_via_bot: true,
  quiet_from: "22:00" as string | null,
  quiet_to: "08:00" as string | null,
  sensitivity: "normal" as InsightSettings["sensitivity"],
  min_cash_buffer: null as string | null,
  expense_alert_min_amount: "1000000" as string | null,
  enabled: {} as Record<string, boolean>,
});

watch(
  () => settings.data.value,
  (data) => {
    if (!data) return;
    Object.assign(form, {
      notify_critical_via_bot: data.notify_critical_via_bot,
      quiet_from: data.quiet_from,
      quiet_to: data.quiet_to,
      sensitivity: data.sensitivity,
      min_cash_buffer: data.min_cash_buffer,
      expense_alert_min_amount: data.expense_alert_min_amount,
      enabled: Object.fromEntries(data.kinds.map((kind) => [kind.kind, !data.disabled_kinds.includes(kind.kind)])),
    });
  },
  { immediate: true },
);

const kinds = computed(() => settings.data.value?.kinds ?? []);

async function submit(): Promise<void> {
  try {
    await save.mutateAsync({
      notify_critical_via_bot: form.notify_critical_via_bot,
      quiet_from: form.quiet_from ?? "22:00",
      quiet_to: form.quiet_to ?? "08:00",
      sensitivity: form.sensitivity,
      min_cash_buffer: form.min_cash_buffer || null,
      expense_alert_min_amount: form.expense_alert_min_amount || "1000000",
      disabled_kinds: Object.entries(form.enabled)
        .filter(([, on]) => !on)
        .map(([kind]) => kind),
    });
    toast.success(t("cockpit.settings.saved"));
  } catch {
    // The HTTP layer showed the field errors.
  }
}
</script>

<template>
  <div v-if="settings.isPending.value" class="flex flex-col gap-3"><SkeletonBlock v-for="n in 3" :key="n" height="56px" radius="10px" /></div>
  <form v-else-if="settings.data.value" class="flex flex-col gap-6" data-testid="insight-settings" @submit.prevent="submit">
    <p class="text-sm text-muted">{{ t("cockpit.settings.description") }}</p>

    <section class="flex flex-col gap-3">
      <ToggleSwitch v-model="form.notify_critical_via_bot" :label="t('cockpit.settings.bot')" :description="t('cockpit.settings.botHint')" />
      <FormField :label="t('cockpit.settings.quiet')" :hint="t('cockpit.settings.quietHint')">
        <div class="grid max-w-sm grid-cols-2 gap-3">
          <FormField :label="t('cockpit.settings.from')"><TimePicker v-model="form.quiet_from" /></FormField>
          <FormField :label="t('cockpit.settings.to')"><TimePicker v-model="form.quiet_to" /></FormField>
        </div>
      </FormField>
    </section>

    <section class="flex flex-col gap-3">
      <FormField :label="t('cockpit.settings.sensitivity')">
        <SegmentedControl
          v-model="form.sensitivity"
          :options="[
            { value: 'low', label: t('cockpit.settings.sensitivityLow') },
            { value: 'normal', label: t('cockpit.settings.sensitivityNormal') },
            { value: 'high', label: t('cockpit.settings.sensitivityHigh') },
          ]"
        />
      </FormField>
      <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <FormField :label="t('cockpit.settings.buffer')" :hint="t('cockpit.settings.bufferHint')">
          <MoneyInput v-model="form.min_cash_buffer" />
        </FormField>
        <FormField :label="t('cockpit.settings.minAmount')">
          <MoneyInput v-model="form.expense_alert_min_amount" />
        </FormField>
      </div>
    </section>

    <section class="flex flex-col gap-2">
      <h3 class="text-md font-semibold text-fg">{{ t("cockpit.settings.kinds") }}</h3>
      <ul class="divide-y divide-line rounded-lg border border-line">
        <li v-for="kind in kinds" :key="kind.kind" class="px-3 py-2.5" :data-kind="kind.kind">
          <ToggleSwitch v-model="form.enabled[kind.kind]" :label="kind.label" :description="kind.available ? undefined : t('cockpit.settings.kindOff')" :disabled="!kind.available" />
        </li>
      </ul>
      <p v-if="settings.data.value.last_run_at" class="text-xs text-muted">{{ t("cockpit.settings.lastRun", { time: fmt.instant(settings.data.value.last_run_at, "short") }) }}</p>
    </section>

    <div><UiButton type="submit" variant="primary" :loading="save.isPending.value">{{ t("cockpit.settings.save") }}</UiButton></div>
  </form>
</template>
