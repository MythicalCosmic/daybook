<script setup lang="ts">
/**
 * Settings → Tasks (PLAN-OWNER §15.3): what happens when someone finishes a task (accept it
 * automatically, accept it only with a photo or text proof, or always ask the person who gave it)
 * and the wait after which work nobody reviewed is accepted. New tasks and routines start from the
 * rule; their own choice wins. Each change saves at once.
 */
import { Camera, CheckCheck, UserCheck } from "@lucide/vue";
import { useQueryClient } from "@tanstack/vue-query";
import { computed, ref, type Component } from "vue";
import { useI18n } from "vue-i18n";

import ErrorState from "@/components/ErrorState.vue";
import FormField from "@/components/FormField.vue";
import type { SelectOption } from "@/components/options";
import RadioCards from "@/components/RadioCards.vue";
import SelectBox from "@/components/SelectBox.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import { toast } from "@/components/useToast";
import { useCan } from "@/lib/usePermission";
import { useCompanyStore } from "@/stores/company";

import { taskKeys, tasksApi, useTasksSettings } from "../api";
import type { OnFinish, TasksSettings } from "../types";

/** The waits offered, in hours (the server takes 4 to 72). 0 here means never. */
const WAITS = [4, 8, 12, 24, 48, 72] as const;

const { t } = useI18n();
const company = useCompanyStore();
const client = useQueryClient();
const canManage = useCan("company.settings");
const settings = useTasksSettings();
const saving = ref<keyof TasksSettings | null>(null);

const rules = computed<{ value: OnFinish; label: string; description: string; icon: Component }[]>(() => [
  { value: "auto", label: t("tasks.settings.auto"), description: t("tasks.settings.autoHint"), icon: CheckCheck },
  { value: "proof", label: t("tasks.settings.proof"), description: t("tasks.settings.proofHint"), icon: Camera },
  { value: "ask", label: t("tasks.settings.ask"), description: t("tasks.settings.askHint"), icon: UserCheck },
]);
const waits = computed<SelectOption<number>[]>(() => [
  { value: 0, label: t("tasks.settings.never") },
  ...WAITS.map((hours) => ({ value: hours, label: t("tasks.settings.afterHours", { n: hours }, hours) })),
]);

async function save<K extends keyof TasksSettings>(field: K, value: TasksSettings[K]): Promise<void> {
  const key = taskKeys.settings(company.currentId ?? 0);
  const before = client.getQueryData<TasksSettings>(key);
  if (before) client.setQueryData(key, { ...before, [field]: value });
  saving.value = field;
  try {
    const saved = await tasksApi.saveSettings(company.currentId ?? 0, { [field]: value });
    client.setQueryData(key, saved);
    toast.success(t("tasks.settings.saved"));
  } catch {
    if (before) client.setQueryData(key, before);
  } finally {
    saving.value = null;
  }
}
</script>

<template>
  <div class="flex flex-col gap-5">
    <ErrorState v-if="settings.isError.value" compact :error="settings.error.value" :retry="() => settings.refetch()" />
    <div v-else-if="!settings.data.value" class="flex flex-col gap-3" aria-hidden="true">
      <SkeletonBlock height="180px" radius="12px" />
      <SkeletonBlock height="72px" radius="12px" />
    </div>
    <!-- One card of rows, like every settings panel; each change saves at once. -->
    <div v-else class="ui-card flex flex-col divide-y divide-line">
      <FormField class="px-4 py-3.5 md:px-5" :label="t('tasks.settings.onFinish')" :hint="t('tasks.settings.onFinishHint')">
        <RadioCards
          :model-value="settings.data.value.on_finish"
          :options="rules"
          :columns="1"
          :disabled="!canManage || saving === 'on_finish'"
          @update:model-value="(value) => value && value !== settings.data.value?.on_finish && save('on_finish', value)"
        />
      </FormField>
      <FormField class="px-4 py-3.5 md:px-5" :label="t('tasks.settings.timeout')" :hint="t('tasks.settings.timeoutHint')">
        <SelectBox
          :model-value="settings.data.value.auto_accept_after_hours ?? 0"
          :options="waits"
          :disabled="!canManage || saving === 'auto_accept_after_hours'"
          class="sm:max-w-[360px]"
          @update:model-value="(value) => value !== null && save('auto_accept_after_hours', Number(value) || null)"
        />
      </FormField>
    </div>
  </div>
</template>
