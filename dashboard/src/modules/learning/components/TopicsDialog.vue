<script setup lang="ts">
/**
 * Add topics to an unchangeable list: one topic per line, typed or pasted (a numbered or bulleted
 * list is fine; the list numbers its topics itself, after the ones it has).
 */
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { isApiError } from "@/api/http";
import FormField from "@/components/FormField.vue";
import TextArea from "@/components/TextArea.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";
import { useCompanyId } from "@/stores/company";

import { learningApi, useApplyList } from "../api";
import { parseTitles } from "../lists";
import type { StudyListDetail } from "../types";

const open = defineModel<boolean>("open", { default: false });
const props = defineProps<{ list: StudyListDetail }>();

const { t } = useI18n();
const cid = useCompanyId();
const apply = useApplyList();

const MAX_TOPICS = 100;
const MAX_TITLE = 300;

const text = ref("");
const error = ref<string | null>(null);
const busy = ref(false);
watch(open, (value) => {
  if (value) {
    text.value = "";
    error.value = null;
  }
});

const titles = computed(() => parseTitles(text.value));
const next = computed(() => Math.max(0, ...props.list.topics.map((topic) => topic.number)) + 1);
const problem = computed(() => {
  if (titles.value.length > MAX_TOPICS) return t("learning.lists.topics.tooMany", { n: MAX_TOPICS });
  if (titles.value.some((title) => title.length > MAX_TITLE)) return t("learning.lists.topics.tooLong", { n: MAX_TITLE });
  return null;
});
const hint = computed(() => {
  const n = titles.value.length;
  if (!n) return t("learning.lists.topics.hint");
  return n === 1 ? t("learning.lists.topics.previewOne", { from: next.value }) : t("learning.lists.topics.preview", { n, from: next.value, to: next.value + n - 1 });
});

async function save(): Promise<void> {
  if (busy.value || !titles.value.length || problem.value) return;
  busy.value = true;
  error.value = null;
  try {
    apply(await learningApi.addTopics(cid.value, props.list.id, titles.value));
    toast.success(t("learning.lists.topics.added", { n: titles.value.length }, titles.value.length));
    open.value = false;
  } catch (failure) {
    // `{ titles: […] }` names no field on screen, so it is said here (a `detail` was toasted).
    error.value = isApiError(failure) && !failure.detail ? (Object.values(failure.fieldErrors)[0]?.[0] ?? null) : null;
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <UiDialog v-model:open="open" :title="t('learning.lists.topics.title')" :description="t('learning.lists.topics.description')" size="md">
    <FormField :label="t('learning.lists.topics.label')" :hint="hint" :error="problem ?? error" required>
      <TextArea v-model="text" :rows="8" :max-rows="16" autofocus :placeholder="t('learning.lists.topics.placeholder')" data-testid="topics-text" @submit="save" />
    </FormField>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="primary" :loading="busy" :disabled="!titles.length || !!problem" data-testid="topics-save" @click="save">
        {{ titles.length ? t("learning.lists.topics.submit", { n: titles.length }, titles.length) : t("learning.lists.topics.submitEmpty") }}
      </UiButton>
    </template>
  </UiDialog>
</template>
