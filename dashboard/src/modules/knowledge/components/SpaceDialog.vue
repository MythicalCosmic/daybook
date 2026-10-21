<script setup lang="ts">
/** Create or edit a space: icon, name, a line about it, and who reads it (everyone or positions). */
import { Lock, Users } from "@lucide/vue";
import { computed, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";
import { z } from "zod";

import FormField from "@/components/FormField.vue";
import PositionPicker from "@/components/PositionPicker.vue";
import RadioCards from "@/components/RadioCards.vue";
import TextArea from "@/components/TextArea.vue";
import TextInput from "@/components/TextInput.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";
import { useForm } from "@/lib/useForm";
import { useCompanyStore } from "@/stores/company";

import { knowledgeApi, usePositions, useRefresh } from "../api";
import type { Space } from "../types";
import EmojiPicker from "./EmojiPicker.vue";

const open = defineModel<boolean>("open", { default: false });
const props = withDefaults(defineProps<{ space?: Space | null }>(), { space: null });
const emit = defineEmits<{ saved: [space: Space] }>();

const { t } = useI18n();
const router = useRouter();
const company = useCompanyStore();
const refresh = useRefresh();
const positions = usePositions(open);

const schema = z
  .object({
    name: z.string().trim().min(1, "common.form.required").max(100, "common.form.tooLong"),
    icon: z.string(),
    description: z.string().max(300, "common.form.tooLong"),
    audience: z.enum(["all", "positions"]),
    position_ids: z.array(z.number()),
  })
  .refine((values) => values.audience === "all" || values.position_ids.length > 0, {
    message: "knowledge.space.pickPositions",
    path: ["position_ids"],
  });

const form = useForm(
  schema,
  { name: "", icon: "📘", description: "", audience: "all" as "all" | "positions", position_ids: [] as number[] },
  {
    onSubmit: async (values) => {
      const input = {
        name: values.name,
        icon: values.icon,
        description: values.description,
        audience_all: values.audience === "all",
        position_ids: values.audience === "all" ? [] : values.position_ids,
      };
      const cid = company.currentId ?? 0;
      const saved = props.space ? await knowledgeApi.updateSpace(cid, props.space.id, input) : await knowledgeApi.createSpace(cid, input);
      await refresh();
      toast.success(props.space ? t("knowledge.space.saved") : t("knowledge.space.created", { name: saved.name }));
      open.value = false;
      emit("saved", saved);
      if (!props.space) void router.push(`/c/${cid}/knowledge/s/${saved.id}`);
    },
  },
);

watch(open, (isOpen) => {
  if (!isOpen) return;
  const space = props.space;
  form.reset(
    space
      ? {
          name: space.name,
          icon: space.icon,
          description: space.description,
          audience: space.audience_all ? "all" : "positions",
          position_ids: space.positions.map((position) => position.id),
        }
      : { name: "", icon: "📘", description: "", audience: "all", position_ids: [] },
  );
});

const audienceOptions = computed(() => [
  { value: "all" as const, label: t("knowledge.space.everyone"), description: t("knowledge.space.everyoneHint"), icon: Users },
  { value: "positions" as const, label: t("knowledge.space.somePositions"), description: t("knowledge.space.somePositionsHint"), icon: Lock },
]);
</script>

<template>
  <UiDialog v-model:open="open" :title="space ? t('knowledge.space.editTitle') : t('knowledge.space.newTitle')" :description="t('knowledge.space.dialogHint')" size="md">
    <form id="kb-space-form" class="flex flex-col gap-4" @submit.prevent="form.submit">
      <div class="flex items-end gap-3">
        <FormField :label="t('knowledge.space.icon')">
          <EmojiPicker v-model="form.values.icon" />
        </FormField>
        <FormField :label="t('knowledge.space.name')" :error="form.errors.name" required class="min-w-0 flex-1">
          <TextInput v-model="form.values.name" :placeholder="t('knowledge.space.namePlaceholder')" :maxlength="100" autofocus @blur="form.touch('name')" />
        </FormField>
      </div>
      <FormField :label="t('knowledge.space.description')" :error="form.errors.description" optional :count="form.values.description.length" :max="300">
        <TextArea v-model="form.values.description" :rows="2" :placeholder="t('knowledge.space.descriptionPlaceholder')" />
      </FormField>
      <FormField :label="t('knowledge.space.audience')">
        <RadioCards v-model="form.values.audience" :options="audienceOptions" :columns="2" />
      </FormField>
      <FormField v-if="form.values.audience === 'positions'" :label="t('knowledge.space.positions')" :error="form.errors.position_ids" required>
        <PositionPicker v-model="form.values.position_ids" multiple :positions="positions.data.value ?? []" />
      </FormField>
      <p v-if="form.formError.value" class="text-sm text-danger">{{ form.formError.value }}</p>
    </form>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="primary" type="submit" form="kb-space-form" :loading="form.submitting.value">{{ space ? t("common.save") : t("knowledge.space.create") }}</UiButton>
    </template>
  </UiDialog>
</template>
