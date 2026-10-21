<script setup lang="ts">
/**
 * Pause someone's access (members.services.suspend): until a day, or until reinstated, with the
 * reason. The bot, the app and the reminders leave them alone meanwhile; their record stays.
 * Package S replaces this with its own suspensions (paid/unpaid, records) through
 * `people.profile.actions`.
 */
import { Pause } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import DatePicker from "@/components/DatePicker.vue";
import FormField from "@/components/FormField.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import TextArea from "@/components/TextArea.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";
import { addDays, todayIn } from "@/lib/dates";
import { useCompanyStore } from "@/stores/company";

import { suspendPerson, usePersonMutation } from "../api";
import type { PersonDetail } from "../types";

const open = defineModel<boolean>("open", { default: false });
const props = defineProps<{ person: PersonDetail }>();

const { t } = useI18n();
const company = useCompanyStore();
const today = computed(() => todayIn(company.timezone));

const mode = ref<"until" | "open">("until");
const until = ref<string | null>(addDays(today.value, 7));
const reason = ref("");
const error = ref<string | null>(null);

const suspend = usePersonMutation((cid, body: { until: string | null; reason: string }) => suspendPerson(cid, props.person.id, body));

async function submit(): Promise<void> {
  error.value = null;
  if (!reason.value.trim()) {
    error.value = t("people.suspend.reasonRequired");
    return;
  }
  try {
    await suspend.mutateAsync({ until: mode.value === "until" ? until.value : null, reason: reason.value.trim() });
    toast.success(t("people.suspend.done", { name: props.person.name }));
    open.value = false;
  } catch {
    // The HTTP layer showed why.
  }
}
</script>

<template>
  <UiDialog v-model:open="open" :title="t('people.suspend.title', { name: person.name })" :description="t('people.suspend.description')" size="sm">
    <div class="flex flex-col gap-4">
      <SegmentedControl
        v-model="mode"
        block
        :options="[
          { value: 'until', label: t('people.suspend.untilDay') },
          { value: 'open', label: t('people.suspend.untilReinstated') },
        ]"
      />
      <FormField v-if="mode === 'until'" :label="t('people.suspend.lastDay')" :hint="t('people.suspend.lastDayHint')">
        <DatePicker v-model="until" :min="today" />
      </FormField>
      <FormField :label="t('people.suspend.reason')" :error="error" required>
        <TextArea v-model="reason" :rows="3" :maxlength="300" :placeholder="t('people.suspend.reasonPlaceholder')" />
      </FormField>
      <InlineAlert tone="warning" size="sm" :description="t('people.suspend.effects')" />
    </div>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="danger" :icon="Pause" :loading="suspend.isPending.value" @click="submit">{{ t("people.suspend.confirm") }}</UiButton>
    </template>
  </UiDialog>
</template>
