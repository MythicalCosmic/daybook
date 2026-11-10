<script setup lang="ts">
/**
 * When Maslahatchi's business reviews go out and to whom (apps.briefings BriefingSettings): the
 * weekly review and its day and time (the company's clock), the monthly one on the first, and
 * whether owners alone or everyone who sees reports get one (each their own scope). Each change is
 * saved at once. Read-only without company.settings. In the Maslahatchi page's drawer and in
 * Settings › Business reviews.
 */
import { CalendarClock, Lock } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import ErrorState from "@/components/ErrorState.vue";
import FormField from "@/components/FormField.vue";
import RadioCards from "@/components/RadioCards.vue";
import SelectBox from "@/components/SelectBox.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import TimePicker from "@/components/TimePicker.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import { toast } from "@/components/useToast";
import { useCompanyStore } from "@/stores/company";

import { useBriefingSettings, useSaveBriefingSettings, type BriefingRecipients, type BriefingSettings } from "../briefings";

const { t } = useI18n();
const company = useCompanyStore();
const editable = computed(() => company.can("company.settings"));
const query = useBriefingSettings(editable);
const save = useSaveBriefingSettings();
const saving = ref<keyof BriefingSettings | null>(null);
const row = computed(() => query.data.value ?? null);

const weekdays = computed(() => Array.from({ length: 7 }, (_unused, day) => ({ value: day, label: t(`ai.advisor.weekday.${day}`) })));
const recipients = computed(() =>
  (["owners", "reports"] as BriefingRecipients[]).map((value) => ({
    value,
    label: t(`ai.advisor.settings.recipients.${value}`),
    description: t(`ai.advisor.settings.recipients.${value}Hint`),
  })),
);

async function change<K extends keyof BriefingSettings>(key: K, value: BriefingSettings[K] | null): Promise<void> {
  if (value === null || !row.value || row.value[key] === value) return;
  saving.value = key;
  try {
    await save.mutateAsync({ [key]: value } as Partial<BriefingSettings>);
    toast.success(t("ai.advisor.settings.saved"));
  } catch {
    // The reason is a toast from the HTTP layer; the form shows what is stored.
  } finally {
    saving.value = null;
  }
}
</script>

<template>
  <div class="flex flex-col gap-4" data-testid="briefing-settings">
    <p v-if="!editable" class="flex items-start gap-2 text-sm text-muted" data-testid="briefing-settings-locked">
      <Lock :size="14" class="mt-0.5 shrink-0" aria-hidden="true" />{{ t("ai.advisor.settings.locked") }}
    </p>
    <template v-else>
      <div v-if="query.isPending.value" class="flex flex-col gap-3" aria-hidden="true">
        <SkeletonBlock v-for="n in 4" :key="n" height="56px" radius="10px" />
      </div>
      <ErrorState v-else-if="query.isError.value" compact :error="query.error.value" :retry="() => query.refetch()" />
      <template v-else-if="row">
        <div class="ui-card flex flex-col divide-y divide-line">
          <div class="flex flex-col gap-4 px-4 py-4 md:px-5">
            <ToggleSwitch
              :model-value="row.weekly_enabled"
              layout="row"
              :label="t('ai.advisor.settings.weekly')"
              :description="t('ai.advisor.settings.weeklyHint')"
              :loading="saving === 'weekly_enabled'"
              data-testid="briefing-weekly"
              @update:model-value="(value: boolean) => change('weekly_enabled', value)"
            />
            <div v-if="row.weekly_enabled" class="grid gap-3 sm:grid-cols-2">
              <FormField :label="t('ai.advisor.settings.day')">
                <SelectBox :model-value="row.weekday" :options="weekdays" :disabled="saving === 'weekday'" data-testid="briefing-weekday" @update:model-value="(value) => change('weekday', value as number | null)" />
              </FormField>
              <FormField :label="t('ai.advisor.settings.time')" :hint="t('ai.advisor.settings.timeHint')">
                <TimePicker :model-value="row.send_at" :disabled="saving === 'send_at'" data-testid="briefing-time" @update:model-value="(value) => change('send_at', value)" />
              </FormField>
            </div>
          </div>
          <div class="px-4 py-4 md:px-5">
            <ToggleSwitch
              :model-value="row.monthly_enabled"
              layout="row"
              :label="t('ai.advisor.settings.monthly')"
              :description="t('ai.advisor.settings.monthlyHint')"
              :loading="saving === 'monthly_enabled'"
              data-testid="briefing-monthly"
              @update:model-value="(value: boolean) => change('monthly_enabled', value)"
            />
          </div>
        </div>
        <FormField :label="t('ai.advisor.settings.recipients.label')">
          <RadioCards :model-value="row.recipients" :options="recipients" :columns="2" :disabled="saving === 'recipients'" data-testid="briefing-recipients" @update:model-value="(value) => change('recipients', value as BriefingRecipients | null)" />
        </FormField>
        <p class="flex items-start gap-2 text-sm text-muted">
          <CalendarClock :size="14" class="mt-0.5 shrink-0" aria-hidden="true" />{{ t("ai.advisor.settings.note") }}
        </p>
      </template>
    </template>
  </div>
</template>
