<script setup lang="ts">
/**
 * Settings › HR (the module's settings panel): how many days ahead documents, contracts and
 * probation endings are flagged, whether birthdays and work anniversaries are celebrated, and the
 * pharmacist coverage rule (plan §14.9) with who counts as a pharmacist (its own Save: it is the
 * setup step `hr.pharmacists`). Saves only what changed; the server audits it.
 */
import { computed, ref, useId, watch } from "vue";
import { useI18n } from "vue-i18n";

import { unshownFieldError } from "@/api/http";
import ErrorState from "@/components/ErrorState.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import NumberInput from "@/components/NumberInput.vue";
import PageSection from "@/components/PageSection.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StickyActionBar from "@/components/StickyActionBar.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import UiButton from "@/components/UiButton.vue";
import { toast } from "@/components/useToast";
import { useCompanyId } from "@/stores/company";

import { hrApi, useHrSettings, useRefresh } from "../api";
import type { HrSettings } from "../types";
import PharmacistsEditor from "./PharmacistsEditor.vue";

const { t } = useI18n();
const companyId = useCompanyId();
const refresh = useRefresh();
const query = useHrSettings();
const draft = ref<HrSettings | null>(null);
const saving = ref(false);
const failure = ref<string | null>(null);
const uid = useId();

watch(
  () => query.data.value,
  (value) => {
    if (value) draft.value = { ...value };
  },
  { immediate: true },
);

const changes = computed<Partial<HrSettings>>(() => {
  const base = query.data.value;
  const next = draft.value;
  if (!base || !next) return {};
  const out: Partial<HrSettings> = {};
  for (const key of Object.keys(next) as Array<keyof HrSettings>) {
    if (next[key] !== base[key]) (out as Record<string, unknown>)[key] = next[key];
  }
  return out;
});
const dirty = computed(() => Object.keys(changes.value).length > 0);

const windows = [
  { key: "document_warn_days", max: 180 },
  { key: "contract_warn_days", max: 180 },
  { key: "probation_warn_days", max: 60 },
] as const;

/** Pharmacist coverage (plan §14.9): how many are needed, how long a gap waits, how far ahead. */
const coverageNumbers = [
  { key: "coverage_min", min: 1, max: 10, suffix: "hr.settings.people" },
  { key: "coverage_alert_minutes", min: 5, max: 240, suffix: "hr.settings.minutes" },
  { key: "coverage_days", min: 1, max: 31, suffix: "hr.settings.days" },
] as const;
const coverageKnown = computed(() => draft.value?.coverage_enabled !== undefined);

async function save(): Promise<void> {
  if (!dirty.value) return;
  saving.value = true;
  failure.value = null;
  try {
    await hrApi.saveSettings(companyId.value, changes.value);
    toast.success(t("hr.settings.saved"));
    refresh();
  } catch (error) {
    failure.value = unshownFieldError(error);
  } finally {
    saving.value = false;
  }
}

function reset(): void {
  if (query.data.value) draft.value = { ...query.data.value };
}
</script>

