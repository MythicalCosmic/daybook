<script setup lang="ts">
/**
 * Edit someone: name, position, the branches they work in and their home branch, and (with
 * roles.manage) their role. Only roles the viewer may give are offered; the server checks the
 * anti-escalation rules again. Sends only what changed.
 */
import { computed, watch } from "vue";
import { useI18n } from "vue-i18n";
import { z } from "zod";

import BranchPicker from "@/components/BranchPicker.vue";
import FormField from "@/components/FormField.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import { useScopedBranches } from "@/components/pickers";
import SelectBox from "@/components/SelectBox.vue";
import TextInput from "@/components/TextInput.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";
import { useForm } from "@/lib/useForm";

import { updatePerson, usePersonMutation, usePositions, useRoles } from "../api";
import type { PersonDetail, PersonUpdate } from "../types";

const open = defineModel<boolean>("open", { default: false });
const props = defineProps<{ person: PersonDetail }>();

const { t } = useI18n();
const positions = usePositions();
const roles = useRoles(computed(() => props.person.can.change_role));
const scoped = useScopedBranches();

const schema = z.object({
  first_name: z.string().trim().min(1, "common.form.required").max(100, "common.form.tooLong"),
  last_name: z.string().trim().max(100, "common.form.tooLong"),
  position_id: z.number().nullable(),
  branch_ids: z.array(z.number()),
  home_branch_id: z.number().nullable(),
  role_id: z.number().nullable(),
});

const initial = {
  first_name: props.person.first_name,
  last_name: props.person.last_name,
  position_id: props.person.position?.id ?? null,
  branch_ids: props.person.branches.map((b) => b.id),
  home_branch_id: props.person.home_branch?.id ?? null,
  role_id: props.person.role?.id ?? null,
};

const save = usePersonMutation((cid, body: PersonUpdate) => updatePerson(cid, props.person.id, body));
const form = useForm(schema, initial, {
  onSubmit: async (values) => {
    const body: PersonUpdate = {};
    if (values.first_name !== initial.first_name) body.first_name = values.first_name;
    if (values.last_name !== initial.last_name) body.last_name = values.last_name;
    if (values.position_id !== initial.position_id) body.position_id = values.position_id;
    if (JSON.stringify([...values.branch_ids].sort()) !== JSON.stringify([...initial.branch_ids].sort())) body.branch_ids = values.branch_ids;
    if (values.home_branch_id !== initial.home_branch_id) body.home_branch_id = values.home_branch_id;
    if (values.role_id !== null && values.role_id !== initial.role_id) body.role_id = values.role_id;
    if (Object.keys(body).length) {
      await save.mutateAsync(body);
      toast.success(t("people.edit.saved", { name: `${values.first_name} ${values.last_name}`.trim() }));
    }
    open.value = false;
  },
});

const positionOptions = computed(() =>
  (positions.data.value ?? []).filter((p) => p.is_active || p.id === initial.position_id).map((p) => ({ value: p.id, label: p.name })),
);
// Branches the person works in that the viewer can't see stay as they are (the server keeps them).
const hiddenBranches = computed(() => props.person.branches.filter((b) => !scoped.value.some((s) => s.id === b.id)));
const homeOptions = computed(() =>
  [...scoped.value, ...hiddenBranches.value].filter((b) => form.values.branch_ids.includes(b.id) || hiddenBranches.value.some((h) => h.id === b.id)).map((b) => ({ value: b.id, label: b.name, description: b.code })),
);
const roleOptions = computed(() =>
  (roles.data.value ?? [])
    .filter((role) => role.can_assign || role.id === initial.role_id)
    .map((role) => ({ value: role.id, label: role.name, description: role.is_owner ? t("people.edit.ownerRole") : t("people.roles.permissionsCount", { n: role.permissions.length }, role.permissions.length), disabled: !role.can_assign })),
);

// A home branch must be one of the branches: keep it valid while branches change.
watch(
  () => [...form.values.branch_ids],
  (ids) => {
    if (!ids.length) return;
    if (form.values.home_branch_id === null || !ids.includes(form.values.home_branch_id)) form.values.home_branch_id = ids[0]!;
  },
);
</script>

<template>
  <UiDialog v-model:open="open" :title="t('people.edit.title', { name: person.name })" :description="t('people.edit.description')" size="md">
    <form id="person-edit" class="flex flex-col gap-4" @submit="form.submit">
      <InlineAlert v-if="form.formError.value" tone="danger" :description="form.formError.value" />
      <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <FormField :label="t('people.field.first_name')" :error="form.errors.first_name" required>
          <TextInput v-model="form.values.first_name" autocomplete="off" @blur="form.touch('first_name')" />
        </FormField>
        <FormField :label="t('people.field.last_name')" :error="form.errors.last_name">
          <TextInput v-model="form.values.last_name" autocomplete="off" />
        </FormField>
      </div>
      <FormField :label="t('people.col.position')" :error="form.errors.position_id">
        <SelectBox v-model="form.values.position_id" :options="positionOptions" :placeholder="t('people.noPosition')" clearable />
      </FormField>
      <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <FormField :label="t('people.field.branches')" :hint="t('people.edit.branchesHint')" :error="form.errors.branch_ids">
          <BranchPicker v-model="form.values.branch_ids" multiple />
        </FormField>
        <FormField :label="t('people.field.homeBranch')" :hint="t('people.edit.homeHint')" :error="form.errors.home_branch_id">
          <SelectBox v-model="form.values.home_branch_id" :options="homeOptions" :disabled="!homeOptions.length" :placeholder="t('people.noBranch')" />
        </FormField>
      </div>
      <FormField v-if="person.can.change_role" :label="t('people.col.role')" :hint="t('people.edit.roleHint')" :error="form.errors.role_id">
        <SelectBox v-model="form.values.role_id" :options="roleOptions" />
      </FormField>
    </form>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="primary" type="submit" form="person-edit" :loading="form.submitting.value" :disabled="!form.dirty.value">{{ t("common.save") }}</UiButton>
    </template>
  </UiDialog>
</template>
