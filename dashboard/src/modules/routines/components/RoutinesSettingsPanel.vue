<script setup lang="ts">
/**
 * Settings → Routines (PLAN-OWNER §14.10, §14.21): what "Set up storage readings" starts from: the
 * fridge and room temperature ranges, the humidity maximum and the reading times. Each routine the
 * preset makes keeps its own copy, editable on the routine, so changing these never touches
 * routines already made. Defaults follow the storage rules as read in 2026 (confirm with your
 * inspector). Each change saves at once.
 */
import { Plus, X } from "@lucide/vue";
import { useQueryClient } from "@tanstack/vue-query";
import { ref } from "vue";
import { useI18n } from "vue-i18n";

import ErrorState from "@/components/ErrorState.vue";
import FormField from "@/components/FormField.vue";
import NumberInput from "@/components/NumberInput.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import TimePicker from "@/components/TimePicker.vue";
import UiButton from "@/components/UiButton.vue";
import { toast } from "@/components/useToast";
import { useCan } from "@/lib/usePermission";
import { useCompanyStore } from "@/stores/company";

import { routineKeys, routinesApi, useRoutinesSettings } from "../api";
import type { RoutinesSettings } from "../types";

const MAX_TIMES = 4;
const { t } = useI18n();
const company = useCompanyStore();
const client = useQueryClient();
const canManage = useCan("company.settings");
const settings = useRoutinesSettings();
const saving = ref<keyof RoutinesSettings | null>(null);
const adding = ref<string | null>(null);

type RangeField = Exclude<keyof RoutinesSettings, "storage_times">;
const rows: Array<{ id: string; label: string; hint: string; low?: RangeField; high: RangeField; unit: string }> = [
  { id: "fridge", label: "routines.settings.fridge", hint: "routines.settings.fridgeHint", low: "storage_fridge_min", high: "storage_fridge_max", unit: "°C" },
  { id: "room", label: "routines.settings.room", hint: "routines.settings.roomHint", low: "storage_room_min", high: "storage_room_max", unit: "°C" },
  { id: "humidity", label: "routines.settings.humidity", hint: "routines.settings.humidityHint", high: "storage_humidity_max", unit: "%" },
];

async function save<K extends keyof RoutinesSettings>(field: K, value: RoutinesSettings[K]): Promise<void> {
  const key = routineKeys.settings(company.currentId ?? 0);
  const before = client.getQueryData<RoutinesSettings>(key);
  if (before && JSON.stringify(before[field]) === JSON.stringify(value)) return;
  if (before) client.setQueryData(key, { ...before, [field]: value });
  saving.value = field;
  try {
    const saved = await routinesApi.saveSettings(company.currentId ?? 0, { [field]: value });
    client.setQueryData(key, saved);
    toast.success(t("routines.settings.saved"));
  } catch {
    if (before) client.setQueryData(key, before);
  } finally {
    saving.value = null;
  }
}

function number(field: RangeField, value: number | null): void {
  if (value === null) return;
  void save(field, value.toFixed(1));
}
function addTime(): void {
  const current = settings.data.value?.storage_times ?? [];
  const value = adding.value;
  if (!value || current.includes(value) || current.length >= MAX_TIMES) return;
  adding.value = null;
  void save("storage_times", [...current, value].sort());
}
function removeTime(value: string): void {
  const current = settings.data.value?.storage_times ?? [];
  if (current.length <= 1) return;
  void save(
    "storage_times",
    current.filter((time) => time !== value),
  );
}
</script>

<template>
  <div class="flex flex-col gap-5" data-testid="routines-settings">
    <ErrorState v-if="settings.isError.value" compact :error="settings.error.value" :retry="() => settings.refetch()" />
    <div v-else-if="!settings.data.value" class="flex flex-col gap-3" aria-hidden="true">
      <SkeletonBlock height="180px" radius="12px" />
    </div>
    <template v-else>
      <p class="text-sm text-muted">{{ t("routines.settings.intro") }}</p>
      <div class="ui-card flex flex-col divide-y divide-line">
        <FormField v-for="row in rows" :key="row.id" class="px-4 py-3.5 md:px-5" :label="t(row.label)" :hint="t(row.hint)">
          <div class="flex flex-wrap items-center gap-2">
            <template v-if="row.low">
              <NumberInput
                :model-value="Number(settings.data.value[row.low])"
                :min="-50"
                :max="100"
                :decimals="1"
                :suffix="row.unit"
                :disabled="!canManage || saving === row.low"
                class="w-[130px]"
                :aria-label="t('routines.settings.lowest')"
                @update:model-value="(value) => number(row.low!, value)"
              />
              <span class="text-muted">–</span>
            </template>
            <span v-else class="text-muted">≤</span>
            <NumberInput
              :model-value="Number(settings.data.value[row.high])"
              :min="row.unit === '%' ? 0 : -50"
              :max="100"
              :decimals="1"
              :suffix="row.unit"
              :disabled="!canManage || saving === row.high"
              class="w-[130px]"
              :aria-label="t('routines.settings.highest')"
              @update:model-value="(value) => number(row.high, value)"
            />
          </div>
        </FormField>
        <FormField class="px-4 py-3.5 md:px-5" :label="t('routines.settings.times')" :hint="t('routines.settings.timesHint')">
          <div class="flex flex-wrap items-center gap-2">
            <span v-for="time in settings.data.value.storage_times" :key="time" class="inline-flex items-center gap-1 rounded-full bg-surface-2 py-0.5 pl-2.5 pr-1 text-sm font-medium tabular-nums">
              {{ time }}
              <button
                v-if="canManage && settings.data.value.storage_times.length > 1"
                type="button"
                class="grid size-5 place-items-center rounded-full text-muted hover:bg-surface hover:text-fg"
                :aria-label="t('routines.preset.removeTime', { time })"
                @click="removeTime(time)"
              >
                <X :size="12" aria-hidden="true" />
              </button>
            </span>
            <template v-if="canManage && settings.data.value.storage_times.length < MAX_TIMES">
              <TimePicker v-model="adding" :step="15" size="sm" class="w-[110px]" />
              <UiButton size="sm" variant="ghost" :icon="Plus" :disabled="!adding" :loading="saving === 'storage_times'" @click="addTime">{{ t("routines.preset.addTime") }}</UiButton>
            </template>
          </div>
        </FormField>
      </div>
      <p class="text-xs text-muted">{{ t("routines.preset.confirmLaw") }}</p>
    </template>
  </div>
</template>
