<script setup lang="ts">
/**
 * Face ID › Settings: whether linked people's scans count in attendance (when Attendance is on) and
 * how people use a one-door terminal (only when they come: later scans are only seen; or both ways),
 * what Telegram says (who came, every scan, or nothing), group posts, the person's own message,
 * unknown-face alerts, repeats and how long snapshots are kept. Saves only what changed; the server
 * audits it. Faces never leave the terminal; employees should agree in writing.
 */
import { ArrowLeftRight, LogIn, ShieldCheck } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { unshownFieldError } from "@/api/http";
import ErrorState from "@/components/ErrorState.vue";
import FormField from "@/components/FormField.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import NumberInput from "@/components/NumberInput.vue";
import PageHeader from "@/components/PageHeader.vue";
import PageSection from "@/components/PageSection.vue";
import RadioCards from "@/components/RadioCards.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StickyActionBar from "@/components/StickyActionBar.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import UiButton from "@/components/UiButton.vue";
import { toast } from "@/components/useToast";
import { useCompanyId, useCompanyStore } from "@/stores/company";

import { saveSettings, useRefresh, useSettings } from "../api";
import type { FaceIdSettings, ScanMode, TelegramMode } from "../types";

const { t } = useI18n();
const companyId = useCompanyId();
const company = useCompanyStore();
const refresh = useRefresh();
const query = useSettings();
const draft = ref<FaceIdSettings | null>(null);
const saving = ref(false);
const failure = ref<string | null>(null);

watch(
  () => query.data.value,
  (value) => {
    if (value) draft.value = { ...value };
  },
  { immediate: true },
);

const changes = computed<Partial<FaceIdSettings>>(() => {
  const base = query.data.value;
  const next = draft.value;
  if (!base || !next) return {};
  const out: Partial<FaceIdSettings> = {};
  for (const key of Object.keys(next) as Array<keyof FaceIdSettings>) {
    if (next[key] !== base[key]) (out as Record<string, unknown>)[key] = next[key];
  }
  return out;
});
const dirty = computed(() => Object.keys(changes.value).length > 0);
const attendanceOn = computed(() => company.enabled("attendance"));
const telegramOptions = computed(() =>
  (["arrivals", "every_scan", "off"] as TelegramMode[]).map((value) => ({ value, label: t(`faceid.settings.telegram.${value}`), description: t(`faceid.settings.telegram.${value}Hint`) })),
);
const SCAN_MODE_ICONS = { arrival: LogIn, both: ArrowLeftRight } as const;
const scanModeOptions = computed(() =>
  (["arrival", "both"] as ScanMode[]).map((value) => ({ value, label: t(`faceid.settings.scanMode.${value}`), description: t(`faceid.settings.scanMode.${value}Hint`), icon: SCAN_MODE_ICONS[value] })),
);

