<script setup lang="ts">
/**
 * "Assign to people" on a course's People tab: anyone the manager sees (branch scope), with an
 * optional deadline (the end of that day in the company's time). People who already have the
 * course open or still valid are marked and skipped.
 */
import { useQuery } from "@tanstack/vue-query";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import DatePicker from "@/components/DatePicker.vue";
import FormField from "@/components/FormField.vue";
import MultiSelect from "@/components/MultiSelect.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";
import { useCompanyId, useCompanyToday } from "@/stores/company";

import { learningApi, learningKeys, useRefresh } from "../api";

const props = defineProps<{ courseId: number }>();
const open = defineModel<boolean>("open", { default: false });

const { t } = useI18n();
const cid = useCompanyId();
const today = useCompanyToday();
const refresh = useRefresh();
const chosen = ref<number[]>([]);
const dueOn = ref<string | null>(null);
const busy = ref(false);
watch(open, (value) => {
  if (value) {
    chosen.value = [];
    dueOn.value = null;
  }
});

const candidates = useQuery({
  queryKey: computed(() => learningKeys.of(cid.value, "candidates", { id: props.courseId })),
  queryFn: () => learningApi.candidates(cid.value, props.courseId),
  enabled: computed(() => open.value && props.courseId > 0),
});
const options = computed(() =>
  (candidates.data.value ?? []).map((person) => ({
    value: person.id,
    label: person.name,
    description: person.assigned ? t("learning.assign.already") : [person.position, person.branch].filter(Boolean).join(" · ") || undefined,
    avatar: { name: person.name, src: person.photo_url },
    disabled: person.assigned,
  })),
);

async function save(): Promise<void> {
  if (!chosen.value.length) return;
  busy.value = true;
  try {
    const { count } = await learningApi.assign(cid.value, props.courseId, { member_ids: chosen.value, due_on: dueOn.value });
    toast.success(t("learning.assign.done", { n: count }, count));
    refresh();
    open.value = false;
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <UiDialog v-model:open="open" :title="t('learning.assign.title')" :description="t('learning.assign.hint')" size="md">
    <div class="flex flex-col gap-4">
      <FormField :label="t('learning.assign.people')">
        <MultiSelect v-model="chosen" :options="options" :placeholder="t('learning.assign.pick')" :search-placeholder="t('common.search')" display="chips" />
      </FormField>
      <FormField :label="t('learning.assign.due')" :hint="t('learning.assign.dueHint')" optional>
        <DatePicker v-model="dueOn" :min="today" clearable />
      </FormField>
    </div>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="primary" :loading="busy" :disabled="!chosen.length" @click="save">{{ t("learning.assign.submit") }}</UiButton>
    </template>
  </UiDialog>
</template>
