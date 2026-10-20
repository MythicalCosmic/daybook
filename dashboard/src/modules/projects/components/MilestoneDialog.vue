<script setup lang="ts">
/** Add or edit a milestone: name, due date and a short description. */
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import DatePicker from "@/components/DatePicker.vue";
import FormField from "@/components/FormField.vue";
import TextArea from "@/components/TextArea.vue";
import TextInput from "@/components/TextInput.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";

import { createMilestone, updateMilestone, useCompanyId, useRefreshProjects } from "../api";
import type { Milestone } from "../types";

const open = defineModel<boolean>("open", { default: false });
const props = withDefaults(defineProps<{ projectId: number; milestone?: Milestone | null }>(), { milestone: null });

const { t } = useI18n();
const companyId = useCompanyId();
const refresh = useRefreshProjects();
const name = ref("");
const dueOn = ref<string | null>(null);
const description = ref("");
const error = ref<string | null>(null);
const saving = ref(false);
const editing = computed(() => !!props.milestone);

watch(open, (value) => {
  if (!value) return;
  name.value = props.milestone?.name ?? "";
  dueOn.value = props.milestone?.due_on ?? null;
  description.value = props.milestone?.description ?? "";
  error.value = null;
});

async function save(): Promise<void> {
  if (!name.value.trim()) {
    error.value = t("projects.milestones.nameRequired");
    return;
  }
  saving.value = true;
  try {
    const body = { name: name.value.trim(), due_on: dueOn.value, description: description.value.trim() };
    if (props.milestone) await updateMilestone(companyId.value, props.projectId, props.milestone.id, body);
    else await createMilestone(companyId.value, props.projectId, body);
    toast.success(editing.value ? t("projects.milestones.saved") : t("projects.milestones.added"));
    open.value = false;
    void refresh();
  } catch {
    // The HTTP layer showed why.
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <UiDialog v-model:open="open" :title="editing ? t('projects.milestones.edit') : t('projects.milestones.add')" size="sm">
    <form id="milestone-form" class="flex flex-col gap-4" @submit.prevent="save">
      <FormField :label="t('projects.milestones.name')" :error="error" required>
        <TextInput v-model="name" :maxlength="120" autofocus :placeholder="t('projects.milestones.namePlaceholder')" />
      </FormField>
      <FormField :label="t('projects.milestones.due')" optional>
        <DatePicker v-model="dueOn" clearable />
      </FormField>
      <FormField :label="t('projects.milestones.description')" optional>
        <TextArea v-model="description" :rows="3" />
      </FormField>
    </form>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="primary" type="submit" form="milestone-form" :loading="saving">{{ editing ? t("common.save") : t("projects.milestones.add") }}</UiButton>
    </template>
  </UiDialog>
</template>
