<script setup lang="ts">
/**
 * "Publish version N?": who will be asked (and by when), or who hears there is something new to
 * read; for a policy already in force, whether everyone signs again (the rules changed) or the
 * signatures stay (a typo, a wording); and what changed, as people will see it.
 */
import { BellRing, PenLine, Send } from "@lucide/vue";
import { ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import FormField from "@/components/FormField.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import RadioCards from "@/components/RadioCards.vue";
import TextArea from "@/components/TextArea.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";

const open = defineModel<boolean>("open", { default: false });
const props = defineProps<{
  number: number;
  /** A version is in force already: the choice of asking again appears. */
  republish: boolean;
  requiresAck: boolean;
  days: number;
  audience: number;
  changeNote: string;
  busy?: boolean;
}>();
const emit = defineEmits<{ confirm: [input: { asks_again: boolean; change_note: string }] }>();

const { t } = useI18n();
const asks = ref<"again" | "keep">("again");
const note = ref("");
watch(
  open,
  (value) => {
    if (!value) return;
    asks.value = "again";
    note.value = props.changeNote;
  },
  { immediate: true },
);
</script>

<template>
  <UiDialog v-model:open="open" :title="t('hr.policy.publishTitle', { n: number })" size="md">
    <div class="flex flex-col gap-4">
      <InlineAlert
        tone="info"
        size="sm"
        :icon="requiresAck ? BellRing : Send"
        :title="requiresAck ? t('hr.policy.publishAsk', { n: audience, days }, audience) : t('hr.policy.publishToRead', { n: audience }, audience)"
        :description="t('hr.policy.publishWhen')"
      />
      <RadioCards
        v-if="republish && requiresAck"
        v-model="asks"
        :columns="1"
        :options="[
          { value: 'again', label: t('hr.policy.asks.again'), description: t('hr.policy.asks.againHint'), icon: BellRing },
          { value: 'keep', label: t('hr.policy.asks.keep'), description: t('hr.policy.asks.keepHint'), icon: PenLine },
        ]"
      />
      <FormField v-if="republish" :label="t('hr.policy.field.changeNote')" :hint="t('hr.policy.changeNoteHint')">
        <TextArea v-model="note" :rows="2" :max-rows="5" :maxlength="300" :placeholder="t('hr.policy.changeNotePlaceholder')" />
      </FormField>
    </div>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="primary" :icon="Send" :loading="busy" data-publish-confirm @click="emit('confirm', { asks_again: asks === 'again' || !republish, change_note: note.trim() })">{{ t("hr.policy.publish") }}</UiButton>
    </template>
  </UiDialog>
</template>
