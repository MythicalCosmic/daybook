<script setup lang="ts">
/**
 * Settings › Company (plan §4.4): name and logo, language, timezone, base currency (locked once
 * money is booked), the work week, report times, the morning digest, the rejoin wait and the two
 * people switches. One form with a save bar; read-only for people without `company.settings`.
 */
import { CalendarClock, Image as ImageIcon, Lock, ShieldCheck, Trash2, Upload } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { z } from "zod";

import CompanyLogo from "@/components/CompanyLogo.vue";
import ErrorState from "@/components/ErrorState.vue";
import FormField from "@/components/FormField.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import NumberInput from "@/components/NumberInput.vue";
import PageSection from "@/components/PageSection.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SelectBox from "@/components/SelectBox.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StickyActionBar from "@/components/StickyActionBar.vue";
import TextInput from "@/components/TextInput.vue";
import TimePicker from "@/components/TimePicker.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import UiBadge from "@/components/UiBadge.vue";
import UiButton from "@/components/UiButton.vue";
import WeekdayPicker from "@/components/WeekdayPicker.vue";
import { toast } from "@/components/useToast";
import { useCan } from "@/lib/usePermission";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { useForm } from "@/lib/useForm";

import { useLogo, useSaveSettings, useSettings } from "../api";
import PanelHeader from "../components/PanelHeader.vue";
import { timezoneOptions } from "../timezones";
import type { CompanySettings } from "../types";

const { t } = useI18n();
const settings = useSettings();
const save = useSaveSettings();
const logo = useLogo();
const canEdit = useCan("company.settings");
const showSkeleton = useDelayedPending(() => settings.isPending.value);

const schema = z
  .object({
    name: z.string().trim().min(1, "common.form.required").max(200, "common.form.tooLong"),
    timezone: z.string().min(1, "common.form.required"),
    default_language: z.enum(["uz", "ru", "en"]),
    base_currency: z.enum(["UZS", "USD"]),
    workdays: z.array(z.number().int().min(0).max(6)).min(1, "settings.company.workdaysRequired"),
    morning_report_at: z.string().regex(/^\d{2}:\d{2}$/, "common.form.required"),
    evening_report_at: z.string().regex(/^\d{2}:\d{2}$/, "common.form.required"),
    morning_digest: z.boolean(),
    rejoin_cooldown_hours: z.number({ message: "common.form.number" }).int().min(0).max(720),
    owner_sees_personal_tasks: z.boolean(),
    team_directory_phones: z.boolean(),
  })
  .refine((v) => v.morning_report_at !== v.evening_report_at, { path: ["evening_report_at"], message: "settings.company.sameTimes" });

type Values = z.input<typeof schema>;

function valuesOf(data: CompanySettings | undefined): Values {
  return {
    name: data?.name ?? "",
    timezone: data?.timezone ?? "Asia/Tashkent",
    default_language: data?.default_language ?? "uz",
    base_currency: data?.base_currency ?? "UZS",
    workdays: [...(data?.workdays ?? [0, 1, 2, 3, 4, 5])],
    morning_report_at: data?.morning_report_at ?? "09:00",
    evening_report_at: data?.evening_report_at ?? "20:00",
    morning_digest: data?.morning_digest ?? true,
    rejoin_cooldown_hours: data?.rejoin_cooldown_hours ?? 24,
    owner_sees_personal_tasks: data?.owner_sees_personal_tasks ?? true,
    team_directory_phones: data?.team_directory_phones ?? true,
  };
}

const form = useForm(schema, valuesOf(undefined), {
  onSubmit: async (values) => {
    const data = await save.mutateAsync({ ...values, rejoin_cooldown_hours: values.rejoin_cooldown_hours });
    form.reset(valuesOf(data));
    toast.success(t("settings.company.saved"));
  },
});

watch(
  () => settings.data.value,
  (data) => data && !form.dirty.value && form.reset(valuesOf(data)),
  { immediate: true },
);

