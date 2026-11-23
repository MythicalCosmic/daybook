<script setup lang="ts">
/**
 * Ko‘z › Settings (docs/KOZ.md §6.7), in four groups: the alert rules, who gets alerts, privacy,
 * and recording and storage. Every setting says what it does in plain words and shows its default,
 * with a way back to it. Only what changed is saved (PATCH); the server keeps the audit. Without
 * `vision.manage` the page reads the same but nothing can be changed.
 */
import { RotateCcw } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { unshownFieldError } from "@/api/http";
import ErrorState from "@/components/ErrorState.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import NumberInput from "@/components/NumberInput.vue";
import PageHeader from "@/components/PageHeader.vue";
import PageSection from "@/components/PageSection.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StickyActionBar from "@/components/StickyActionBar.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import UiButton from "@/components/UiButton.vue";
import { toast } from "@/components/useToast";
import { useFormat } from "@/lib/useFormat";
import { useCompanyId, useCompanyStore } from "@/stores/company";

import { saveSettings, useRefresh, useSettings } from "../api";
import { formatSeconds } from "../lib/format";
import { DEFAULT_RULES, LIMITS, changedSettings, clampSetting, type NumericSetting } from "../lib/rules";
import type { VisionSettings } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const companyId = useCompanyId();
const refresh = useRefresh();
const query = useSettings();
const canManage = computed(() => company.can("vision.manage"));

const draft = ref<VisionSettings | null>(null);
const saving = ref(false);
const failure = ref<string | null>(null);
const fieldErrors = ref<Record<string, string>>({});
watch(
  () => query.data.value,
  (value) => {
    if (value) draft.value = { ...value };
  },
  { immediate: true },
);
const changes = computed(() => (query.data.value && draft.value ? changedSettings(query.data.value, draft.value) : {}));
const dirty = computed(() => Object.keys(changes.value).length > 0);

type Row =
  | { key: NumericSetting; type: "number"; unit: "people" | "s" | "h" | "days" }
  | { key: "analysis_fps" | "live_fps"; type: "fps" }
  | { key: keyof VisionSettings; type: "toggle" };

const GROUPS: Array<{ id: string; rows: Row[] }> = [
  {
    id: "rules",
    rows: [
      { key: "queue_people", type: "number", unit: "people" },
      { key: "queue_wait_s", type: "number", unit: "s" },
      { key: "unattended_s", type: "number", unit: "s" },
      { key: "clear_after_s", type: "number", unit: "s" },
      { key: "cooldown_s", type: "number", unit: "s" },
    ],
  },
  { id: "who", rows: [{ key: "notify_on_shift", type: "toggle" }, { key: "notify_managers", type: "toggle" }] },
  { id: "privacy", rows: [{ key: "privacy_blur", type: "toggle" }, { key: "alert_photo", type: "toggle" }] },
  {
    id: "recording",
    rows: [
      { key: "record_counter", type: "toggle" },
      { key: "record_hours", type: "number", unit: "h" },
      { key: "analysis_fps", type: "fps" },
      { key: "live_fps", type: "fps" },
      { key: "stats_keep_days", type: "number", unit: "days" },
      { key: "photos_keep_days", type: "number", unit: "days" },
      { key: "clips_keep_days", type: "number", unit: "days" },
    ],
  },
];

function shown(row: Row, value: number | boolean): string {
  if (typeof value === "boolean") return value ? t("vision.settings.on") : t("vision.settings.off");
  if (row.type === "number" && row.unit === "s") return formatSeconds(value, fmt.lang.value);
  if (row.type === "fps") return `${fmt.number(value)} ${t("vision.unit.fps")}`;
  if (row.type === "number") return `${fmt.number(value)} ${t(`vision.unit.${row.unit}`)}`;
  return String(value);
}

function isDefault(row: Row): boolean {
  return !draft.value || draft.value[row.key] === DEFAULT_RULES[row.key];
}

function reset(row: Row): void {
  if (draft.value) (draft.value as unknown as Record<string, unknown>)[row.key] = DEFAULT_RULES[row.key];
}

function setNumber(key: NumericSetting, value: number | null): void {
  if (!draft.value || value === null) return;
  draft.value[key] = clampSetting(key, value);
}

const fpsOptions = (key: "analysis_fps" | "live_fps") => {
  const [min, max] = LIMITS[key];
  return Array.from({ length: max - min + 1 }, (_, i) => ({ value: min + i, label: String(min + i) }));
};

