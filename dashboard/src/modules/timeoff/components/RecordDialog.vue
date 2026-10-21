<script setup lang="ts">
/**
 * Record time off for someone (plan §4.6): sick leave after the fact, a day off agreed in person.
 * Past days are allowed (back to the last finalized payroll period, at most a year); it is
 * approved at once and the person is told in the bot. A sick note can be attached (photo or PDF).
 */
import { CalendarPlus } from "@lucide/vue";
import { computed, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import DatePicker from "@/components/DatePicker.vue";
import FileDrop from "@/components/FileDrop.vue";
import FormField from "@/components/FormField.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import PersonPicker from "@/components/PersonPicker.vue";
import TextInput from "@/components/TextInput.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";
import { addDays, diffDays, todayIn } from "@/lib/dates";
import { useCompanyStore } from "@/stores/company";

import { useRecord } from "../api";
import type { TimeOffRow } from "../types";

const open = defineModel<boolean>("open", { default: false });
const props = defineProps<{ memberId?: number | null }>();
const emit = defineEmits<{ recorded: [row: TimeOffRow] }>();

const { t } = useI18n();
const company = useCompanyStore();
const record = useRecord();

const today = computed(() => todayIn(company.timezone));
const member = ref<number | null>(props.memberId ?? null);
const first = ref<string | null>(today.value);
const last = ref<string | null>(today.value);
const reason = ref("");
const files = ref<File[]>([]);
const errors = ref<Record<string, string>>({});
const formError = ref<string | null>(null);

// Nobody picked yet: start in the person picker (the dialog itself focuses the first text box).
const personField = ref<HTMLElement | null>(null);
onMounted(() => {
  if (member.value) return;
  requestAnimationFrame(() => requestAnimationFrame(() => personField.value?.querySelector<HTMLElement>("[role=combobox]")?.focus({ preventScroll: true })));
});

watch(first, (value) => {
  if (value && (!last.value || last.value < value)) last.value = value;
});

const days = computed(() => (first.value && last.value && last.value >= first.value ? diffDays(first.value, last.value) + 1 : 0));
const past = computed(() => !!first.value && first.value < today.value);
const QUICK = ["sick", "dayOff", "family", "vacation", "study"] as const;

async function submit(): Promise<void> {
  const next: Record<string, string> = {};
  if (!member.value) next.member = t("timeoff.record.pickPerson");
  if (!first.value) next.first = t("common.form.required");
  if (!last.value) next.last = t("common.form.required");
  errors.value = next;
  formError.value = null;
  if (Object.keys(next).length) return;
  try {
    const row = await record.mutateAsync({ member_id: member.value!, first_day: first.value!, last_day: last.value!, reason: reason.value.trim(), attachment: files.value[0] ?? null });
    toast.success(t("timeoff.record.done", { name: row.member.name }), { description: t("timeoff.record.doneHint") });
    emit("recorded", row);
    open.value = false;
  } catch (error) {
    const fields = (error as { fieldErrors?: Record<string, string[]> }).fieldErrors ?? {};
    if (fields.member_id) errors.value = { member: fields.member_id[0]! };
  }
}
</script>

<template>
  <UiDialog v-model:open="open" :title="t('timeoff.record.title')" :description="t('timeoff.record.description')" size="md">
    <div class="flex flex-col gap-4">
      <InlineAlert v-if="formError" tone="danger" :description="formError" />
      <div ref="personField">
        <FormField :label="t('timeoff.record.person')" :error="errors.member" required>
          <PersonPicker v-model="member" :placeholder="t('timeoff.record.personPlaceholder')" />
        </FormField>
      </div>
      <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <FormField :label="t('timeoff.record.first')" :error="errors.first" required>
          <DatePicker v-model="first" :min="addDays(today, -366)" />
        </FormField>
        <FormField :label="t('timeoff.record.last')" :error="errors.last" required>
          <DatePicker v-model="last" :min="first ?? addDays(today, -366)" />
        </FormField>
      </div>
      <p v-if="days" class="-mt-2 text-sm text-muted">
        {{ t("timeoff.days", { n: days }, days) }}<template v-if="past"> · {{ t("timeoff.record.pastNote") }}</template>
      </p>
      <FormField :label="t('timeoff.record.reason')" optional>
        <TextInput v-model="reason" :maxlength="300" :placeholder="t('timeoff.record.reasonPlaceholder')" />
        <div class="mt-2 flex flex-wrap gap-1.5">
          <button
            v-for="quick in QUICK"
            :key="quick"
            type="button"
            :class="[
              'pressable inline-flex h-7 items-center rounded-full border px-2.5 text-xs font-medium transition-colors',
              reason === t(`timeoff.reasons.${quick}`) ? 'border-primary bg-accent-soft text-accent-fg' : 'border-line text-muted hover:bg-highlight hover:text-fg',
            ]"
            @click="reason = t(`timeoff.reasons.${quick}`)"
          >
            {{ t(`timeoff.reasons.${quick}`) }}
          </button>
        </div>
      </FormField>
      <FormField :label="t('timeoff.record.note')" :hint="t('timeoff.record.noteHint')" optional>
        <FileDrop v-model="files" accept="image/*,application/pdf" :max-size="10 * 1024 * 1024" compact :title="t('timeoff.record.noteDrop')" />
      </FormField>
    </div>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="primary" :icon="CalendarPlus" :loading="record.isPending.value" @click="submit">{{ t("timeoff.record.confirm") }}</UiButton>
    </template>
  </UiDialog>
</template>
