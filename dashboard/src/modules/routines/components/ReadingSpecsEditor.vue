<script setup lang="ts">
/**
 * What a readings routine asks for (PLAN-OWNER §14.10): 1 to 3 numbers, each with a name, a unit
 * and its allowed values, and whether going out of them is critical (a fridge with vaccines).
 * Quick-add rows start from the company's Settings → Routines ranges (fridge, room, humidity).
 */
import { Droplets, Plus, Refrigerator, Thermometer, Trash2 } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import CheckBox from "@/components/CheckBox.vue";
import IconButton from "@/components/IconButton.vue";
import NumberInput from "@/components/NumberInput.vue";
import TextInput from "@/components/TextInput.vue";
import UiButton from "@/components/UiButton.vue";

import { useRoutinesSettings } from "../api";
import { MAX_SPECS, presetSpecs, type SpecDraft } from "../readings";

const model = defineModel<SpecDraft[]>({ default: () => [] });
withDefaults(defineProps<{ error?: string }>(), { error: undefined });

const { t } = useI18n();
const settings = useRoutinesSettings();
const presets = computed(() =>
  presetSpecs(settings.data.value, {
    fridge: t("routines.readings.preset.fridgeLabel"),
    room: t("routines.readings.preset.roomLabel"),
    humidity: t("routines.readings.preset.humidityLabel"),
  }),
);
const quick = computed(() => [
  { id: "fridge" as const, label: t("routines.readings.preset.fridge"), icon: Refrigerator },
  { id: "room" as const, label: t("routines.readings.preset.room"), icon: Thermometer },
  { id: "humidity" as const, label: t("routines.readings.preset.humidity"), icon: Droplets },
]);
const full = computed(() => model.value.length >= MAX_SPECS);

function add(draft?: SpecDraft): void {
  if (full.value) return;
  model.value = [...model.value, draft ? { ...draft } : { label: "", unit: "°C", min: null, max: null, critical: false }];
}
function update(index: number, patch: Partial<SpecDraft>): void {
  model.value = model.value.map((row, at) => (at === index ? { ...row, ...patch } : row));
}
function remove(index: number): void {
  model.value = model.value.filter((_, at) => at !== index);
}
</script>

<template>
  <div class="flex flex-col gap-3" data-testid="specs-editor">
    <p v-if="!model.length" class="text-sm text-muted">{{ t("routines.readings.editorEmpty") }}</p>
    <div
      v-for="(row, index) in model"
      :key="index"
      class="grid gap-2 rounded-[10px] border border-line bg-surface-2/40 p-3 sm:grid-cols-[minmax(0,1fr)_84px_96px_96px_auto]"
      :data-spec="index"
    >
      <TextInput
        :model-value="row.label"
        :maxlength="80"
        :placeholder="t('routines.readings.labelPlaceholder')"
        :aria-label="t('routines.readings.label')"
        @update:model-value="(value) => update(index, { label: value ?? '' })"
      />
      <TextInput :model-value="row.unit" :maxlength="8" :placeholder="'°C'" :aria-label="t('routines.readings.unit')" @update:model-value="(value) => update(index, { unit: value ?? '' })" />
      <NumberInput
        :model-value="row.min"
        :min="-50"
        :max="100"
        :decimals="1"
        :placeholder="t('routines.readings.min')"
        :aria-label="t('routines.readings.min')"
        @update:model-value="(value) => update(index, { min: value })"
      />
      <NumberInput
        :model-value="row.max"
        :min="-50"
        :max="100"
        :decimals="1"
        :placeholder="t('routines.readings.max')"
        :aria-label="t('routines.readings.max')"
        @update:model-value="(value) => update(index, { max: value })"
      />
      <IconButton :icon="Trash2" :label="t('routines.readings.remove')" size="sm" class="self-center justify-self-end" @click="remove(index)" />
      <CheckBox
        class="sm:col-span-5"
        size="sm"
        :model-value="row.critical"
        :label="t('routines.readings.critical')"
        :description="t('routines.readings.criticalHint')"
        @update:model-value="(value) => update(index, { critical: value })"
      />
    </div>
    <p v-if="error" class="text-sm text-danger">{{ error }}</p>
    <div v-if="!full" class="flex flex-wrap items-center gap-2">
      <UiButton v-for="item in quick" :key="item.id" size="sm" :icon="item.icon" @click="add(presets[item.id])">{{ item.label }}</UiButton>
      <UiButton size="sm" variant="ghost" :icon="Plus" @click="add()">{{ t("routines.readings.add") }}</UiButton>
    </div>
    <p v-else class="text-xs text-muted">{{ t("routines.readings.max3") }}</p>
  </div>
</template>
