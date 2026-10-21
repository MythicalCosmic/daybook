<script setup lang="ts">
/**
 * Settings → Knowledge base (also opened from the knowledge base home): Telegram news on publish and
 * the automatic reminder for pages people must confirm. Each change saves at once.
 */
import { useQueryClient } from "@tanstack/vue-query";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import ErrorState from "@/components/ErrorState.vue";
import FormField from "@/components/FormField.vue";
import type { SelectOption } from "@/components/options";
import SelectBox from "@/components/SelectBox.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import { toast } from "@/components/useToast";
import { useCan } from "@/lib/usePermission";
import { useCompanyStore } from "@/stores/company";

import { kbKeys, knowledgeApi, useKnowledgeSettings } from "../api";
import type { KnowledgeSettings } from "../types";

const { t } = useI18n();
const company = useCompanyStore();
const client = useQueryClient();
const canManage = useCan("knowledge.manage");
const settings = useKnowledgeSettings();
const saving = ref<keyof KnowledgeSettings | null>(null);

const hourOptions = computed<SelectOption<number>[]>(() => [
  { value: 0, label: t("knowledge.settings.never") },
  ...[12, 24, 48, 72, 168].map((hours) => ({ value: hours, label: t("knowledge.settings.afterHours", { n: hours }, hours) })),
]);

async function save<K extends keyof KnowledgeSettings>(field: K, value: KnowledgeSettings[K]): Promise<void> {
  const key = kbKeys.settings(company.currentId ?? 0);
  const before = client.getQueryData<KnowledgeSettings>(key);
  if (before) client.setQueryData(key, { ...before, [field]: value });
  saving.value = field;
  try {
    const saved = await knowledgeApi.saveSettings(company.currentId ?? 0, { [field]: value });
    client.setQueryData(key, saved);
    toast.success(t("knowledge.settings.saved"));
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
      <SkeletonBlock height="64px" radius="12px" />
      <SkeletonBlock height="96px" radius="12px" />
    </div>
    <!-- One card of rows, like every settings panel; each change saves at once. -->
    <div v-else class="ui-card flex flex-col divide-y divide-line">
      <ToggleSwitch
        :model-value="settings.data.value.notify_on_publish"
        layout="row"
        class="px-4 py-3.5 md:px-5"
        :label="t('knowledge.settings.notify')"
        :description="t('knowledge.settings.notifyHint')"
        :loading="saving === 'notify_on_publish'"
        :disabled="!canManage"
        @update:model-value="(value: boolean) => save('notify_on_publish', value)"
      />
      <FormField class="px-4 py-3.5 md:px-5" :label="t('knowledge.settings.remind')" :hint="t('knowledge.settings.remindHint')">
        <SelectBox
          :model-value="settings.data.value.remind_unread_after_hours"
          :options="hourOptions"
          :disabled="!canManage"
          class="sm:max-w-[320px]"
          @update:model-value="(value) => value !== null && save('remind_unread_after_hours', Number(value))"
        />
      </FormField>
    </div>
  </div>
</template>