async function save(): Promise<void> {
  if (!dirty.value) return;
  saving.value = true;
  failure.value = null;
  try {
    await saveSettings(companyId.value, changes.value);
    toast.success(t("faceid.settings.saved"));
    refresh();
  } catch (error) {
    failure.value = unshownFieldError(error);
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <div class="flex flex-col gap-6 pb-16">
    <PageHeader :title="t('faceid.settings.title')" :description="t('faceid.settings.description')" />

    <div v-if="query.isPending.value" class="flex flex-col gap-4">
      <SkeletonBlock v-for="n in 3" :key="n" height="96px" radius="12px" />
    </div>
    <ErrorState v-else-if="query.isError.value" :error="query.error.value" :retry="() => query.refetch()" />
    <template v-else-if="draft">
      <PageSection variant="card" flush :heading-level="2" :title="t('faceid.settings.attendanceTitle')" :description="t('faceid.settings.attendanceHint')">
        <div class="flex flex-col divide-y divide-line">
          <ToggleSwitch v-model="draft.attendance" layout="row" class="px-4 py-3 md:px-5" :label="t('faceid.settings.attendance')" :description="attendanceOn ? t('faceid.settings.attendanceOn') : t('faceid.settings.attendanceOff')" />
          <div class="px-4 py-3 md:px-5" data-testid="scan-mode">
            <FormField :label="t('faceid.settings.scanMode.title')" :hint="t('faceid.settings.scanMode.hint')" :disabled="!draft.attendance">
              <RadioCards v-model="draft.scan_mode" :columns="2" :options="scanModeOptions" />
            </FormField>
          </div>
          <ToggleSwitch v-model="draft.notify_employee" layout="row" class="px-4 py-3 md:px-5" :disabled="!draft.attendance" :label="t('faceid.settings.notifyEmployee')" :description="t('faceid.settings.notifyEmployeeHint')" />
          <div class="flex flex-wrap items-center justify-between gap-3 px-4 py-3 md:px-5">
            <div class="min-w-0 flex-1">
              <p class="text-sm font-medium text-fg">{{ t("faceid.settings.repeat") }}</p>
              <p class="text-sm text-muted">{{ t("faceid.settings.repeatHint") }}</p>
            </div>
            <NumberInput v-model="draft.repeat_minutes" class="w-36" :min="1" :max="60" :suffix="t('faceid.unit.min')" />
          </div>
        </div>
      </PageSection>

      <PageSection variant="card" flush :heading-level="2" :title="t('faceid.settings.telegramTitle')" :description="t('faceid.settings.telegramHint')">
        <div class="flex flex-col divide-y divide-line">
          <div class="px-4 py-3 md:px-5">
            <RadioCards v-model="draft.telegram" :columns="3" :options="telegramOptions" />
          </div>
          <ToggleSwitch v-model="draft.group_posts" layout="row" class="px-4 py-3 md:px-5" :label="t('faceid.settings.groupPosts')" :description="t('faceid.settings.groupPostsHint')" />
          <ToggleSwitch v-model="draft.group_photos" layout="row" class="px-4 py-3 md:px-5" :disabled="!draft.group_posts" :label="t('faceid.settings.groupPhotos')" :description="t('faceid.settings.groupPhotosHint')" />
          <ToggleSwitch v-model="draft.alert_strangers" layout="row" class="px-4 py-3 md:px-5" :label="t('faceid.settings.strangers')" :description="t('faceid.settings.strangersHint')" />
        </div>
      </PageSection>

      <PageSection variant="card" flush :heading-level="2" :title="t('faceid.settings.privacyTitle')" :description="t('faceid.settings.privacyHint')">
        <div class="flex flex-col divide-y divide-line">
          <div class="flex flex-wrap items-center justify-between gap-3 px-4 py-3 md:px-5">
            <div class="min-w-0 flex-1">
              <p class="text-sm font-medium text-fg">{{ t("faceid.settings.photoDays") }}</p>
              <p class="text-sm text-muted">{{ t("faceid.settings.photoDaysHint") }}</p>
            </div>
            <NumberInput v-model="draft.photo_days" class="w-36" :min="0" :max="365" :suffix="t('faceid.unit.days')" />
          </div>
          <p class="flex items-start gap-2 px-4 py-3 text-sm text-muted md:px-5">
            <ShieldCheck :size="16" class="mt-0.5 shrink-0 text-subtle" aria-hidden="true" />
            <span>{{ t("faceid.privacy") }}</span>
          </p>
        </div>
      </PageSection>

      <InlineAlert v-if="failure && dirty" tone="danger" :description="failure" />
      <StickyActionBar :show="dirty" :message="t('common.unsaved')" tone="warning">
        <UiButton variant="ghost" @click="draft = { ...query.data.value! }">{{ t("common.discard") }}</UiButton>
        <UiButton variant="primary" :loading="saving" @click="save">{{ t("common.save") }}</UiButton>
      </StickyActionBar>
    </template>
  </div>
</template>
