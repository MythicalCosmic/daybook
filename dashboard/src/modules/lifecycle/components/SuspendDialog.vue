<script setup lang="ts">
/**
 * Suspend someone (over members.services.suspend): until a day, or until reinstated, and why. The
 * bot, the app and the reminders leave them alone meanwhile; their record stays. The server refuses
 * what it must (the last owner, someone already suspended) and says why.
 */
import { Pause } from "@lucide/vue";
import { ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import DatePicker from "@/components/DatePicker.vue";
import FormField from "@/components/FormField.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import PersonPicker from "@/components/PersonPicker.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import TextArea from "@/components/TextArea.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";
import { addDays } from "@/lib/dates";
import { useCompanyToday } from "@/stores/company";

import { lifecycleApi, useLifecycleMutation } from "../api";
import type { SuspendInput, Suspension } from "../types";

const open = defineModel<boolean>("open", { default: false });
const props = withDefaults(defineProps<{ member?: { id: number; name: string } | null }>(), { member: null });
const emit = defineEmits<{ saved: [suspension: Suspension] }>();

const { t } = useI18n();
const today = useCompanyToday();

const person = ref<number | null>(null);
const mode = ref<"until" | "open">("until");
const until = ref<string | null>(null);
const reason = ref("");
const errors = ref<Record<string, string>>({});

watch(
  open,
  (isOpen) => {
    if (!isOpen) return;
    errors.value = {};
    person.value = props.member?.id ?? null;
    mode.value = "until";
    until.value = addDays(today.value, 7);
    reason.value = "";
  },
  { immediate: true },
);

const save = useLifecycleMutation((cid, input: SuspendInput) => lifecycleApi.suspend(cid, input));

async function submit(): Promise<void> {
  const next: Record<string, string> = {};
  if (!person.value) next.member = t("lifecycle.form.required");
  if (mode.value === "until" && !until.value) next.until = t("lifecycle.form.required");
  if (!reason.value.trim()) next.reason = t("lifecycle.suspend.reasonRequired");
  errors.value = next;
  if (Object.keys(next).length) return;
  try {
    const saved = await save.mutateAsync({ member_id: person.value!, until: mode.value === "until" ? until.value : null, reason: reason.value.trim() });
    toast.success(t("lifecycle.suspend.done", { name: saved.member.name }));
    emit("saved", saved);
    open.value = false;
  } catch {
    // The HTTP layer showed the server's reason (the last owner can't be suspended, for example).
  }
}
</script>

<template>
  <UiDialog v-model:open="open" size="sm" :title="member ? t('lifecycle.suspend.titleFor', { name: member.name }) : t('lifecycle.suspend.title')" :description="t('lifecycle.suspend.description')">
    <div class="flex flex-col gap-4">
      <FormField v-if="!member" :label="t('lifecycle.field.person')" :error="errors.member" required>
        <PersonPicker v-model="person" :invalid="!!errors.member" />
      </FormField>
      <SegmentedControl
        v-model="mode"
        block
        :options="[
          { value: 'until', label: t('lifecycle.suspend.untilDay') },
          { value: 'open', label: t('lifecycle.suspend.untilReinstated') },
        ]"
      />
      <FormField v-if="mode === 'until'" :label="t('lifecycle.suspend.lastDay')" :hint="t('lifecycle.suspend.lastDayHint')" :error="errors.until" required>
        <DatePicker v-model="until" :min="today" format="long" />
      </FormField>
      <FormField :label="t('lifecycle.suspend.reason')" :error="errors.reason" required>
        <TextArea v-model="reason" :rows="3" :maxlength="300" :placeholder="t('lifecycle.suspend.reasonPlaceholder')" :invalid="!!errors.reason" />
      </FormField>
      <InlineAlert tone="warning" size="sm" :description="t('lifecycle.suspend.effects')" />
    </div>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="danger" :icon="Pause" :loading="save.isPending.value" @click="submit">{{ t("lifecycle.suspend.confirm") }}</UiButton>
    </template>
  </UiDialog>
</template>
