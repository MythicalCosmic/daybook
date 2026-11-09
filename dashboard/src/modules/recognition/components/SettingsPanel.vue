<script setup lang="ts">
/**
 * Settings › Recognition (PLAN-LEARNING §7, §8): points on or off, who sees the leaderboard and
 * for which scope, points for tasks done on time, thanks between colleagues (a day's limit, posts
 * to linked groups), the points table (each row with its default) and the ten levels. Owners
 * change it (recognition.manage); others read it.
 */
import { RotateCcw } from "@lucide/vue";
import { computed, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import FormField from "@/components/FormField.vue";
import NumberInput from "@/components/NumberInput.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import UiButton from "@/components/UiButton.vue";
import { toast } from "@/components/useToast";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { recognitionApi, useRecognitionSettings, useRefresh } from "../api";
import { MANAGE } from "../lib";

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const refresh = useRefresh();
const settings = useRecognitionSettings();
const canManage = computed(() => company.can(MANAGE));

const form = reactive({
  points_enabled: true,
  leaderboard_for_staff: true,
  leaderboard_scope: "company" as "company" | "branch",
  task_points: true,
  kudos_enabled: true,
  kudos_per_day: 3,
  post_kudos_to_groups: false,
});
const points = reactive<Record<string, number | null>>({});

watch(
  () => settings.data.value,
  (data) => {
    if (!data) return;
    Object.assign(form, {
      points_enabled: data.points_enabled,
      leaderboard_for_staff: data.leaderboard_for_staff,
      leaderboard_scope: data.leaderboard_scope,
      task_points: data.task_points,
      kudos_enabled: data.kudos_enabled,
      kudos_per_day: data.kudos_per_day,
      post_kudos_to_groups: data.post_kudos_to_groups,
    });
    for (const row of data.points) points[row.key] = row.points;
  },
  { immediate: true },
);

const defaults = computed(() => Object.fromEntries((settings.data.value?.points ?? []).map((row) => [row.key, row.default])));
/** The rows that differ from their default: what the server keeps. */
const table = computed(() => {
  const out: Record<string, number> = {};
  for (const [key, value] of Object.entries(points)) if (value !== null && value !== defaults.value[key]) out[key] = value;
  return out;
});

const saving = ref(false);
async function save(): Promise<void> {
  saving.value = true;
  try {
    await recognitionApi.updateSettings(company.currentId ?? 0, { ...form, points_table: table.value });
    toast.success(t("recognition.settings.saved"));
    refresh();
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <div v-if="settings.isPending.value" class="flex flex-col gap-3"><SkeletonBlock v-for="n in 3" :key="n" height="56px" radius="10px" /></div>
  <div v-else-if="settings.data.value" class="flex flex-col gap-6" data-testid="recognition-settings">
    <section class="flex flex-col gap-3">
      <div>
        <h3 class="text-md font-semibold text-fg">{{ t("recognition.settings.pointsTitle") }}</h3>
        <p class="mt-1 text-sm text-muted">{{ t("recognition.settings.pointsBody") }}</p>
      </div>
      <ToggleSwitch v-model="form.points_enabled" :disabled="!canManage" :label="t('recognition.settings.pointsEnabled')" :description="t('recognition.settings.pointsEnabledHint')" />
      <ToggleSwitch v-model="form.task_points" :disabled="!canManage || !form.points_enabled" :label="t('recognition.settings.taskPoints')" :description="t('recognition.settings.taskPointsHint')" />
    </section>

    <section class="flex flex-col gap-3">
      <h3 class="text-md font-semibold text-fg">{{ t("recognition.settings.boardTitle") }}</h3>
      <ToggleSwitch v-model="form.leaderboard_for_staff" :disabled="!canManage" :label="t('recognition.settings.forStaff')" :description="t('recognition.settings.forStaffHint')" />
      <FormField :label="t('recognition.settings.scope')" :hint="t('recognition.settings.scopeHint')">
        <SegmentedControl
          v-model="form.leaderboard_scope"
          :disabled="!canManage"
          :options="[
            { value: 'company', label: t('recognition.scope.company') },
            { value: 'branch', label: t('recognition.scope.branch') },
          ]"
        />
      </FormField>
    </section>

    <section class="flex flex-col gap-3">
      <h3 class="text-md font-semibold text-fg">{{ t("recognition.settings.kudosTitle") }}</h3>
      <ToggleSwitch v-model="form.kudos_enabled" :disabled="!canManage" :label="t('recognition.settings.kudosEnabled')" :description="t('recognition.settings.kudosEnabledHint')" />
      <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <FormField :label="t('recognition.settings.perDay')" :hint="t('recognition.settings.perDayHint')">
          <NumberInput v-model="form.kudos_per_day" :min="1" :max="20" :disabled="!canManage || !form.kudos_enabled" />
        </FormField>
      </div>
      <ToggleSwitch v-model="form.post_kudos_to_groups" :disabled="!canManage || !form.kudos_enabled" :label="t('recognition.settings.groups')" :description="t('recognition.settings.groupsHint')" />
    </section>

    <section class="flex flex-col gap-3">
      <div>
        <h3 class="text-md font-semibold text-fg">{{ t("recognition.settings.tableTitle") }}</h3>
        <p class="mt-1 text-sm text-muted">{{ t("recognition.settings.tableBody") }}</p>
      </div>
      <ul class="divide-y divide-line rounded-lg border border-line" data-testid="points-table">
        <li v-for="row in settings.data.value.points" :key="row.key" class="flex items-center gap-3 px-3 py-2">
          <span class="min-w-0 flex-1 text-sm text-fg">{{ row.label }}</span>
          <span v-if="points[row.key] !== row.default" class="text-xs text-muted">{{ t("recognition.settings.default", { n: row.default }) }}</span>
          <UiButton
            v-if="canManage && points[row.key] !== row.default"
            size="sm"
            variant="ghost"
            :icon="RotateCcw"
            :aria-label="t('recognition.settings.reset')"
            @click="points[row.key] = row.default"
          />
          <div class="w-28"><NumberInput v-model="points[row.key]" :min="0" :max="1000" :disabled="!canManage || !form.points_enabled" size="sm" /></div>
        </li>
      </ul>
    </section>

    <section class="flex flex-col gap-2">
      <h3 class="text-md font-semibold text-fg">{{ t("recognition.settings.levelsTitle") }}</h3>
      <ol class="grid grid-cols-2 gap-2 sm:grid-cols-5">
        <li v-for="level in settings.data.value.levels" :key="level.number" class="ui-card flex flex-col p-3">
          <span class="text-xs text-muted">{{ t("recognition.level", { number: level.number }) }}</span>
          <span class="text-sm font-semibold text-fg">{{ level.name }}</span>
          <span class="text-xs tabular-nums text-muted">{{ t("recognition.settings.from", { n: fmt.number(level.starts_at) }) }}</span>
        </li>
      </ol>
    </section>

    <div v-if="canManage"><UiButton variant="primary" :loading="saving" @click="save">{{ t("common.save") }}</UiButton></div>
  </div>
</template>
