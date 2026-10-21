<script setup lang="ts">
/**
 * Take back approved time off: all of it (before it starts), or from a day on (it then ends the day
 * before). Once it has started it can only be cut from today or later. The person is told in the
 * bot, with the reason.
 */
import { CalendarX2 } from "@lucide/vue";
import { computed, ref, watch } from "vue";
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
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { useRevoke } from "../api";
import type { TimeOffRow } from "../types";

const open = defineModel<boolean>("open", { default: false });
const props = defineProps<{ row: TimeOffRow }>();

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const revoke = useRevoke();

const today = computed(() => todayIn(company.timezone));
const started = computed(() => props.row.first_day <= today.value);
const mode = ref<"all" | "from">(started.value && props.row.first_day < today.value ? "from" : "all");
const firstPossible = computed(() => (started.value ? (today.value > props.row.first_day ? today.value : addDays(props.row.first_day, 1)) : addDays(props.row.first_day, 1)));
const fromDay = ref<string | null>(firstPossible.value <= props.row.last_day ? firstPossible.value : null);
const reason = ref("");
const error = ref<string | null>(null);
const canCut = computed(() => props.row.days > 1 && firstPossible.value <= props.row.last_day);
watch(mode, (value) => {
  if (value === "from" && !fromDay.value && canCut.value) fromDay.value = firstPossible.value;
});

const outcome = computed(() => {
  if (mode.value === "all" || !fromDay.value || fromDay.value <= props.row.first_day) return t("timeoff.revoke.outcomeAll");
  return t("timeoff.revoke.outcomeCut", { date: fmt.day(addDays(fromDay.value, -1), "long") });
});

async function submit(): Promise<void> {
  error.value = null;
  if (!reason.value.trim()) {
    error.value = t("timeoff.revoke.reasonRequired");
    return;
  }
  try {
    await revoke.mutateAsync({ id: props.row.id, reason: reason.value.trim(), from_day: mode.value === "from" ? fromDay.value : null });
    toast.success(t("timeoff.revoke.done", { name: props.row.member.name }));
    open.value = false;
  } catch {
    // The HTTP layer showed why.
  }
}
</script>

<template>
  <UiDialog v-model:open="open" :title="t('timeoff.revoke.title', { name: row.member.name })" :description="t('timeoff.revoke.description')" size="sm">
    <div class="flex flex-col gap-4">
      <SegmentedControl
        v-if="canCut && (!started || row.first_day === today)"
        v-model="mode"
        block
        :options="[
          { value: 'all', label: t('timeoff.revoke.all') },
          { value: 'from', label: t('timeoff.revoke.fromDay') },
        ]"
      />
      <FormField v-if="mode === 'from' && canCut" :label="t('timeoff.revoke.firstDayBack')" :hint="t('timeoff.revoke.firstDayBackHint')">
        <DatePicker v-model="fromDay" :min="firstPossible" :max="row.last_day" />
      </FormField>
      <InlineAlert tone="info" size="sm" :description="outcome" />
      <FormField :label="t('timeoff.revoke.reason')" :hint="t('timeoff.revoke.reasonHint')" :error="error" required>
        <TextArea v-model="reason" :rows="3" :maxlength="300" :placeholder="t('timeoff.revoke.reasonPlaceholder')" />
      </FormField>
    </div>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="danger" :icon="CalendarX2" :loading="revoke.isPending.value" @click="submit">{{ t("timeoff.revoke.confirm") }}</UiButton>
    </template>
  </UiDialog>
</template>
