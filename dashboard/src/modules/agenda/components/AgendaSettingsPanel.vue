<script setup lang="ts">
/** Settings → Calendar (also opened from the calendar): the default reminder and Telegram invitations. */
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

import { agendaApi, agendaKeys, useAgendaSettings } from "../api";
import { REMIND_OPTIONS, remindKey } from "../lib";
import type { AgendaSettings } from "../types";

const { t } = useI18n();
const company = useCompanyStore();
const client = useQueryClient();
const canManage = useCan("agenda.manage");
const settings = useAgendaSettings();
const saving = ref<keyof AgendaSettings | null>(null);

const remindOptions = computed<SelectOption<number | string>[]>(() =>
  REMIND_OPTIONS.map((minutes) => {
    const { key, n } = remindKey(minutes);
    return { value: minutes === null ? "none" : minutes, label: n !== undefined ? t(key, { n }, n) : t(key) };
  }),
);

async function save<K extends keyof AgendaSettings>(field: K, value: AgendaSettings[K]): Promise<void> {
  const key = agendaKeys.settings(company.currentId ?? 0);
  const before = client.getQueryData<AgendaSettings>(key);
  if (before) client.setQueryData(key, { ...before, [field]: value });
  saving.value = field;
  try {
    client.setQueryData(key, await agendaApi.saveSettings(company.currentId ?? 0, { [field]: value }));
    toast.success(t("agenda.settings.saved"));
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
      <SkeletonBlock height="56px" radius="8px" />
      <SkeletonBlock height="44px" radius="8px" />
    </div>
    <template v-else>
      <FormField :label="t('agenda.settings.defaultRemind')" :hint="t('agenda.settings.defaultRemindHint')">
        <SelectBox
          :model-value="settings.data.value.default_remind_before ?? 'none'"
          :options="remindOptions"
          :disabled="!canManage"
          @update:model-value="(value) => save('default_remind_before', value === 'none' || value === null ? null : Number(value))"
        />
      </FormField>
      <ToggleSwitch
        :model-value="settings.data.value.notify_invites"
        layout="row"
        :label="t('agenda.settings.notifyInvites')"
        :description="t('agenda.settings.notifyInvitesHint')"
        :loading="saving === 'notify_invites'"
        :disabled="!canManage"
        @update:model-value="(value: boolean) => save('notify_invites', value)"
      />
    </template>
  </div>
</template>
