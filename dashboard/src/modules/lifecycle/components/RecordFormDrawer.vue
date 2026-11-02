<script setup lang="ts">
/**
 * Record a disciplinary step (plan §13.4): whom, which kind and category (the pharmacy ones first),
 * when it happened, what happened, evidence if there is any, and "also propose a fine": the amount
 * goes to payroll as a proposal that a manager approves there. The employee reads it in the app,
 * confirms it and can write their explanation.
 */
import { Banknote, Gavel } from "@lucide/vue";
import { computed, reactive, watch } from "vue";
import { useI18n } from "vue-i18n";

import { isApiError, unshownFieldError } from "@/api/http";
import DatePicker from "@/components/DatePicker.vue";
import FileDrop from "@/components/FileDrop.vue";
import FormField from "@/components/FormField.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import MoneyInput from "@/components/MoneyInput.vue";
import type { SelectOption } from "@/components/options";
import PersonPicker from "@/components/PersonPicker.vue";
import RadioCards from "@/components/RadioCards.vue";
import SelectBox from "@/components/SelectBox.vue";
import TextArea from "@/components/TextArea.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import UiButton from "@/components/UiButton.vue";
import UiDrawer from "@/components/UiDrawer.vue";
import { toast } from "@/components/useToast";
import { useCompanyStore, useCompanyToday } from "@/stores/company";

import { lifecycleApi, useLifecycleMutation } from "../api";
import { recordFormErrors, recordPayload, type RecordForm } from "../lib";
import { GENERAL_CATEGORIES, PHARMACY_CATEGORIES, type DisciplinaryRecord, type RecordCategory, type RecordInput, type RecordKind } from "../types";

const open = defineModel<boolean>("open", { default: false });
/** The person when it is decided already (Person 360); without a name the picker shows it, locked. */
const props = withDefaults(defineProps<{ member?: { id: number; name: string } | null }>(), { member: null });
const emit = defineEmits<{ saved: [record: DisciplinaryRecord] }>();

const { t } = useI18n();
const company = useCompanyStore();
const today = useCompanyToday();

const form = reactive<RecordForm>({ member: null, kind: "verbal_warning", category: null, incident_on: null, description: "", files: [], proposeFine: false, fine: null });
const errors = reactive<Record<string, string | undefined>>({});

watch(
  open,
  (isOpen) => {
    if (!isOpen) return;
    for (const key of Object.keys(errors)) delete errors[key];
    Object.assign(form, { member: props.member?.id ?? null, kind: "verbal_warning", category: null, incident_on: today.value, description: "", files: [], proposeFine: false, fine: null });
  },
  { immediate: true },
);

/** A fine goes to payroll: only where payroll is on and the person may propose one. */
const canFine = computed(() => company.enabled("payroll") && company.can(["payroll.propose", "payroll.manage"]));

const kindOptions = computed(() =>
  (["verbal_warning", "written_warning", "final_warning", "reprimand"] as RecordKind[]).map((kind) => ({ value: kind, label: t(`lifecycle.kind.${kind}`), description: t(`lifecycle.kindHint.${kind}`) })),
);
const categoryOptions = computed<SelectOption<RecordCategory>[]>(() => [
  ...PHARMACY_CATEGORIES.map((value) => ({ value, label: t(`lifecycle.category.${value}`), group: t("lifecycle.categoryGroup.pharmacy") })),
  ...GENERAL_CATEGORIES.map((value) => ({ value, label: t(`lifecycle.category.${value}`), group: t("lifecycle.categoryGroup.general") })),
]);

const save = useLifecycleMutation((cid, input: RecordInput) => lifecycleApi.createRecord(cid, input));

async function submit(): Promise<void> {
  for (const key of Object.keys(errors)) delete errors[key];
  const problems = recordFormErrors({ ...form, proposeFine: form.proposeFine && canFine.value }, today.value);
  for (const [field, problem] of Object.entries(problems)) errors[field] = t(`lifecycle.form.${problem}`);
  if (Object.keys(problems).length) return;
  try {
    const saved = await save.mutateAsync(recordPayload({ ...form, proposeFine: form.proposeFine && canFine.value }));
    toast.success(t("lifecycle.record.created", { name: saved.member.name }));
    emit("saved", saved);
    open.value = false;
  } catch (failure) {
    if (isApiError(failure)) {
      for (const [field, messages] of Object.entries(failure.fieldErrors)) errors[field === "member_id" ? "member" : field === "fine_amount" ? "fine" : field] = messages[0];
      const unshown = unshownFieldError(failure, ["member_id", "kind", "category", "incident_on", "description", "fine_amount", "evidence"]);
      if (unshown) toast.error(unshown);
    }
  }
}
</script>

<template>
  <UiDrawer v-model:open="open" size="md" :title="t('lifecycle.record.newTitle')" :description="t('lifecycle.record.newHint')">
    <form class="flex flex-col gap-4 p-5" @submit.prevent="submit">
      <FormField v-if="!member?.name" :label="t('lifecycle.field.person')" :error="errors.member" required>
        <PersonPicker v-model="form.member" :invalid="!!errors.member" :disabled="!!member" />
      </FormField>
      <p v-else class="rounded-[10px] bg-surface-2 px-3 py-2 text-sm text-muted">
        {{ t("lifecycle.field.person") }}: <span class="font-semibold text-fg">{{ member.name }}</span>
      </p>

      <FormField :label="t('lifecycle.field.kind')" required>
        <RadioCards v-model="form.kind" :options="kindOptions" :columns="2" />
      </FormField>

      <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <FormField :label="t('lifecycle.field.category')" :error="errors.category" required>
          <SelectBox v-model="form.category" :options="categoryOptions" :placeholder="t('lifecycle.record.categoryPlaceholder')" :invalid="!!errors.category" />
        </FormField>
        <FormField :label="t('lifecycle.field.incidentOn')" :error="errors.incident_on" required>
          <DatePicker v-model="form.incident_on" :max="today" :invalid="!!errors.incident_on" />
        </FormField>
      </div>

      <FormField :label="t('lifecycle.field.description')" :hint="t('lifecycle.record.descriptionHint')" :error="errors.description" required :count="form.description.length" :max="2000">
        <TextArea v-model="form.description" :rows="4" :maxlength="2000" :placeholder="t('lifecycle.record.descriptionPlaceholder')" :invalid="!!errors.description" />
      </FormField>

      <FormField :label="t('lifecycle.field.evidence')" :error="errors.evidence" optional>
        <FileDrop v-model="form.files" accept="image/*,application/pdf" compact :hint="t('lifecycle.record.evidenceHint')" />
      </FormField>

      <section v-if="canFine" :class="['flex flex-col gap-3 rounded-card border p-3.5 transition-colors', form.proposeFine ? 'border-[color-mix(in_srgb,var(--c-warning)_45%,transparent)] bg-warning-soft/40' : 'border-line']">
        <ToggleSwitch v-model="form.proposeFine" layout="row" :label="t('lifecycle.record.proposeFine')" :description="t('lifecycle.record.proposeFineHint')" />
        <FormField v-if="form.proposeFine" :label="t('lifecycle.field.fine')" :error="errors.fine" required>
          <MoneyInput v-model="form.fine" :currencies="[company.currency]" :invalid="!!errors.fine" />
        </FormField>
        <InlineAlert v-if="form.proposeFine" tone="info" size="sm" :icon="Banknote" :description="t('lifecycle.record.fineNote')" />
      </section>
    </form>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="primary" :icon="Gavel" :loading="save.isPending.value" @click="submit">{{ t("lifecycle.record.issue") }}</UiButton>
    </template>
  </UiDrawer>
</template>
