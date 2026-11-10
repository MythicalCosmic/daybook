<script setup lang="ts">
/**
 * Propose a job change: for whom, from which day, what changes (a new position, the branch they
 * move to, a department, a new pay) and why. Someone who may decide it can approve it in the same
 * step; otherwise it waits in Needs you. Their job today is shown beside each part (the pay only
 * for payroll.view, and the pay part only for payroll.manage).
 */
import { Banknote, Briefcase, MapPin, Network, Send, UserRoundCheck } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import BranchPicker from "@/components/BranchPicker.vue";
import CheckBox from "@/components/CheckBox.vue";
import DatePicker from "@/components/DatePicker.vue";
import FormField from "@/components/FormField.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import MoneyInput from "@/components/MoneyInput.vue";
import MoneyText from "@/components/MoneyText.vue";
import PersonPicker from "@/components/PersonPicker.vue";
import PositionPicker from "@/components/PositionPicker.vue";
import SelectBox from "@/components/SelectBox.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import TextArea from "@/components/TextArea.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore, useCompanyToday } from "@/stores/company";

import { lifecycleApi, useCurrentJob, useLifecycleMutation } from "../api";
import { changeFormErrors, changePayload, suggestedChangeDay, type ChangeForm, type ChangeFormErrors } from "../lib";
import { PAY_TYPES, type ChangeInput, type ChangePart, type JobChange } from "../types";

const open = defineModel<boolean>("open", { default: false });
/** `preset`: what a move on the org chart starts with (the parts ticked, the new department or branch, a reason). */
export interface ChangePreset {
  parts: ChangePart[];
  department?: number | null;
  branch?: number | null;
  reason?: string;
}
const props = withDefaults(defineProps<{ member?: { id: number; name: string } | null; preset?: ChangePreset | null }>(), { member: null, preset: null });
const emit = defineEmits<{ saved: [change: JobChange] }>();

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const today = useCompanyToday();

const blank = (): ChangeForm => ({
  member: props.member?.id ?? null,
  effective_on: suggestedChangeDay(today.value),
  parts: [...(props.preset?.parts ?? [])],
  position: null,
  branch: null,
  department: null,
  pay_amount: null,
  pay_type: null,
  reason: props.preset?.reason ?? "",
  approve: true,
});
const form = ref<ChangeForm>(blank());
const errors = ref<ChangeFormErrors>({});
watch(
  open,
  (isOpen) => {
    if (!isOpen) return;
    form.value = blank();
    errors.value = {};
  },
  { immediate: true },
);

const current = useCurrentJob(computed(() => (open.value ? form.value.member : null)));
const job = computed(() => current.data.value ?? null);
const title = computed(() => {
  const name = props.member?.name || (props.member ? job.value?.member.name : "");
  return name ? t("lifecycle.propose.titleFor", { name }) : t("lifecycle.propose.title");
});
// A new person: start from their job today (and from what a move on the org chart set).
function startFrom(value: NonNullable<typeof job.value>): void {
  form.value.position = value.position?.id ?? null;
  form.value.branch = value.home_branch?.id ?? null;
  form.value.department = value.department?.id ?? null;
  form.value.pay_type = value.pay?.pay_type ?? "monthly";
  const preset = props.preset;
  if (preset?.department !== undefined) form.value.department = preset.department;
  if (preset?.branch !== undefined && preset.branch !== null) form.value.branch = preset.branch;
}
watch(job, (value) => value && startFrom(value));
watch(open, (isOpen) => isOpen && job.value && startFrom(job.value));

const PART_ICONS = { position: Briefcase, branch: MapPin, department: Network, pay: Banknote } as const;
const parts = computed<ChangePart[]>(() => (job.value?.may_change_pay ? ["position", "branch", "department", "pay"] : ["position", "branch", "department"]));
const nowText = computed<Record<ChangePart, string>>(() => {
  const value = job.value;
  return {
    position: value?.position?.name ?? t("lifecycle.changes.noPosition"),
    branch: value?.home_branch?.name ?? "—",
    department: value?.department?.name ?? t("lifecycle.changes.noDepartment"),
    pay: "",
  };
});
function toggle(part: ChangePart, on: boolean): void {
  const set = new Set(form.value.parts);
  if (on) set.add(part);
  else set.delete(part);
  form.value.parts = (["position", "branch", "department", "pay"] as const).filter((each) => set.has(each));
}

const NONE = 0;
const departments = computed(() => [{ value: NONE, label: t("lifecycle.changes.noDepartment") }, ...(job.value?.departments ?? []).map((d) => ({ value: d.id, label: d.name }))]);
const department = computed<number>({
  get: () => form.value.department ?? NONE,
  set: (value) => (form.value.department = value === NONE ? null : value),
});
const payTypes = computed(() => PAY_TYPES.map((value) => ({ value, label: t(`lifecycle.payTypeOption.${value}`) })));

/** Who may decide it can approve it now: hr.manage, members.manage for the job, payroll.manage for pay. */
const mayDecide = computed(() => {
  if (!company.can("hr.manage")) return false;
  const job = form.value.parts.some((part) => part !== "pay");
  if (job && !company.can("members.manage")) return false;
  if (form.value.parts.includes("pay") && !company.can("payroll.manage")) return false;
  return true;
});
/** Approving in the same step: once something changes and the viewer may decide it. */
const approving = computed(() => form.value.approve && mayDecide.value && form.value.parts.length > 0);
const overlap = computed(() => (job.value?.open_changes ?? []).find((other) => other.parts.some((part) => form.value.parts.includes(part))) ?? null);

