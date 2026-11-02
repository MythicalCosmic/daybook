<script setup lang="ts">
/**
 * A new contract (a draft until it is activated): whose, which kind, the dates (a fixed-term one
 * needs an end), probation and weekly hours, and where the paper comes from: one of the company's
 * templates (the PDF is generated from it) or a scan of a contract signed on paper.
 */
import { FilePlus2, FileSignature, ScanLine } from "@lucide/vue";
import { computed, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { isApiError, unshownFieldError } from "@/api/http";
import DatePicker from "@/components/DatePicker.vue";
import FileDrop from "@/components/FileDrop.vue";
import FormField from "@/components/FormField.vue";
import NumberInput from "@/components/NumberInput.vue";
import type { SelectOption } from "@/components/options";
import PersonPicker from "@/components/PersonPicker.vue";
import RadioCards from "@/components/RadioCards.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SelectBox from "@/components/SelectBox.vue";
import TextInput from "@/components/TextInput.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";
import { addMonths } from "@/lib/dates";
import { useCompanyToday } from "@/stores/company";

import { hrApi, useHrMutation, useTemplates } from "../api";
import { contractDatesProblem } from "../lib";
import { CONTRACT_KINDS, type Contract, type ContractKind } from "../types";

const open = defineModel<boolean>("open", { default: false });
const props = withDefaults(defineProps<{ member?: { id: number; name: string } | null }>(), { member: null });
const emit = defineEmits<{ saved: [contract: Contract] }>();

const { t } = useI18n();
const today = useCompanyToday();
const templates = useTemplates(open);

const form = reactive({
  member: null as number | null,
  kind: "indefinite" as ContractKind,
  number: "",
  starts_on: null as string | null,
  ends_on: null as string | null,
  probation_until: null as string | null,
  weekly_hours: 40 as number | null,
  source: "template" as "template" | "scan",
  template: null as number | null,
  files: [] as File[],
});
const errors = reactive<Record<string, string | undefined>>({});

watch(
  open,
  (isOpen) => {
    if (!isOpen) return;
    for (const key of Object.keys(errors)) delete errors[key];
    Object.assign(form, {
      member: props.member?.id ?? null,
      kind: "indefinite",
      number: "",
      starts_on: today.value,
      ends_on: null,
      probation_until: null,
      weekly_hours: 40,
      source: "template",
      template: null,
      files: [],
    });
  },
  { immediate: true },
);

const kindOptions = computed(() => CONTRACT_KINDS.map((kind) => ({ value: kind, label: t(`hr.contractKind.${kind}`), description: t(`hr.contractKindHint.${kind}`) })));
/** Active templates, the ones for this kind first. */
const templateOptions = computed<SelectOption<number>[]>(() =>
  (templates.data.value ?? [])
    .filter((row) => row.is_active)
    .sort((a, b) => Number(b.kind === form.kind) - Number(a.kind === form.kind))
    .map((row) => ({ value: row.id, label: row.name, description: `${row.kind ? t(`hr.contractKind.${row.kind}`) : t("hr.template.anyKind")} · ${t(`hr.language.${row.language}`)}` })),
);
// Pick the first template for the chosen kind, unless one was picked by hand.
const pickedByHand = ref(false);
watch(
  () => [form.kind, templateOptions.value] as const,
  () => {
    if (pickedByHand.value && form.template) return;
    const active = (templates.data.value ?? []).filter((row) => row.is_active);
    const match = active.find((row) => row.kind === form.kind) ?? active.find((row) => row.kind === "");
    form.template = match?.id ?? null;
  },
);
const needsEnd = computed(() => form.kind === "fixed_term");

function probationIn(months: number): void {
  if (form.starts_on) form.probation_until = addMonths(form.starts_on, months);
}

const save = useHrMutation((cid, body: Parameters<typeof hrApi.createContract>[1]) => hrApi.createContract(cid, body));

async function submit(): Promise<void> {
  for (const key of Object.keys(errors)) delete errors[key];
  if (!form.member) errors.member = t("hr.form.required");
  const problem = contractDatesProblem(form);
  if (problem) errors[problem] = t(`hr.contract.problem.${problem}`);
  if (form.source === "scan" && !form.files.length) errors.file = t("hr.contract.scanRequired");
  if (Object.values(errors).some(Boolean)) return;
  try {
    const saved = await save.mutateAsync({
      member_id: form.member!,
      kind: form.kind,
      number: form.number.trim(),
      starts_on: form.starts_on!,
      ends_on: form.ends_on,
      probation_until: form.probation_until,
      weekly_hours: form.weekly_hours === null ? null : String(form.weekly_hours),
      template_id: form.source === "template" ? form.template : null,
      file: form.source === "scan" ? (form.files[0] ?? null) : null,
    });
    toast.success(t("hr.contract.created", { name: saved.member.name }));
    emit("saved", saved);
    open.value = false;
  } catch (failure) {
    if (isApiError(failure)) {
      for (const [field, messages] of Object.entries(failure.fieldErrors)) errors[field === "member_id" ? "member" : field === "template_id" ? "template" : field] = messages[0];
      const unshown = unshownFieldError(failure, ["member_id", "kind", "number", "starts_on", "ends_on", "probation_until", "weekly_hours", "template_id", "file"]);
      if (unshown) toast.error(unshown);
    }
  }
}
</script>

<template>
  <UiDialog v-model:open="open" size="lg" :title="t('hr.contract.new')" :description="t('hr.contract.newHint')">
    <form class="flex flex-col gap-4" @submit.prevent="submit">
      <FormField v-if="!member" :label="t('hr.field.person')" :error="errors.member" required>
        <PersonPicker v-model="form.member" :invalid="!!errors.member" />
      </FormField>
      <p v-else class="rounded-[10px] bg-surface-2 px-3 py-2 text-sm text-muted">
        {{ t("hr.field.person") }}: <span class="font-semibold text-fg">{{ member.name }}</span>
      </p>

      <FormField :label="t('hr.field.contractKind')" required>
        <RadioCards v-model="form.kind" :options="kindOptions" :columns="2" />
      </FormField>

      <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <FormField :label="t('hr.field.startsOn')" :error="errors.starts_on" required>
          <DatePicker v-model="form.starts_on" :invalid="!!errors.starts_on" />
        </FormField>
        <FormField :label="t('hr.field.endsOn')" :hint="needsEnd ? t('hr.contract.endRequired') : t('hr.contract.endOptional')" :error="errors.ends_on" :required="needsEnd" :optional="!needsEnd">
          <DatePicker v-model="form.ends_on" :min="form.starts_on" clearable :invalid="!!errors.ends_on" />
        </FormField>
        <FormField :label="t('hr.field.probationUntil')" :error="errors.probation_until" optional>
          <DatePicker v-model="form.probation_until" :min="form.starts_on" :max="form.ends_on" clearable :invalid="!!errors.probation_until" />
          <div class="mt-1.5 flex flex-wrap gap-1.5">
            <button v-for="months in [1, 2, 3]" :key="months" type="button" class="pressable inline-flex h-8 items-center rounded-full border border-line px-3 text-xs font-semibold text-muted hover:bg-highlight hover:text-fg" @click="probationIn(months)">
              {{ t("hr.contract.probationMonths", { n: months }, months) }}
            </button>
          </div>
        </FormField>
        <FormField :label="t('hr.field.weeklyHours')" :error="errors.weekly_hours" optional>
          <NumberInput v-model="form.weekly_hours" :min="1" :max="60" :decimals="1" :suffix="t('hr.contract.hoursUnit')" />
        </FormField>
      </div>

      <FormField :label="t('hr.field.number')" :hint="t('hr.contract.numberHint')" :error="errors.number" optional>
        <TextInput v-model="form.number" :maxlength="40" />
      </FormField>

      <FormField :label="t('hr.contract.paper')">
        <SegmentedControl
          v-model="form.source"
          block
          :options="[
            { value: 'template', label: t('hr.contract.fromTemplate'), icon: FileSignature },
            { value: 'scan', label: t('hr.contract.fromScan'), icon: ScanLine },
          ]"
        />
      </FormField>
      <FormField v-if="form.source === 'template'" :label="t('hr.field.template')" :hint="templateOptions.length ? t('hr.contract.templateHint') : t('hr.contract.noTemplates')" :error="errors.template">
        <SelectBox v-model="form.template" :options="templateOptions" :placeholder="t('hr.contract.templatePlaceholder')" clearable @update:model-value="pickedByHand = true" />
      </FormField>
      <FormField v-else :label="t('hr.contract.scan')" :error="errors.file" required>
        <FileDrop v-model="form.files" accept="application/pdf,image/*" :invalid="!!errors.file" :hint="t('hr.document.fileHint')" />
      </FormField>
    </form>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="primary" :icon="FilePlus2" :loading="save.isPending.value" @click="submit">{{ t("hr.contract.create") }}</UiButton>
    </template>
  </UiDialog>
</template>
