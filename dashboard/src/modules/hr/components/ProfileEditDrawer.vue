<script setup lang="ts">
/**
 * Edit someone's HR profile: work details, personal details, IDs and how they are paid. The ID
 * fields start empty (the stored numbers stay masked): typing one replaces it, leaving it empty
 * keeps it. Only what changed is sent; the server checks and audits it.
 */
import { LockKeyhole } from "@lucide/vue";
import { computed, reactive, watch } from "vue";
import { useI18n } from "vue-i18n";

import { isApiError, unshownFieldError } from "@/api/http";
import DatePicker from "@/components/DatePicker.vue";
import FormField from "@/components/FormField.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SelectBox from "@/components/SelectBox.vue";
import TextArea from "@/components/TextArea.vue";
import TextInput from "@/components/TextInput.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import UiButton from "@/components/UiButton.vue";
import UiDrawer from "@/components/UiDrawer.vue";
import { toast } from "@/components/useToast";
import { useCompanyToday } from "@/stores/company";

import { hrApi, useHrMutation } from "../api";
import { cleanIds } from "../lib";
import type { EmploymentType, Gender, HrProfile, PayoutMethod, ProfileInput } from "../types";

const open = defineModel<boolean>("open", { default: false });
const props = defineProps<{ profile: HrProfile }>();

const { t } = useI18n();
const today = useCompanyToday();

type Draft = Required<Omit<ProfileInput, "pinfl" | "passport" | "payout_card" | "tin">> & { pinfl: string; passport: string; payout_card: string; tin: string };
const form = reactive<Draft>({} as Draft);
const errors = reactive<Record<string, string | undefined>>({});

function fromProfile(p: HrProfile): Draft {
  return {
    employee_number: p.employee_number,
    middle_name: p.middle_name,
    birth_date: p.birth_date,
    show_birthday: p.show_birthday,
    gender: p.gender,
    hire_date: p.hire_date,
    employment_type: p.employment_type,
    personal_phone: p.personal_phone,
    email: p.email,
    address: p.address,
    city: p.city,
    payout_method: p.payout_method,
    notes: p.notes ?? "",
    pinfl: "",
    passport: "",
    payout_card: "",
    tin: p.tin,
  };
}

watch(
  open,
  (isOpen) => {
    if (!isOpen) return;
    for (const key of Object.keys(errors)) delete errors[key];
    Object.assign(form, fromProfile(props.profile));
  },
  { immediate: true },
);

const typeOptions = computed(() => (["full_time", "part_time", "contractor", "intern"] as EmploymentType[]).map((value) => ({ value, label: t(`hr.employmentType.${value}`) })));
const genderOptions = computed(() => [
  { value: "female" as Gender, label: t("hr.gender.female") },
  { value: "male" as Gender, label: t("hr.gender.male") },
  { value: "" as Gender, label: t("hr.gender.unset") },
]);
const payoutOptions = computed(() => (["cash", "card", "bank"] as PayoutMethod[]).map((value) => ({ value, label: t(`hr.payout.${value}`) })));

const save = useHrMutation((cid, body: ProfileInput) => hrApi.updateProfile(cid, props.profile.member.id, body));

async function submit(): Promise<void> {
  for (const key of Object.keys(errors)) delete errors[key];
  const ids = cleanIds({ pinfl: form.pinfl, passport: form.passport, payout_card: form.payout_card, tin: form.tin });
  for (const field of ids.errors) errors[field] = t(`hr.profile.invalid.${field}`);
  if (form.email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email.trim())) errors.email = t("hr.profile.invalid.email");
  if (Object.values(errors).some(Boolean)) return;

  const base = fromProfile(props.profile);
  const changes: ProfileInput = {};
  for (const key of Object.keys(form) as Array<keyof Draft>) {
    if (key === "pinfl" || key === "passport" || key === "payout_card" || key === "tin") continue;
    const value = typeof form[key] === "string" ? (form[key] as string).trim() : form[key];
    if (value !== base[key]) (changes as Record<string, unknown>)[key] = value;
  }
  for (const [field, value] of Object.entries(ids.values)) if (field !== "tin" || value !== props.profile.tin) (changes as Record<string, unknown>)[field] = value;
  if (!form.tin.trim() && props.profile.tin) changes.tin = "";
  if (!Object.keys(changes).length) {
    open.value = false;
    return;
  }
  try {
    await save.mutateAsync(changes);
    toast.success(t("hr.profile.saved"));
    open.value = false;
  } catch (failure) {
    if (isApiError(failure)) {
      for (const [field, messages] of Object.entries(failure.fieldErrors)) errors[field] = messages[0];
      const unshown = unshownFieldError(failure, Object.keys(form));
      if (unshown) toast.error(unshown);
    }
  }
}
</script>

