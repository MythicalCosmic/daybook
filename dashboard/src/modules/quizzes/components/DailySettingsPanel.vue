<script setup lang="ts">
/**
 * Settings › Question of the day: on or off, the time it goes out on workdays (the company's time)
 * and who gets it (everyone, or some positions). Today's numbers below.
 */
import { MessageCircleQuestion } from "@lucide/vue";
import { reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { isApiError } from "@/api/http";
import FormField from "@/components/FormField.vue";
import PositionPicker from "@/components/PositionPicker.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import TimePicker from "@/components/TimePicker.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import UiButton from "@/components/UiButton.vue";
import { toast } from "@/components/useToast";
import { useCompanyStore } from "@/stores/company";

import { quizzesApi, useDaily, useRefresh } from "../api";

const { t } = useI18n();
const company = useCompanyStore();
const refresh = useRefresh();
const daily = useDaily();

const form = reactive({ daily_question: false, daily_at: "11:00" as string | null, daily_position_ids: [] as number[] });
const saving = ref(false);
const errors = ref<Record<string, string>>({});
watch(
  () => daily.data.value,
  (found) => {
    if (!found) return;
    Object.assign(form, { daily_question: found.daily_question, daily_at: found.daily_at, daily_position_ids: [...found.daily_position_ids] });
  },
  { immediate: true },
);

async function save(): Promise<void> {
  errors.value = {};
  saving.value = true;
  try {
    await quizzesApi.updateDaily(company.currentId ?? 0, { ...form, daily_at: form.daily_at ?? "11:00" });
    toast.success(t("quizzes.daily.saved"));
    refresh();
  } catch (error) {
    if (isApiError(error)) errors.value = { form: error.detail ?? Object.values(error.fieldErrors)[0]?.[0] ?? "" };
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <div class="flex flex-col gap-4">
    <div class="flex items-start gap-3">
      <MessageCircleQuestion :size="20" class="mt-0.5 shrink-0 text-muted" aria-hidden="true" />
      <div>
        <h3 class="text-md font-semibold text-fg">{{ t("quizzes.daily.title") }}</h3>
        <p class="mt-1 text-sm text-muted">{{ t("quizzes.daily.body") }}</p>
      </div>
    </div>
    <SkeletonBlock v-if="daily.isPending.value" height="120px" />
    <template v-else>
      <ToggleSwitch v-model="form.daily_question" :label="t('quizzes.daily.on')" :description="t('quizzes.daily.onHint')" data-testid="daily-on" />
      <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <FormField :label="t('quizzes.daily.at')" :hint="t('quizzes.daily.atHint')">
          <TimePicker v-model="form.daily_at" :disabled="!form.daily_question" />
        </FormField>
        <FormField :label="t('quizzes.daily.who')" :hint="t('quizzes.daily.whoHint')" optional>
          <PositionPicker v-model="form.daily_position_ids" multiple :disabled="!form.daily_question" :placeholder="t('quizzes.daily.everyone')" />
        </FormField>
      </div>
      <p v-if="daily.data.value?.today.asked" class="text-sm text-muted">
        {{ t("quizzes.daily.today", { asked: daily.data.value.today.asked, answered: daily.data.value.today.answered, right: daily.data.value.today.right }) }}
      </p>
      <p v-if="errors.form" class="text-sm text-danger">{{ errors.form }}</p>
      <div><UiButton variant="primary" :loading="saving" @click="save">{{ t("common.save") }}</UiButton></div>
    </template>
  </div>
</template>
