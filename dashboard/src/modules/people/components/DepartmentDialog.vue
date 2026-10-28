<script setup lang="ts">
/**
 * One dialog for the structure's small edits, each showing only what it changes: a new department
 * (name, where it goes, its head), a new name, a new place (never under itself or one of its own
 * sub-departments), or its head (an active member, or none). Sends only what changed.
 */
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { z } from "zod";

import FormField from "@/components/FormField.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import PersonPicker from "@/components/PersonPicker.vue";
import SelectBox from "@/components/SelectBox.vue";
import TextInput from "@/components/TextInput.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";
import { useForm } from "@/lib/useForm";

import { useDepartmentMutations } from "../api";
import { allowedParents, departmentOptions, TOP_LEVEL } from "../departments";
import type { Department, DepartmentInput } from "../types";

export type DepartmentDialogMode = "create" | "rename" | "move" | "head";

const open = defineModel<boolean>("open", { default: false });
const props = withDefaults(
  defineProps<{
    mode: DepartmentDialogMode;
    /** The department being changed (null for a new one). */
    department?: Department | null;
    /** A new department's place: under this one (a sub-department), or at the top level. */
    parentId?: number | null;
    departments: Department[];
    /** The viewer may choose heads (else a new department starts without one). */
    canHead?: boolean;
  }>(),
  { department: null, parentId: null, canHead: true },
);
const emit = defineEmits<{ saved: [department: Department] }>();

const { t } = useI18n();
const { create, update } = useDepartmentMutations();

const schema = z.object({
  name: z.string().trim().min(1, "common.form.required").max(100, "common.form.tooLong"),
  parent_id: z.number(),
  head_id: z.number().nullable(),
});

const initial = {
  name: props.department?.name ?? "",
  parent_id: (props.department ? props.department.parent_id : props.parentId) ?? TOP_LEVEL,
  head_id: props.department?.head?.id ?? null,
};

const shows = computed(() => ({
  name: props.mode === "create" || props.mode === "rename",
  parent: props.mode === "create" || props.mode === "move",
  head: (props.mode === "create" && props.canHead) || props.mode === "head",
}));

const title = computed(() => {
  const name = props.department?.name ?? "";
  if (props.mode === "rename") return t("people.dept.renameTitle");
  if (props.mode === "move") return t("people.dept.moveTitle", { name });
  if (props.mode === "head") return t("people.dept.headTitle", { name });
  return t("people.dept.newTitle");
});

const parentOptions = computed(() => [
  { value: TOP_LEVEL, label: t("people.dept.topLevel"), description: t("people.dept.topLevelHint") },
  ...departmentOptions(allowedParents(props.departments, props.department?.id ?? null), (d) => d.id),
]);

const form = useForm(schema, initial, {
  onSubmit: async (values) => {
    const parent = values.parent_id === TOP_LEVEL ? null : values.parent_id;
    if (props.mode === "create") {
      const body: DepartmentInput = { name: values.name, parent_id: parent };
      if (values.head_id !== null) body.head_id = values.head_id;
      const created = await create.mutateAsync(body);
      toast.success(t("people.dept.created", { name: created.name }));
      emit("saved", created);
      open.value = false;
      return;
    }
    const department = props.department!;
    const body: Partial<DepartmentInput> = {};
    if (shows.value.name && values.name !== initial.name) body.name = values.name;
    if (shows.value.parent && values.parent_id !== initial.parent_id) body.parent_id = parent;
    if (shows.value.head && values.head_id !== initial.head_id) body.head_id = values.head_id;
    if (Object.keys(body).length) {
      const saved = await update.mutateAsync({ id: department.id, body });
      if ("head_id" in body) {
        toast.success(saved.head ? t("people.dept.headSet", { person: saved.head.name, name: saved.name }) : t("people.dept.headCleared", { name: saved.name }));
      } else if ("parent_id" in body) {
        toast.success(t("people.dept.moved", { name: saved.name }));
      } else {
        toast.success(t("people.dept.saved", { name: saved.name }));
      }
      emit("saved", saved);
    }
    open.value = false;
  },
});
</script>

<template>
  <UiDialog v-model:open="open" :title="title" size="sm">
    <form id="department-form" class="flex flex-col gap-4" data-department-form @submit="form.submit">
      <InlineAlert v-if="form.formError.value" tone="danger" :description="form.formError.value" />
      <FormField v-if="shows.name" :label="t('people.dept.name')" :error="form.errors.name" required>
        <TextInput v-model="form.values.name" autofocus autocomplete="off" :maxlength="100" :placeholder="t('people.dept.namePlaceholder')" @blur="form.touch('name')" />
      </FormField>
      <FormField v-if="shows.parent" :label="t('people.dept.parent')" :hint="mode === 'move' ? t('people.dept.moveHint') : undefined" :error="form.errors.parent_id">
        <SelectBox v-model="form.values.parent_id" :options="parentOptions" data-parent-picker />
      </FormField>
      <FormField v-if="shows.head" :label="t('people.dept.head')" :hint="t('people.dept.headHint')" :error="form.errors.head_id">
        <!-- Active members only: the server refuses a suspended head. -->
        <PersonPicker v-model="form.values.head_id" :filters="{ status: 'active' }" :placeholder="t('people.dept.headPlaceholder')" data-head-picker />
      </FormField>
    </form>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="primary" type="submit" form="department-form" :loading="form.submitting.value" :disabled="mode !== 'create' && !form.dirty.value">
        {{ mode === "create" ? t("common.create") : t("common.save") }}
      </UiButton>
    </template>
  </UiDialog>
</template>
