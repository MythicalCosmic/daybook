<script setup lang="ts">
/** Create or edit a reminder policy in a drawer, with its live timeline and texts. */
import { ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { isApiError } from "@/api/http";
import UiButton from "@/components/UiButton.vue";
import UiDrawer from "@/components/UiDrawer.vue";
import { toast } from "@/components/useToast";

import { useSavePolicy } from "../api";
import { emptyDraft, toDraft, toInput } from "../draft";
import type { Policy } from "../types";
import PolicyForm, { type PolicyDraft } from "./PolicyForm.vue";

const open = defineModel<boolean>("open", { default: false });
const props = withDefaults(defineProps<{ policy?: Policy | null }>(), { policy: null });

const { t } = useI18n();
const save = useSavePolicy();
const draft = ref<PolicyDraft>(emptyDraft());
const errors = ref<Record<string, string>>({});

watch(open, (value) => {
  if (!value) return;
  draft.value = props.policy ? toDraft(props.policy) : emptyDraft(t("reminders.form.newName"));
  errors.value = {};
}, { immediate: true });

async function submit(): Promise<void> {
  if (!draft.value.name.trim()) {
    errors.value = { name: t("reminders.form.nameRequired") };
    return;
  }
  try {
    const saved = await save.mutateAsync({ id: props.policy?.id ?? null, input: toInput(draft.value) });
    toast.success(props.policy ? t("reminders.toast.saved") : t("reminders.toast.created"), { description: saved.name });
    open.value = false;
  } catch (error) {
    if (isApiError(error)) errors.value = Object.fromEntries(Object.entries(error.fieldErrors).map(([key, messages]) => [key, messages[0] ?? ""]));
  }
}
</script>

<template>
  <UiDrawer v-model:open="open" size="xl" :title="policy ? t('reminders.editor.editTitle') : t('reminders.editor.newTitle')" :description="t('reminders.editor.description')">
    <div class="p-5">
      <PolicyForm v-model="draft" :errors="errors" />
    </div>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="primary" :loading="save.isPending.value" @click="submit">{{ policy ? t("common.save") : t("common.create") }}</UiButton>
    </template>
  </UiDrawer>
</template>