<template>
  <UiDrawer v-model:open="open" size="lg" :title="t('hr.profile.editTitle', { name: profile.member.name })">
    <form class="flex flex-col gap-6 p-5" @submit.prevent="submit">
      <fieldset class="flex flex-col gap-4">
        <legend class="mb-3 text-sm font-semibold text-fg">{{ t("hr.profile.work") }}</legend>
        <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <FormField :label="t('hr.profile.employeeNumber')" :error="errors.employee_number" optional>
            <TextInput v-model="form.employee_number" :maxlength="20" mono />
          </FormField>
          <FormField :label="t('hr.profile.hireDate')" :error="errors.hire_date" optional>
            <DatePicker v-model="form.hire_date" :max="today" clearable />
          </FormField>
          <FormField :label="t('hr.profile.employmentType')" :error="errors.employment_type">
            <SelectBox v-model="form.employment_type" :options="typeOptions" />
          </FormField>
        </div>
      </fieldset>

      <fieldset class="flex flex-col gap-4">
        <legend class="mb-3 text-sm font-semibold text-fg">{{ t("hr.profile.personal") }}</legend>
        <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <FormField :label="t('hr.profile.middleName')" :error="errors.middle_name" optional>
            <TextInput v-model="form.middle_name" :maxlength="80" />
          </FormField>
          <FormField :label="t('hr.profile.birthDate')" :error="errors.birth_date" optional>
            <DatePicker v-model="form.birth_date" :max="today" clearable />
          </FormField>
          <FormField :label="t('hr.profile.gender')" class="sm:col-span-2">
            <SegmentedControl v-model="form.gender" :options="genderOptions" />
          </FormField>
          <FormField :label="t('hr.profile.personalPhone')" :error="errors.personal_phone" optional>
            <TextInput v-model="form.personal_phone" type="tel" inputmode="tel" :maxlength="20" />
          </FormField>
          <FormField :label="t('hr.profile.email')" :error="errors.email" optional>
            <TextInput v-model="form.email" type="email" inputmode="email" :maxlength="120" />
          </FormField>
          <FormField :label="t('hr.profile.addressLine')" :error="errors.address" optional>
            <TextInput v-model="form.address" :maxlength="200" />
          </FormField>
          <FormField :label="t('hr.profile.city')" :error="errors.city" optional>
            <TextInput v-model="form.city" :maxlength="80" />
          </FormField>
        </div>
        <ToggleSwitch v-model="form.show_birthday" layout="row" :label="t('hr.profile.showBirthday')" :description="t('hr.profile.showBirthdayHint')" />
      </fieldset>

      <fieldset class="flex flex-col gap-4">
        <legend class="mb-1 flex items-center gap-1.5 text-sm font-semibold text-fg"><LockKeyhole :size="14" class="text-subtle" aria-hidden="true" />{{ t("hr.profile.ids") }}</legend>
        <p class="-mt-1 mb-1 text-xs text-muted">{{ t("hr.profile.idsHint") }}</p>
        <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <FormField :label="t('hr.profile.id.pinfl')" :error="errors.pinfl" optional>
            <TextInput v-model="form.pinfl" mono inputmode="numeric" :maxlength="20" autocomplete="off" :placeholder="profile.pinfl || t('hr.profile.pinflPlaceholder')" :invalid="!!errors.pinfl" />
          </FormField>
          <FormField :label="t('hr.profile.id.passport')" :error="errors.passport" optional>
            <TextInput v-model="form.passport" mono :maxlength="12" autocomplete="off" :placeholder="profile.passport || 'AA1234567'" :invalid="!!errors.passport" />
          </FormField>
          <FormField :label="t('hr.profile.id.tin')" :error="errors.tin" optional>
            <TextInput v-model="form.tin" mono inputmode="numeric" :maxlength="12" autocomplete="off" :invalid="!!errors.tin" />
          </FormField>
        </div>
        <FormField :label="t('hr.profile.payoutMethod')">
          <SegmentedControl v-model="form.payout_method" :options="payoutOptions" />
        </FormField>
        <FormField v-if="form.payout_method === 'card'" :label="t('hr.profile.id.payout_card')" :error="errors.payout_card" optional>
          <TextInput v-model="form.payout_card" mono inputmode="numeric" :maxlength="23" autocomplete="off" :placeholder="profile.payout_card || '8600 •••• •••• ••••'" :invalid="!!errors.payout_card" />
        </FormField>
      </fieldset>

      <FormField :label="t('hr.profile.notes')" :hint="t('hr.profile.notesHint')" optional>
        <TextArea v-model="form.notes" :rows="3" :maxlength="4000" />
      </FormField>
    </form>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="primary" :loading="save.isPending.value" @click="submit">{{ t("common.save") }}</UiButton>
    </template>
  </UiDrawer>
</template>