const locked = computed(() => settings.data.value?.base_currency_locked ?? false);
const zones = computed(() => timezoneOptions(form.values.timezone, t));
const languages = [
  { value: "uz" as const, label: "O‘zbekcha" },
  { value: "ru" as const, label: "Русский" },
  { value: "en" as const, label: "English" },
];
const currencies = computed(() => [
  { value: "UZS" as const, label: t("settings.company.uzs") },
  { value: "USD" as const, label: t("settings.company.usd") },
]);

const fileInput = ref<HTMLInputElement | null>(null);
async function pickLogo(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = "";
  if (!file) return;
  if (file.size > 10 * 1024 * 1024) {
    toast.error(t("settings.company.logoTooBig"));
    return;
  }
  await logo.mutateAsync(file);
  toast.success(t("settings.company.logoSaved"));
}
async function dropLogo(): Promise<void> {
  await logo.mutateAsync(null);
  toast.success(t("settings.company.logoRemoved"));
}
</script>

<template>
  <div>
    <PanelHeader :title="t('settings.panel.company')" :description="t('settings.company.description')" />

    <ErrorState v-if="settings.isError.value" :error="settings.error.value" :retry="() => settings.refetch()" :retrying="settings.isFetching.value" />

    <div v-else-if="showSkeleton || !settings.data.value" class="flex flex-col gap-6" aria-busy="true">
      <div v-for="n in 3" :key="n" class="ui-card flex flex-col gap-4 p-5">
        <SkeletonBlock width="30%" height="16px" />
        <SkeletonBlock height="36px" />
        <SkeletonBlock width="70%" height="36px" />
      </div>
    </div>

    <form v-else class="flex flex-col gap-7" novalidate @submit="form.submit">
      <InlineAlert v-if="!canEdit" tone="info" :icon="Lock" :title="t('settings.readOnly.title')" :description="t('settings.readOnly.body')" />

      <!-- Identity -->
      <PageSection variant="card" :title="t('settings.company.identity')" :description="t('settings.company.identityHint')">
        <div class="flex flex-col gap-5">
          <div class="flex flex-wrap items-center gap-4">
            <CompanyLogo :name="form.values.name || settings.data.value.name" :src="settings.data.value.logo" :size="64" />
            <div class="flex min-w-[12rem] flex-1 flex-col gap-1">
              <p class="text-base font-medium text-fg">{{ t("settings.company.logo") }}</p>
              <p class="text-sm text-muted">{{ t("settings.company.logoHint") }}</p>
            </div>
            <div v-if="canEdit" class="flex flex-wrap gap-2">
              <input ref="fileInput" type="file" accept="image/png,image/jpeg,image/webp,image/heic" class="hidden" @change="pickLogo" />
              <UiButton :icon="settings.data.value.logo ? ImageIcon : Upload" :loading="logo.isPending.value" @click="fileInput?.click()">
                {{ settings.data.value.logo ? t("settings.company.changeLogo") : t("settings.company.uploadLogo") }}
              </UiButton>
              <UiButton v-if="settings.data.value.logo" variant="ghost" :icon="Trash2" :disabled="logo.isPending.value" @click="dropLogo">{{ t("settings.company.removeLogo") }}</UiButton>
            </div>
          </div>

          <div class="grid gap-4 md:grid-cols-2">
            <FormField :label="t('settings.company.name')" :error="form.errors.name" required>
              <TextInput v-model="form.values.name" :maxlength="200" :disabled="!canEdit" @blur="form.touch('name')" />
            </FormField>
            <FormField :label="t('settings.company.timezone')" :hint="t('settings.company.timezoneHint')" :error="form.errors.timezone">
              <SelectBox v-model="form.values.timezone" :options="zones" :disabled="!canEdit" />
            </FormField>
          </div>

          <div class="grid gap-4 md:grid-cols-2">
            <FormField :label="t('settings.company.language')" :hint="t('settings.company.languageHint')">
              <SegmentedControl v-model="form.values.default_language" :options="languages" :disabled="!canEdit" block :aria-label="t('settings.company.language')" />
            </FormField>
            <FormField :label="t('settings.company.currency')" :hint="locked ? t('settings.company.currencyLocked') : t('settings.company.currencyHint')">
              <div class="flex items-center gap-2">
                <SegmentedControl v-model="form.values.base_currency" :options="currencies" :disabled="!canEdit || locked" block class="flex-1" :aria-label="t('settings.company.currency')" />
                <UiBadge v-if="locked" tone="neutral"><Lock :size="12" class="mr-1 inline" />{{ t("settings.company.locked") }}</UiBadge>
              </div>
            </FormField>
          </div>
        </div>
      </PageSection>

      <!-- Work week and reports -->
      <PageSection variant="card" :title="t('settings.company.week')" :description="t('settings.company.weekHint')">
        <div class="flex flex-col gap-5">
          <FormField :label="t('settings.company.workdays')" :hint="t('settings.company.workdaysHint')" :error="form.errors.workdays">
            <WeekdayPicker v-model="form.values.workdays" presets :disabled="!canEdit" />
          </FormField>
          <div class="grid gap-4 sm:grid-cols-2">
            <FormField :label="t('settings.company.morning')" :hint="t('settings.company.morningHint')" :error="form.errors.morning_report_at">
              <TimePicker v-model="form.values.morning_report_at" :step="15" :disabled="!canEdit" />
            </FormField>
            <FormField :label="t('settings.company.evening')" :hint="t('settings.company.eveningHint')" :error="form.errors.evening_report_at">
              <TimePicker v-model="form.values.evening_report_at" :step="15" :disabled="!canEdit" />
            </FormField>
          </div>
          <div class="border-t border-line pt-4">
            <ToggleSwitch v-model="form.values.morning_digest" layout="row" :disabled="!canEdit" :label="t('settings.company.digest')" :description="t('settings.company.digestHint')" />
          </div>
        </div>
      </PageSection>

      <!-- People -->
      <PageSection variant="card" :title="t('settings.company.people')" :description="t('settings.company.peopleHint')">
        <div class="flex flex-col divide-y divide-line">
          <div class="pb-4">
            <ToggleSwitch
              v-model="form.values.owner_sees_personal_tasks"
              layout="row"
              :disabled="!canEdit"
              :label="t('settings.company.personalTasks')"
              :description="t('settings.company.personalTasksHint')"
            />
          </div>
          <div class="py-4">
            <ToggleSwitch
              v-model="form.values.team_directory_phones"
              layout="row"
              :disabled="!canEdit"
              :label="t('settings.company.phones')"
              :description="t('settings.company.phonesHint')"
            />
          </div>
          <div class="flex flex-wrap items-start justify-between gap-3 pt-4">
            <span class="min-w-0 flex-1 basis-[16rem]">
              <span class="block text-base font-medium text-fg">{{ t("settings.company.cooldown") }}</span>
              <span class="mt-0.5 block text-sm text-muted">{{ t("settings.company.cooldownHint") }}</span>
            </span>
            <NumberInput
              v-model="form.values.rejoin_cooldown_hours"
              :min="0"
              :max="720"
              :suffix="t('settings.company.hours')"
              :disabled="!canEdit"
              class="w-[150px]"
              :invalid="!!form.errors.rejoin_cooldown_hours"
            />
          </div>
        </div>
      </PageSection>

      <p class="flex flex-wrap items-center gap-x-5 gap-y-1.5 text-sm text-muted">
        <span class="inline-flex items-center gap-2"><ShieldCheck :size="15" class="shrink-0 text-success" />{{ t("settings.company.audited") }}</span>
        <span class="inline-flex items-center gap-2"><CalendarClock :size="15" class="shrink-0 text-subtle" />{{ t("settings.company.timesLocal", { zone: form.values.timezone }) }}</span>
      </p>

      <StickyActionBar v-if="canEdit" :show="form.dirty.value" :message="form.formError.value ?? t('common.unsaved')" :tone="form.formError.value ? 'warning' : 'neutral'">
        <UiButton variant="ghost" :disabled="form.submitting.value" @click="form.reset()">{{ t("common.discard") }}</UiButton>
        <UiButton variant="primary" type="submit" :loading="form.submitting.value">{{ t("common.save") }}</UiButton>
      </StickyActionBar>
    </form>
  </div>
</template>
