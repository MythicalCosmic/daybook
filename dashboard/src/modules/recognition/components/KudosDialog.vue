<script setup lang="ts">
/**
 * "Say thanks" from the dashboard: the colleague (fixed when it opens from their profile), what
 * for, a few words. It comes from the signed-in person, like a thank-you in the app; the
 * receiver gets the points and a bot message.
 */
import { Check } from "@lucide/vue";
import { ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { isApiError } from "@/api/http";
import FormField from "@/components/FormField.vue";
import PersonPicker from "@/components/PersonPicker.vue";
import TextArea from "@/components/TextArea.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";
import { useCompanyStore } from "@/stores/company";

import { recognitionApi, useRefresh } from "../api";
import { KUDOS_BADGES } from "../lib";
import type { KudosBadge } from "../types";

const open = defineModel<boolean>("open", { default: false });
const props = defineProps<{ person?: { id: number; name: string } | null }>();

const { t } = useI18n();
const company = useCompanyStore();
const refresh = useRefresh();
const to = ref<number | null>(null);
const badge = ref<KudosBadge>("thanks");
const message = ref("");
const error = ref<string | null>(null);
const sending = ref(false);

watch(
  open,
  (value) => {
    if (!value) return;
    to.value = props.person?.id ?? null;
    badge.value = "thanks";
    message.value = "";
    error.value = null;
  },
  { immediate: true },
);

async function send(): Promise<void> {
  error.value = null;
  if (!to.value) {
    error.value = t("recognition.kudos.pickPerson");
    return;
  }
  sending.value = true;
  try {
    await recognitionApi.sendKudos(company.currentId ?? 0, { to: to.value, badge: badge.value, message: message.value.trim() });
    toast.success(t("recognition.kudos.sent"));
    refresh();
    open.value = false;
  } catch (failure) {
    error.value = isApiError(failure) ? (failure.detail ?? Object.values(failure.fieldErrors)[0]?.[0] ?? failure.message) : t("recognition.kudos.failed");
  } finally {
    sending.value = false;
  }
}
</script>

<template>
  <UiDialog v-model:open="open" :title="person ? t('recognition.kudos.titleTo', { name: person.name }) : t('recognition.kudos.title')" :description="t('recognition.kudos.description')" size="md">
    <div class="flex flex-col gap-4" data-testid="kudos-dialog">
      <FormField v-if="!person" :label="t('recognition.kudos.to')" required>
        <PersonPicker v-model="to" />
      </FormField>
      <FormField :label="t('recognition.kudos.for')">
        <div class="grid grid-cols-2 gap-2 sm:grid-cols-3" role="radiogroup" :aria-label="t('recognition.kudos.for')">
          <button
            v-for="option in KUDOS_BADGES"
            :key="option.key"
            type="button"
            role="radio"
            :aria-checked="badge === option.key"
            class="relative flex min-h-[72px] flex-col items-center justify-center gap-1.5 rounded-lg border px-2 py-3 text-center text-sm font-medium transition-colors"
            :class="badge === option.key ? 'border-primary bg-accent-soft text-accent-fg' : 'border-line bg-surface text-fg'"
            @click="badge = option.key"
          >
            <component :is="option.icon" :size="20" :stroke-width="2.2" aria-hidden="true" />
            <span>{{ t(`recognition.kudosBadge.${option.key}`) }}</span>
            <Check v-if="badge === option.key" :size="14" :stroke-width="3" class="absolute right-2 top-2" aria-hidden="true" />
          </button>
        </div>
      </FormField>
      <FormField :label="t('recognition.kudos.message')" :hint="`${message.length}/200`" :error="error ?? undefined" optional>
        <TextArea v-model="message" :rows="2" :maxlength="200" autosize :max-rows="4" :placeholder="t('recognition.kudos.placeholder')" />
      </FormField>
    </div>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="primary" :loading="sending" @click="send">{{ t("recognition.kudos.send") }}</UiButton>
    </template>
  </UiDialog>
</template>
