<script setup lang="ts">
/**
 * Settings › Training: when a video counts as watched, the fastest playing that still counts,
 * reminders before a deadline and when the manager hears, certificates (their prefix and the next
 * number), whether staff may start optional courses on their own, and the video storage limit.
 * The question of the day's settings live in the quizzes module.
 */
import { computed, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import FormField from "@/components/FormField.vue";
import NumberInput from "@/components/NumberInput.vue";
import ProgressBar from "@/components/ProgressBar.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import TextInput from "@/components/TextInput.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import UiButton from "@/components/UiButton.vue";
import { toast } from "@/components/useToast";
import { useCompanyId } from "@/stores/company";

import { learningApi, useLearningSettings, useRefresh } from "../api";
import { bytes, nextCertificate } from "../lib";

const { t, locale } = useI18n();
const cid = useCompanyId();
const refresh = useRefresh();
const settings = useLearningSettings();

const form = reactive({
  completion_percent: 90,
  max_speed_percent: 200,
  remind_before_days: 2,
  escalate_after_days: 3,
  certificates: true,
  certificate_prefix: "SRT",
  catalog_for_staff: true,
  storage_limit_mb: 10240,
});
watch(
  () => settings.data.value,
  (data) => {
    if (data) Object.assign(form, { ...data });
  },
  { immediate: true },
);
const used = computed(() => settings.data.value?.storage_used_bytes ?? 0);
const limitBytes = computed(() => form.storage_limit_mb * 1024 * 1024);
const example = computed(() => nextCertificate(form.certificate_prefix.toUpperCase(), settings.data.value?.next_certificate_number ?? 1, new Date().getFullYear()));

const saving = ref(false);
async function save(): Promise<void> {
  saving.value = true;
  try {
    await learningApi.updateSettings(cid.value, {
      completion_percent: form.completion_percent,
      max_speed_percent: form.max_speed_percent,
      remind_before_days: form.remind_before_days,
      escalate_after_days: form.escalate_after_days,
      certificates: form.certificates,
      certificate_prefix: form.certificate_prefix.trim().toUpperCase(),
      catalog_for_staff: form.catalog_for_staff,
      storage_limit_mb: form.storage_limit_mb,
    });
    toast.success(t("learning.settings.saved"));
    refresh();
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <div class="flex flex-col gap-6">
    <template v-if="!settings.data.value">
      <SkeletonBlock v-for="n in 4" :key="n" height="56px" radius="10px" />
    </template>
    <template v-else>
      <section class="flex flex-col gap-4">
        <h3 class="text-sm font-semibold text-fg">{{ t("learning.settings.watching") }}</h3>
        <div class="grid gap-4 sm:grid-cols-2">
          <FormField :label="t('learning.settings.completion')" :hint="t('learning.settings.completionHint')">
            <NumberInput v-model="form.completion_percent" :min="50" :max="100" suffix="%" />
          </FormField>
          <FormField :label="t('learning.settings.speed')" :hint="t('learning.settings.speedHint')">
            <NumberInput v-model="form.max_speed_percent" :min="100" :max="400" :step="25" suffix="%" />
          </FormField>
        </div>
      </section>
      <section class="flex flex-col gap-4">
        <h3 class="text-sm font-semibold text-fg">{{ t("learning.settings.deadlines") }}</h3>
        <div class="grid gap-4 sm:grid-cols-2">
          <FormField :label="t('learning.settings.remind')" :hint="t('learning.settings.remindHint')">
            <NumberInput v-model="form.remind_before_days" :min="0" :max="30" :suffix="t('learning.settings.days')" />
          </FormField>
          <FormField :label="t('learning.settings.escalate')" :hint="t('learning.settings.escalateHint')">
            <NumberInput v-model="form.escalate_after_days" :min="0" :max="60" :suffix="t('learning.settings.days')" />
          </FormField>
        </div>
        <ToggleSwitch v-model="form.catalog_for_staff" layout="row" :label="t('learning.settings.catalog')" :description="t('learning.settings.catalogHint')" />
      </section>
      <section class="flex flex-col gap-4">
        <h3 class="text-sm font-semibold text-fg">{{ t("learning.settings.certificates") }}</h3>
        <ToggleSwitch v-model="form.certificates" layout="row" :label="t('learning.settings.giveCertificates')" :description="t('learning.settings.certificatesHint')" />
        <FormField v-if="form.certificates" :label="t('learning.settings.prefix')" :hint="t('learning.settings.prefixHint', { example })" class="sm:max-w-xs">
          <TextInput v-model="form.certificate_prefix" :maxlength="8" />
        </FormField>
      </section>
      <section class="flex flex-col gap-3">
        <h3 class="text-sm font-semibold text-fg">{{ t("learning.settings.storage") }}</h3>
        <ProgressBar :value="used" :max="limitBytes || 1" tone="auto" size="sm" :value-text="t('learning.settings.storageUsed', { used: bytes(used, locale), limit: bytes(limitBytes, locale) })" show-value />
        <FormField :label="t('learning.settings.limit')" :hint="t('learning.settings.limitHint')" class="sm:max-w-xs">
          <NumberInput v-model="form.storage_limit_mb" :min="100" :max="1000000" :step="1024" suffix="MB" grouping />
        </FormField>
      </section>
      <div>
        <UiButton variant="primary" :loading="saving" @click="save">{{ t("common.save") }}</UiButton>
      </div>
    </template>
  </div>
</template>
