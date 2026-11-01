<script setup lang="ts">
/**
 * Settings › AI (ai.configure): on or off (with the terms), the monthly budget and what was spent,
 * what the AI may read, how long voice notes are kept and how many instructions a person may send
 * a day. Each change saves at once, as in every settings panel.
 */
import { PowerOff, ShieldAlert } from "@lucide/vue";
import { useQueryClient } from "@tanstack/vue-query";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import ErrorState from "@/components/ErrorState.vue";
import FormField from "@/components/FormField.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import NumberInput from "@/components/NumberInput.vue";
import ProgressBar from "@/components/ProgressBar.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import UiButton from "@/components/UiButton.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { useBreakpoints } from "@/lib/useBreakpoints";
import { useFormat } from "@/lib/useFormat";
import { useSessionStore } from "@/stores/session";

import { aiApi, aiKeys, useAiSettings, useAiStatus, useCompanyId } from "../api";
import { budgetShare } from "../lib";
import type { AiSettings, AiSettingsPatch } from "../types";
import StatusPills from "./StatusPills.vue";
import TurnOnCard from "./TurnOnCard.vue";

const { t } = useI18n();
const fmt = useFormat();
const { isPhone } = useBreakpoints();
const cid = useCompanyId();
const client = useQueryClient();
const session = useSessionStore();
const confirm = useConfirm();
const status = useAiStatus();
const settings = useAiSettings(() => status.data.value?.can_configure ?? false);
const saving = ref<keyof AiSettings | null>(null);
const turningOff = ref(false);

const share = computed(() => budgetShare(status.data.value?.budget));
const enabledLine = computed(() => {
  const data = settings.data.value;
  if (!data?.enabled) return "";
  if (data.enabled_by_name && data.enabled_at) return t("ai.settings.onSince", { name: data.enabled_by_name, date: fmt.day(data.enabled_at.slice(0, 10), "long") });
  return t("ai.settings.on");
});

async function save<K extends keyof AiSettingsPatch>(field: K, value: AiSettingsPatch[K]): Promise<void> {
  const key = aiKeys.settings(cid.value);
  const before = client.getQueryData<AiSettings>(key);
  if (before && before[field] === value) return;
  if (before) client.setQueryData(key, { ...before, [field]: value });
  saving.value = field;
  try {
    client.setQueryData(key, await aiApi.saveSettings(cid.value, { [field]: value }));
    if (field === "monthly_budget_usd") void client.invalidateQueries({ queryKey: aiKeys.status(cid.value) });
    toast.success(t("ai.settings.saved"));
  } catch {
    if (before) client.setQueryData(key, before);
  } finally {
    saving.value = null;
  }
}

async function turnOff(): Promise<void> {
  const answer = await confirm({
    title: t("ai.settings.offTitle"),
    message: t("ai.settings.offBody"),
    confirmLabel: t("ai.settings.offConfirm"),
    tone: "danger",
    icon: PowerOff,
  });
  if (!answer) return;
  turningOff.value = true;
  try {
    client.setQueryData(aiKeys.status(cid.value), await aiApi.disable(cid.value));
    void client.invalidateQueries({ queryKey: aiKeys.all(cid.value) });
    void session.loadMe().catch(() => undefined);
    toast.info(t("ai.settings.offDone"));
  } catch {
    // The reason is a toast.
  } finally {
    turningOff.value = false;
  }
}

function enabled(): void {
  void settings.refetch();
}
</script>

