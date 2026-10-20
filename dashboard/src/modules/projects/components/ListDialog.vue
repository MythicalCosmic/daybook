<script setup lang="ts">
/** Add a board list, or rename one and set its WIP limit. */
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import FormField from "@/components/FormField.vue";
import NumberInput from "@/components/NumberInput.vue";
import TextInput from "@/components/TextInput.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";

import { createList, updateList, useCompanyId, useRefreshProjects } from "../api";
import type { BoardList } from "../types";

const open = defineModel<boolean>("open", { default: false });
const props = withDefaults(defineProps<{ projectId: number; list?: BoardList | null }>(), { list: null });

const { t } = useI18n();
const companyId = useCompanyId();
const refresh = useRefreshProjects();
const name = ref("");
const wip = ref<number | null>(null);
const saving = ref(false);
const error = ref<string | null>(null);
const editing = computed(() => !!props.list);

watch(open, (value) => {
  if (!value) return;
  name.value = props.list?.name ?? "";
  wip.value = props.list?.wip_limit ?? null;
  error.value = null;
});

async function save(): Promise<void> {
  if (!name.value.trim()) {
    error.value = t("projects.list.nameRequired");
    return;
  }
  saving.value = true;
  try {
    const body = { name: name.value.trim(), wip_limit: wip.value || null };
    if (props.list) await updateList(companyId.value, props.projectId, props.list.id, body);
    else await createList(companyId.value, props.projectId, body);
    open.value = false;
    void refresh();
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <UiDialog v-model:open="open" :title="editing ? t('projects.list.edit') : t('projects.list.add')" size="sm">
    <form id="list-form" class="flex flex-col gap-4" @submit.prevent="save">
      <FormField :label="t('projects.list.name')" :error="error" required>
        <TextInput v-model="name" :placeholder="t('projects.list.namePlaceholder')" :maxlength="60" autofocus />
      </FormField>
      <FormField :label="t('projects.list.wipLabel')" :hint="t('projects.list.wipHelp')" optional>
        <NumberInput v-model="wip" :min="0" :max="999" :placeholder="t('projects.list.wipNone')" />
      </FormField>
    </form>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="primary" type="submit" form="list-form" :loading="saving">{{ editing ? t("common.save") : t("projects.list.add") }}</UiButton>
    </template>
  </UiDialog>
</template>