async function save(): Promise<void> {
  if (!dirty.value) return;
  saving.value = true;
  failure.value = null;
  fieldErrors.value = {};
  try {
    await saveSettings(companyId.value, changes.value);
    toast.success(t("vision.settings.saved"));
    refresh();
  } catch (error) {
    const fields = (error as { fieldErrors?: Record<string, string[]> }).fieldErrors ?? {};
    for (const [key, messages] of Object.entries(fields)) if (messages[0]) fieldErrors.value[key] = messages[0];
    failure.value = unshownFieldError(error, Object.keys(DEFAULT_RULES));
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <div class="flex flex-col gap-6 pb-16">
    <PageHeader :title="t('vision.settings.title')" :description="t('vision.settings.description')" />
    <InlineAlert v-if="!canManage" tone="neutral" size="sm" :description="t('vision.settings.readonly')" />

    <div v-if="query.isPending.value" class="flex flex-col gap-4">
      <SkeletonBlock v-for="n in 4" :key="n" height="150px" radius="12px" />
    </div>
    <ErrorState v-else-if="query.isError.value" :error="query.error.value" :retry="() => query.refetch()" />

    <template v-else-if="draft">
      <PageSection v-for="group in GROUPS" :key="group.id" variant="card" flush :heading-level="2" :title="t(`vision.settings.${group.id}.title`)" :description="t(`vision.settings.${group.id}.body`)">
        <div class="flex flex-col divide-y divide-line">
          <template v-for="row in group.rows" :key="row.key">
            <!-- A switch: the design system's row, its default under it. -->
            <div v-if="row.type === 'toggle'" class="px-4 py-3.5 md:px-5" :data-setting="row.key">
              <ToggleSwitch v-model="(draft as unknown as Record<string, boolean>)[row.key]!" layout="row" :disabled="!canManage" :label="t(`vision.settings.${row.key}`)" :description="t(`vision.settings.${row.key}.hint`)" />
              <p class="mt-1 flex flex-wrap items-center gap-x-2 text-xs text-subtle">
                <span>{{ t("vision.settings.default", { value: shown(row, DEFAULT_RULES[row.key]) }) }}</span>
                <button v-if="!isDefault(row) && canManage" type="button" class="inline-flex items-center gap-1 font-semibold text-accent-fg hover:underline" @click="reset(row)"><RotateCcw :size="11" />{{ t("vision.settings.reset") }}</button>
              </p>
            </div>
            <div v-else class="flex flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3.5 md:px-5" :data-setting="row.key">
              <div class="min-w-0 flex-1 basis-64">
                <p :id="`koz-set-${row.key}`" class="text-base font-medium text-fg">{{ t(`vision.settings.${row.key}`) }}</p>
                <p class="mt-0.5 text-sm text-muted">{{ t(`vision.settings.${row.key}.hint`) }}</p>
                <p class="mt-1 flex flex-wrap items-center gap-x-2 text-xs text-subtle">
                  <span>{{ t("vision.settings.default", { value: shown(row, DEFAULT_RULES[row.key]) }) }}</span>
                  <button v-if="!isDefault(row) && canManage" type="button" class="inline-flex items-center gap-1 font-semibold text-accent-fg hover:underline" @click="reset(row)"><RotateCcw :size="11" />{{ t("vision.settings.reset") }}</button>
                </p>
                <p v-if="fieldErrors[row.key]" class="mt-1 text-xs font-medium text-danger">{{ fieldErrors[row.key] }}</p>
              </div>
              <SegmentedControl
                v-if="row.type === 'fps'"
                :model-value="draft[row.key]"
                size="sm"
                :options="fpsOptions(row.key)"
                :disabled="!canManage"
                :aria-label="t(`vision.settings.${row.key}`)"
                @update:model-value="(value: number) => (draft![row.key] = value)"
              />
              <div v-else class="flex items-center gap-3">
                <span v-if="row.unit === 's'" class="hidden text-sm tabular-nums text-muted sm:inline">{{ formatSeconds(draft[row.key], fmt.lang.value) }}</span>
                <NumberInput
                  :model-value="draft[row.key]"
                  class="w-36"
                  :min="LIMITS[row.key][0]"
                  :max="LIMITS[row.key][1]"
                  :suffix="t(`vision.unit.${row.unit}`)"
                  :disabled="!canManage"
                  :invalid="!!fieldErrors[row.key]"
                  :aria-labelledby="`koz-set-${row.key}`"
                  @update:model-value="(value: number | null) => setNumber(row.key, value)"
                />
              </div>
            </div>
          </template>
        </div>
      </PageSection>

      <InlineAlert v-if="failure && dirty" tone="danger" :description="failure" />
      <StickyActionBar :show="dirty && canManage" :message="t('common.unsaved')" tone="warning">
        <UiButton variant="ghost" @click="draft = { ...query.data.value! }">{{ t("common.discard") }}</UiButton>
        <UiButton variant="primary" :loading="saving" @click="save">{{ t("common.save") }}</UiButton>
      </StickyActionBar>
    </template>
  </div>
</template>