const message = (key: string | undefined) => (key ? t(`lifecycle.propose.error.${key}`) : null);
const save = useLifecycleMutation((cid, input: ChangeInput) => lifecycleApi.proposeChange(cid, input));

async function submit(): Promise<void> {
  errors.value = changeFormErrors(form.value, today.value);
  if (Object.keys(errors.value).length) return;
  try {
    const saved = await save.mutateAsync(changePayload({ ...form.value, approve: approving.value }));
    const key = saved.status === "applied" ? "lifecycle.changes.appliedNow" : saved.status === "approved" ? "lifecycle.changes.approved" : "lifecycle.propose.done";
    toast.success(t(key, { name: saved.member.name }));
    emit("saved", saved);
    open.value = false;
  } catch {
    // The HTTP layer showed the server's reason (nothing changes, a change already waits).
  }
}
</script>

<template>
  <UiDialog v-model:open="open" size="md" :title="title" :description="t('lifecycle.propose.description')">
    <div class="flex flex-col gap-4">
      <FormField v-if="!member" :label="t('lifecycle.field.person')" :error="message(errors.member)" required>
        <PersonPicker v-model="form.member" :invalid="!!errors.member" />
      </FormField>
      <FormField :label="t('lifecycle.propose.effectiveOn')" :hint="t('lifecycle.propose.effectiveHint')" :error="message(errors.effective_on)" required>
        <DatePicker v-model="form.effective_on" :min="today" format="weekday" :invalid="!!errors.effective_on" />
      </FormField>

      <p v-if="!form.member" class="rounded-[12px] border border-dashed border-line-strong px-4 py-3 text-sm text-muted" data-propose-pick-person>
        {{ t("lifecycle.propose.pickPerson") }}
      </p>
      <div v-else-if="current.isPending.value" class="flex flex-col gap-2">
        <SkeletonBlock v-for="n in 3" :key="n" height="44px" radius="12px" />
      </div>
      <FormField v-else-if="job" :label="t('lifecycle.propose.what')" :error="message(errors.parts)" required>
        <ul class="flex flex-col gap-2" data-propose-parts>
          <li v-for="part in parts" :key="part" :class="['rounded-[12px] border px-3.5 py-3 transition-colors', form.parts.includes(part) ? 'border-[var(--c-primary)] bg-primary-soft/30' : 'border-line']">
            <div class="flex items-center gap-3">
              <CheckBox :model-value="form.parts.includes(part)" :aria-label="t(`lifecycle.propose.part.${part}`)" @update:model-value="(on: boolean) => toggle(part, on)" />
              <component :is="PART_ICONS[part]" :size="16" class="shrink-0 text-muted" aria-hidden="true" />
              <button type="button" class="min-w-0 flex-1 text-left" @click="toggle(part, !form.parts.includes(part))">
                <span class="block text-sm font-medium text-fg">{{ t(`lifecycle.propose.part.${part}`) }}</span>
                <span class="block truncate text-xs text-muted">
                  <template v-if="part === 'pay'">
                    <template v-if="job.pay">{{ t("lifecycle.propose.nowLabel") }} <MoneyText :value="job.pay.amount" :currency="job.pay.currency" /> · {{ t(`lifecycle.payType.${job.pay.pay_type}`) }}</template>
                    <template v-else>{{ t("lifecycle.propose.noPay") }}</template>
                  </template>
                  <template v-else>{{ t("lifecycle.propose.now", { value: nowText[part] }) }}</template>
                </span>
              </button>
            </div>
            <div v-if="form.parts.includes(part)" class="mt-3 pl-8">
              <template v-if="part === 'position'">
                <PositionPicker v-model="form.position" :clearable="false" :invalid="!!errors.position" />
                <p v-if="errors.position" class="mt-1 text-xs text-danger">{{ message(errors.position) }}</p>
              </template>
              <template v-else-if="part === 'branch'">
                <BranchPicker v-model="form.branch" :clearable="false" :invalid="!!errors.branch" />
                <p class="mt-1 text-xs text-subtle">{{ t("lifecycle.propose.branchHint") }}</p>
              </template>
              <SelectBox v-else-if="part === 'department'" v-model="department" :options="departments" />
              <div v-else class="grid gap-2 sm:grid-cols-[1fr_auto]">
                <MoneyInput v-model="form.pay_amount" :currencies="[job.pay?.currency ?? company.currency]" :invalid="!!errors.pay_amount" />
                <SelectBox v-model="form.pay_type" :options="payTypes" />
              </div>
              <p v-if="part === 'pay' && errors.pay_amount" class="mt-1 text-xs text-danger">{{ message(errors.pay_amount) }}</p>
            </div>
          </li>
        </ul>
      </FormField>

      <InlineAlert v-if="overlap" tone="warning" size="sm" :description="t('lifecycle.propose.overlap', { date: fmt.day(overlap.effective_on, 'medium') })" />

      <FormField :label="t('lifecycle.propose.reason')" :error="message(errors.reason)" required>
        <TextArea v-model="form.reason" :rows="3" :maxlength="1000" :placeholder="t('lifecycle.propose.reasonPlaceholder')" :invalid="!!errors.reason" />
      </FormField>

      <CheckBox v-if="mayDecide && form.parts.length" v-model="form.approve" :label="t('lifecycle.propose.approve')" :description="t('lifecycle.propose.approveHint')" />
      <p v-else-if="form.parts.length" class="text-xs text-muted">{{ t("lifecycle.propose.waits") }}</p>
    </div>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="primary" :icon="approving ? UserRoundCheck : Send" :loading="save.isPending.value" @click="submit">
        {{ approving ? t("lifecycle.propose.submitApprove") : t("lifecycle.propose.submit") }}
      </UiButton>
    </template>
  </UiDialog>
</template>