<template>
  <div class="flex flex-col gap-5" data-testid="ai-settings">
    <div v-if="status.isPending.value" class="flex flex-col gap-3" aria-hidden="true">
      <SkeletonBlock height="32px" width="60%" radius="8px" />
      <SkeletonBlock height="180px" radius="12px" />
    </div>
    <ErrorState v-else-if="status.isError.value" compact :error="status.error.value" :retry="() => status.refetch()" />
    <template v-else-if="status.data.value">
      <div class="flex flex-wrap gap-2"><StatusPills :status="status.data.value" /></div>
      <InlineAlert v-if="settings.data.value?.platform_blocked" tone="danger" :icon="ShieldAlert" :title="t('ai.settings.blockedTitle')" :description="t('ai.settings.blockedBody')" />

      <TurnOnCard v-if="!status.data.value.enabled" compact @enabled="enabled" />

      <template v-else>
        <div v-if="!settings.data.value" class="flex flex-col gap-3" aria-hidden="true"><SkeletonBlock v-for="n in 3" :key="n" height="64px" radius="12px" /></div>
        <template v-else>
          <div class="ui-card flex flex-col divide-y divide-line">
            <div class="flex flex-wrap items-center gap-3 px-4 py-3.5 md:px-5">
              <span class="min-w-0 flex-1">
                <span class="flex items-center gap-2 text-base font-medium text-fg"><span class="size-2 rounded-full bg-success" aria-hidden="true" />{{ t("ai.settings.onTitle") }}</span>
                <span class="mt-0.5 block text-sm text-muted">{{ enabledLine }}</span>
              </span>
              <UiButton variant="ghost" class="text-danger" :icon="PowerOff" :loading="turningOff" data-testid="ai-disable" @click="turnOff">{{ t("ai.settings.turnOff") }}</UiButton>
            </div>
            <div class="flex flex-col gap-3 px-4 py-3.5 md:px-5">
              <FormField :label="t('ai.settings.budget')" :hint="t('ai.settings.budgetHint')">
                <NumberInput
                  class="max-w-[200px]"
                  :model-value="Number(settings.data.value.monthly_budget_usd)"
                  :min="0"
                  :max="10000"
                  :step="5"
                  :decimals="2"
                  :size="isPhone ? 'lg' : 'md'"
                  prefix="$"
                  @update:model-value="(value: number | null) => value !== null && save('monthly_budget_usd', value.toFixed(2))"
                />
              </FormField>
              <div v-if="status.data.value.budget" class="flex flex-col gap-1.5">
                <ProgressBar :value="share * 100" :max="100" size="sm" :tone="share >= 0.9 ? 'danger' : share >= 0.7 ? 'warning' : 'primary'" :label="t('ai.settings.spentLabel')" />
                <p class="num text-sm text-muted">
                  {{ t("ai.settings.spent", { spent: `$${status.data.value.budget.spent_usd}`, total: `$${status.data.value.budget.monthly_usd}` }) }}
                  · {{ t("ai.settings.resets", { date: fmt.day(status.data.value.budget.resets_on, "long") }) }}
                </p>
              </div>
            </div>
          </div>

          <section class="flex flex-col gap-2">
            <h3 class="px-1 text-sm font-semibold text-fg">{{ t("ai.settings.reads") }}</h3>
            <div class="ui-card flex flex-col divide-y divide-line">
              <ToggleSwitch
                v-for="field in ['share_task_text', 'share_finance', 'share_salaries'] as const"
                :key="field"
                class="px-4 py-3.5 md:px-5"
                layout="row"
                :model-value="settings.data.value[field]"
                :label="t(`ai.settings.${field}`)"
                :description="t(`ai.settings.${field}.hint`)"
                :loading="saving === field"
                @update:model-value="(value: boolean) => save(field, value)"
              />
            </div>
          </section>

          <section class="flex flex-col gap-2">
            <h3 class="px-1 text-sm font-semibold text-fg">{{ t("ai.settings.voice") }}</h3>
            <div class="ui-card flex flex-col divide-y divide-line">
              <FormField class="px-4 py-3.5 md:px-5" :label="t('ai.settings.retention')" :hint="t('ai.settings.retentionHint')">
                <NumberInput
                  class="max-w-[200px]"
                  :model-value="settings.data.value.voice_retention_days"
                  :min="1"
                  :max="365"
                  :size="isPhone ? 'lg' : 'md'"
                  steppers
                  :suffix="t('ai.settings.days')"
                  @update:model-value="(value: number | null) => value !== null && save('voice_retention_days', value)"
                />
              </FormField>
              <FormField class="px-4 py-3.5 md:px-5" :label="t('ai.settings.daily')" :hint="t('ai.settings.dailyHint')">
                <NumberInput
                  class="max-w-[200px]"
                  :model-value="settings.data.value.member_daily_drafts"
                  :min="1"
                  :max="500"
                  :size="isPhone ? 'lg' : 'md'"
                  steppers
                  @update:model-value="(value: number | null) => value !== null && save('member_daily_drafts', value)"
                />
              </FormField>
            </div>
          </section>
        </template>
      </template>
    </template>
  </div>
</template>
