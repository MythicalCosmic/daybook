<script setup lang="ts">
/** Add a location or change one: its name, a short code for reports, the address and a phone. */
import { computed, watch } from "vue";
import { useI18n } from "vue-i18n";
import { z } from "zod";

import FormField from "@/components/FormField.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import TextInput from "@/components/TextInput.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";
import { useForm } from "@/lib/useForm";
import { useCompanyStore } from "@/stores/company";

import { createBranch, updateBranch, useRefresh } from "../../api";
import type { Branch, BranchInput } from "../../types";

const open = defineModel<boolean>("open", { default: false });
const props = withDefaults(defineProps<{ branch?: Branch | null }>(), { branch: null });

const { t } = useI18n();
const company = useCompanyStore();
const refresh = useRefresh();

const schema = z.object({
  name: z.string().trim().min(1, "common.form.required").max(100, "common.form.tooLong"),
  code: z.string().trim().max(10, "common.form.tooLong"),
  address: z.string().trim().max(255, "common.form.tooLong"),
  phone: z.string().trim().max(32, "common.form.tooLong"),
});

function valuesOf(branch: Branch | null): Required<BranchInput> {
  return { name: branch?.name ?? "", code: branch?.code ?? "", address: branch?.address ?? "", phone: branch?.phone ?? "" };
}

const form = useForm(schema, valuesOf(null), {
  onSubmit: async (values) => {
    const cid = company.currentId ?? 0;
    const body: BranchInput = { name: values.name.trim(), address: values.address.trim(), phone: values.phone.trim(), ...(values.code.trim() ? { code: values.code.trim() } : {}) };
    const saved = props.branch ? await updateBranch(cid, props.branch.id, body) : await createBranch(cid, body);
    toast.success(props.branch ? t("davomat.branches.saved", { name: saved.name }) : t("davomat.branches.created", { name: saved.name }));
    refresh();
    open.value = false;
  },
});

watch(open, (value) => {
  if (value) form.reset(valuesOf(props.branch));
});

const title = computed(() => (props.branch ? t("davomat.branches.editTitle") : t("davomat.branches.newTitle")));
</script>

<template>
  <UiDialog v-model:open="open" :title="title" size="md">
    <form id="branch-form" class="flex flex-col gap-4" novalidate @submit.prevent="form.submit">
      <InlineAlert v-if="form.formError.value" tone="danger" :description="form.formError.value" />
      <div class="grid gap-4 sm:grid-cols-[minmax(0,1fr)_120px]">
        <FormField :label="t('davomat.branches.name')" :error="form.errors.name" required>
          <TextInput v-model="form.values.name" :placeholder="t('davomat.branches.namePlaceholder')" :invalid="!!form.errors.name" data-field="name" @blur="form.touch('name')" />
        </FormField>
        <FormField :label="t('davomat.branches.code')" :hint="t('davomat.branches.codeHint')" :error="form.errors.code" optional>
          <TextInput v-model="form.values.code" :maxlength="10" class="font-mono uppercase" :invalid="!!form.errors.code" />
        </FormField>
      </div>
      <FormField :label="t('davomat.branches.address')" :error="form.errors.address" optional>
        <TextInput v-model="form.values.address" :invalid="!!form.errors.address" />
      </FormField>
      <FormField :label="t('davomat.branches.phone')" :error="form.errors.phone" optional>
        <TextInput v-model="form.values.phone" type="tel" inputmode="tel" :invalid="!!form.errors.phone" />
      </FormField>
    </form>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="primary" type="submit" form="branch-form" :loading="form.submitting.value" data-save-branch>{{ branch ? t("common.save") : t("davomat.branches.create") }}</UiButton>
    </template>
  </UiDialog>
</template>