<template>
  <div class="flex flex-col gap-6 pb-16">
    <div v-if="query.isPending.value" class="flex flex-col gap-4">
      <SkeletonBlock v-for="n in 3" :key="n" height="64px" radius="12px" />
    </div>
    <ErrorState v-else-if="query.isError.value" :error="query.error.value" :retry="() => query.refetch()" />
    <template v-else-if="draft">
      <PageSection variant="card" flush :heading-level="3" :title="t('hr.settings.warnTitle')" :description="t('hr.settings.warnHint')">
        <div class="flex flex-col divide-y divide-line">
          <div v-for="row in windows" :key="row.key" class="flex flex-col gap-2 px-4 py-3 sm:flex-row sm:items-center sm:gap-6 md:px-5">
            <div class="min-w-0 flex-1">
              <label :for="`${uid}-${row.key}`" class="text-sm font-medium text-fg">{{ t(`hr.settings.${row.key}`) }}</label>
              <p class="mt-0.5 text-xs text-muted">{{ t(`hr.settings.${row.key}Hint`) }}</p>
            </div>
            <div class="w-full shrink-0 sm:w-40">
              <NumberInput :id="`${uid}-${row.key}`" v-model="draft[row.key]" :min="1" :max="row.max" :suffix="t('hr.settings.days')" class="w-full" />
            </div>
          </div>
        </div>
      </PageSection>

      <PageSection variant="card" flush :heading-level="3" :title="t('hr.settings.celebrationsTitle')" :description="t('hr.settings.celebrationsHint')">
        <div class="flex flex-col divide-y divide-line">
          <ToggleSwitch v-model="draft.celebrations_enabled" layout="row" class="px-4 py-3 md:px-5" :label="t('hr.settings.celebrations')" :description="t('hr.settings.celebrationsBody')" />
          <ToggleSwitch
            v-model="draft.celebrate_anniversaries"
            layout="row"
            class="px-4 py-3 md:px-5"
            :disabled="!draft.celebrations_enabled"
            :label="t('hr.settings.anniversaries')"
            :description="t('hr.settings.anniversariesBody')"
          />
        </div>
      </PageSection>

      <template v-if="coverageKnown">
        <PageSection variant="card" flush :heading-level="3" :title="t('hr.settings.coverageTitle')" :description="t('hr.settings.coverageHint')" data-coverage-settings>
          <div class="flex flex-col divide-y divide-line">
            <ToggleSwitch v-model="draft.coverage_enabled!" layout="row" class="px-4 py-3 md:px-5" :label="t('hr.settings.coverage_enabled')" :description="t('hr.settings.coverage_enabledBody')" />
            <template v-if="draft.coverage_enabled">
              <div v-for="row in coverageNumbers" :key="row.key" class="flex flex-col gap-2 px-4 py-3 sm:flex-row sm:items-center sm:gap-6 md:px-5">
                <div class="min-w-0 flex-1">
                  <label :for="`${uid}-${row.key}`" class="text-sm font-medium text-fg">{{ t(`hr.settings.${row.key}`) }}</label>
                  <p class="mt-0.5 text-xs text-muted">{{ t(`hr.settings.${row.key}Hint`) }}</p>
                </div>
                <div class="w-full shrink-0 sm:w-40">
                  <NumberInput :id="`${uid}-${row.key}`" v-model="draft[row.key]!" :min="row.min" :max="row.max" :suffix="t(row.suffix)" class="w-full" />
                </div>
              </div>
              <ToggleSwitch
                v-model="draft.coverage_needs_documents!"
                layout="row"
                class="px-4 py-3 md:px-5"
                :label="t('hr.settings.coverage_needs_documents')"
                :description="t('hr.settings.coverage_needs_documentsBody')"
              />
              <ToggleSwitch
                v-model="draft.unqualified_seller_alert!"
                layout="row"
                class="px-4 py-3 md:px-5"
                :label="t('hr.settings.unqualified_seller_alert')"
                :description="t('hr.settings.unqualified_seller_alertBody')"
              />
            </template>
          </div>
        </PageSection>

        <PageSection v-if="draft.coverage_enabled" variant="card" flush :heading-level="3" :title="t('hr.pharmacists.title')" :description="t('hr.pharmacists.hint')">
          <PharmacistsEditor />
        </PageSection>
      </template>

      <InlineAlert v-if="failure && dirty" tone="danger" :description="failure" />
      <StickyActionBar :show="dirty" :message="t('common.unsaved')" tone="warning">
        <UiButton variant="ghost" @click="reset">{{ t("common.discard") }}</UiButton>
        <UiButton variant="primary" :loading="saving" @click="save">{{ t("common.save") }}</UiButton>
      </StickyActionBar>
    </template>
  </div>
</template>
