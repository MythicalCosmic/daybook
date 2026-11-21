<script setup lang="ts">
/**
 * An unchangeable list's title, teacher, branch and what it is about: a new list (it opens once
 * written) or the details of an open one. Only the title is required.
 */
import { reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { isApiError, unshownFieldError } from "@/api/http";
import BranchPicker from "@/components/BranchPicker.vue";
import FormField from "@/components/FormField.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import TextArea from "@/components/TextArea.vue";
import TextInput from "@/components/TextInput.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";
import { useCompanyId } from "@/stores/company";

import { learningApi, useApplyList } from "../api";
import type { StudyListDetail, StudyListInput } from "../types";

const open = defineModel<boolean>("open", { default: false });
const props = withDefaults(defineProps<{ list?: StudyListDetail | null }>(), { list: null });
const emit = defineEmits<{ saved: [list: StudyListDetail] }>();

const { t } = useI18n();
const cid = useCompanyId();
const apply = useApplyList();

const FIELDS = ["title", "teacher", "branch_id", "description"] as const;
const form = reactive({ title: "", teacher: "", branch_id: null as number | null, description: "" });
const errors = ref<Partial<Record<(typeof FIELDS)[number], string>>>({});
const formError = ref<string | null>(null);
const busy = ref(false);

watch(
  open,
  (value) => {
    if (!value) return;
    Object.assign(form, {
      title: props.list?.title ?? "",
      teacher: props.list?.teacher ?? "",
      branch_id: props.list?.branch?.id ?? null,
      description: props.list?.description ?? "",
    });
    errors.value = {};
    formError.value = null;
  },
  { immediate: true },
);

async function save(): Promise<void> {
  const title = form.title.trim();
  if (!title) {
    errors.value = { title: t("common.form.required") };
    return;
  }
  if (busy.value) return;
  busy.value = true;
  errors.value = {};
  formError.value = null;
  const input: StudyListInput = { title, teacher: form.teacher.trim(), branch_id: form.branch_id, description: form.description.trim() };
  try {
    const list = props.list ? await learningApi.updateList(cid.value, props.list.id, input) : await learningApi.createList(cid.value, input);
    apply(list);
    toast.success(props.list ? t("learning.saved") : t("learning.lists.created"));
    open.value = false;
    emit("saved", list);
  } catch (error) {
    const fields = isApiError(error) ? error.fieldErrors : {};
    errors.value = Object.fromEntries(FIELDS.map((field) => [field, fields[field]?.[0]]).filter((entry) => entry[1]));
    // A refusal about anything else is said at the top (a `detail` was toasted already).
    formError.value = unshownFieldError(error, [...FIELDS]);
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <UiDialog v-model:open="open" :title="list ? t('learning.lists.editTitle') : t('learning.lists.new')" :description="list ? undefined : t('learning.lists.newHint')" size="md">
    <form class="flex flex-col gap-4" data-testid="list-form" @submit.prevent="save">
      <InlineAlert v-if="formError" tone="danger" :description="formError" />
      <FormField :label="t('learning.lists.field.title')" :error="errors.title" required>
        <TextInput v-model="form.title" :maxlength="200" autofocus :placeholder="t('learning.lists.field.titlePlaceholder')" />
      </FormField>
      <div class="grid gap-4 sm:grid-cols-2">
        <FormField :label="t('learning.lists.field.teacher')" :error="errors.teacher" optional>
          <TextInput v-model="form.teacher" :maxlength="200" :placeholder="t('learning.lists.field.teacherPlaceholder')" />
        </FormField>
        <FormField :label="t('learning.lists.field.branch')" :error="errors.branch_id" optional>
          <BranchPicker v-model="form.branch_id" clearable :placeholder="t('learning.lists.field.anyBranch')" />
        </FormField>
      </div>
      <FormField :label="t('learning.lists.field.description')" :error="errors.description" optional>
        <TextArea v-model="form.description" :rows="3" :max-rows="8" :maxlength="5000" :placeholder="t('learning.lists.field.descriptionPlaceholder')" />
      </FormField>
      <!-- Enter in a one-line field sends the form. -->
      <button type="submit" class="hidden" tabindex="-1" aria-hidden="true" />
    </form>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="primary" :loading="busy" :disabled="!form.title.trim()" data-testid="list-save" @click="save">{{ list ? t("common.save") : t("common.create") }}</UiButton>
    </template>
  </UiDialog>
</template>
