<script setup lang="ts">
/**
 * Settings → Projects (company-wide): the lists every new board starts with, the weekly update
 * nudge to leads (and its day), and when a project counts as at risk.
 */
import { GripVertical, Plus, Trash2 } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import ErrorState from "@/components/ErrorState.vue";
import FormField from "@/components/FormField.vue";
import IconButton from "@/components/IconButton.vue";
import NumberInput from "@/components/NumberInput.vue";
import PageSection from "@/components/PageSection.vue";
import SelectBox from "@/components/SelectBox.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StickyActionBar from "@/components/StickyActionBar.vue";
import TextInput from "@/components/TextInput.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import UiButton from "@/components/UiButton.vue";
import { toast } from "@/components/useToast";

import { saveSettings, useCompanyId, useSettings } from "../api";
import type { ProjectSettings } from "../types";

const { t } = useI18n();
const companyId = useCompanyId();
const query = useSettings();
const draft = ref<ProjectSettings | null>(null);
const saving = ref(false);

watch(
  () => query.data.value,
  (value) => {
    if (value) draft.value = { ...value, default_lists: [...value.default_lists] };
  },
  { immediate: true },
);

const dirty = computed(() => !!draft.value && !!query.data.value && JSON.stringify(draft.value) !== JSON.stringify(query.data.value));
const weekdays = computed(() => [0, 1, 2, 3, 4, 5, 6].map((day) => ({ value: day, label: t(`projects.settings.weekday.${day}`) })));

async function save(): Promise<void> {
  if (!draft.value) return;
  const names = draft.value.default_lists.map((n) => n.trim()).filter(Boolean);
  if (names.length < 2) {
    toast.error(t("projects.settings.listsTooFew"));
    return;
  }
  saving.value = true;
  try {
    await saveSettings(companyId.value, {
      default_lists: names,
      weekly_nudge: draft.value.weekly_nudge,
      nudge_weekday: draft.value.nudge_weekday,
      at_risk_days: draft.value.at_risk_days,
      at_risk_percent: draft.value.at_risk_percent,
    });
    toast.success(t("projects.settings.saved"));
    await query.refetch();
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <div class="flex flex-col gap-5">
    <SkeletonBlock v-if="query.isPending.value" height="320px" radius="12px" />
    <ErrorState v-else-if="query.isError.value" :error="query.error.value" :retry="() => query.refetch()" />
    <template v-else-if="draft">
      <PageSection :title="t('projects.settings.lists')" :description="t('projects.settings.listsHint')" variant="card">
        <ol class="flex flex-col gap-2">
          <li v-for="(_name, index) in draft.default_lists" :key="index" class="flex items-center gap-2">
            <GripVertical :size="15" class="text-subtle" aria-hidden="true" />
            <TextInput v-model="draft.default_lists[index]" size="sm" :maxlength="60" class="flex-1" :disabled="!draft.can_edit" />
            <span v-if="index === draft.default_lists.length - 1" class="rounded-full bg-success-soft px-2 py-0.5 text-[11px] font-semibold text-success">{{ t("projects.settings.doneList") }}</span>
            <IconButton v-if="draft.can_edit && draft.default_lists.length > 2" :icon="Trash2" :label="t('common.delete')" size="sm" @click="draft.default_lists.splice(index, 1)" />
          </li>
        </ol>
        <UiButton v-if="draft.can_edit && draft.default_lists.length < 12" size="sm" variant="ghost" :icon="Plus" class="mt-2" @click="draft.default_lists.splice(draft.default_lists.length - 1, 0, '')">{{ t("projects.settings.addList") }}</UiButton>
      </PageSection>

      <PageSection :title="t('projects.settings.nudge')" :description="t('projects.settings.nudgeHint')" variant="card">
        <div class="flex flex-col gap-4">
          <ToggleSwitch v-model="draft.weekly_nudge" :label="t('projects.settings.nudgeOn')" :disabled="!draft.can_edit" layout="row" />
          <FormField v-if="draft.weekly_nudge" :label="t('projects.settings.nudgeDay')" class="max-w-xs">
            <SelectBox v-model="draft.nudge_weekday" :options="weekdays" :disabled="!draft.can_edit" />
          </FormField>
        </div>
      </PageSection>

      <PageSection :title="t('projects.settings.risk')" :description="t('projects.settings.riskHint')" variant="card">
        <div class="grid gap-4 sm:grid-cols-2">
          <FormField :label="t('projects.settings.riskDays')">
            <NumberInput v-model="draft.at_risk_days" :min="1" :max="90" :suffix="t('projects.settings.days')" :disabled="!draft.can_edit" />
          </FormField>
          <FormField :label="t('projects.settings.riskPercent')">
            <NumberInput v-model="draft.at_risk_percent" :min="1" :max="100" suffix="%" :disabled="!draft.can_edit" />
          </FormField>
        </div>
        <p class="mt-3 text-sm text-muted">{{ t("projects.settings.riskRule", { days: draft.at_risk_days, percent: draft.at_risk_percent }) }}</p>
      </PageSection>

      <StickyActionBar :show="dirty" :message="t('common.unsaved')" tone="warning">
        <UiButton variant="ghost" @click="draft = query.data.value ? { ...query.data.value, default_lists: [...query.data.value.default_lists] } : null">{{ t("common.discard") }}</UiButton>
        <UiButton variant="primary" :loading="saving" @click="save">{{ t("common.save") }}</UiButton>
      </StickyActionBar>
    </template>
  </div>
</template>
