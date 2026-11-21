<script setup lang="ts">
/**
 * Rename a topic, or a student's name and note, while no line mentions them (the server refuses
 * once one does, or once the list is sealed).
 */
import { computed, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { isApiError, unshownFieldError } from "@/api/http";
import FormField from "@/components/FormField.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import TextInput from "@/components/TextInput.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";
import { useCompanyId } from "@/stores/company";

import { learningApi, useApplyList } from "../api";
import type { StudyStudent, StudyTopic } from "../types";

export type RenameTarget = { kind: "topic"; topic: StudyTopic } | { kind: "student"; student: StudyStudent };

const open = defineModel<boolean>("open", { default: false });
const props = defineProps<{ listId: number; target: RenameTarget | null }>();

const { t } = useI18n();
const cid = useCompanyId();
const apply = useApplyList();

const form = reactive({ name: "", note: "" });
const errors = ref<{ name?: string; note?: string }>({});
const formError = ref<string | null>(null);
const busy = ref(false);

watch(
  [open, () => props.target],
  () => {
    if (!open.value || !props.target) return;
    form.name = props.target.kind === "topic" ? props.target.topic.title : props.target.student.name;
    form.note = props.target.kind === "student" ? props.target.student.note : "";
    errors.value = {};
    formError.value = null;
  },
  { immediate: true },
);

const title = computed(() =>
  props.target?.kind === "topic" ? t("learning.lists.topic.renameTitle", { n: props.target.topic.number }) : t("learning.lists.student.editTitle"),
);

async function save(): Promise<void> {
  const target = props.target;
  if (!target || busy.value) return;
  const name = form.name.trim();
  if (!name) {
    errors.value = { name: t("common.form.required") };
    return;
  }
  busy.value = true;
  errors.value = {};
  formError.value = null;
  try {
    if (target.kind === "topic") apply(await learningApi.renameTopic(cid.value, props.listId, target.topic.id, name));
    else apply(await learningApi.updateStudent(cid.value, props.listId, target.student.id, { name, note: form.note.trim() }));
    toast.success(t("learning.saved"));
    open.value = false;
  } catch (error) {
    const fields = isApiError(error) ? error.fieldErrors : {};
    const nameField = target.kind === "topic" ? "title" : "name";
    errors.value = { name: fields[nameField]?.[0], note: fields.note?.[0] };
    formError.value = unshownFieldError(error, [nameField, "note"]);
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <UiDialog v-model:open="open" :title="title" size="sm">
    <form class="flex flex-col gap-4" @submit.prevent="save">
      <InlineAlert v-if="formError" tone="danger" :description="formError" />
      <FormField :label="target?.kind === 'topic' ? t('learning.lists.topic.title') : t('learning.lists.students.name')" :error="errors.name" required>
        <TextInput v-model="form.name" :maxlength="target?.kind === 'topic' ? 300 : 200" autofocus />
      </FormField>
      <FormField v-if="target?.kind === 'student'" :label="t('learning.lists.students.note')" :error="errors.note" optional>
        <TextInput v-model="form.note" :maxlength="200" :placeholder="t('learning.lists.students.notePlaceholder')" />
      </FormField>
      <button type="submit" class="hidden" tabindex="-1" aria-hidden="true" />
    </form>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="primary" :loading="busy" :disabled="!form.name.trim()" @click="save">{{ t("common.save") }}</UiButton>
    </template>
  </UiDialog>
</template>
