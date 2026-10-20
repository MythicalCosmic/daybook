<script setup lang="ts">
/**
 * The body of the switcher's "New company" dialog (`shell.company.create`, plan §13.2): name,
 * timezone, language and currency, a signup code when the server asks for one, and optionally
 * the setup to copy from another of your companies (people, money and history never travel).
 * On success it reloads `me`, opens the new company's "Get started" and closes the dialog.
 */
import { Building2, Copy, KeyRound, Lock } from "@lucide/vue";
import { computed, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";
import { z } from "zod";

import CheckBox from "@/components/CheckBox.vue";
import ErrorState from "@/components/ErrorState.vue";
import FormField from "@/components/FormField.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SelectBox from "@/components/SelectBox.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import TextInput from "@/components/TextInput.vue";
import UiButton from "@/components/UiButton.vue";
import { toast } from "@/components/useToast";
import { useForm } from "@/lib/useForm";
import { useSessionStore } from "@/stores/session";

import { createCompany, useNewCompanyInfo } from "../api";
import { zoneOptions } from "../zones";

const props = withDefaults(defineProps<{ context?: { close?: () => void } }>(), { context: () => ({}) });

const { t, locale } = useI18n();
const router = useRouter();
const session = useSessionStore();
const info = useNewCompanyInfo();

const schema = z.object({
  name: z.string().trim().min(1, "common.form.required").max(200, "common.form.tooLong"),
  timezone: z.string().min(1),
  language: z.enum(["uz", "ru", "en"]),
  base_currency: z.enum(["UZS", "USD"]),
  signup_code: z.string().trim(),
  copy_from: z.number().nullable(),
  parts: z.array(z.string()),
});

const form = useForm(
  schema,
  {
    name: "",
    timezone: "Asia/Tashkent",
    language: (locale.value === "ru" || locale.value === "en" ? locale.value : "uz") as "uz" | "ru" | "en",
    base_currency: "UZS" as "UZS" | "USD",
    signup_code: "",
    copy_from: null as number | null,
    parts: [] as string[],
  },
  {
    onSubmit: async (values) => {
      if (info.data.value?.needs_code && !values.signup_code) {
        form.setErrors({ signup_code: t("setup.new.codeRequired") });
        throw new Error("code");
      }
      const created = await createCompany({
        name: values.name,
        timezone: values.timezone,
        language: values.language,
        base_currency: values.base_currency,
        signup_code: values.signup_code || undefined,
        copy_from: values.copy_from,
        parts: values.copy_from ? values.parts : [],
      });
      await session.loadMe();
      props.context.close?.();
      toast.success(t("setup.new.created", { name: created.name }), { description: t("setup.new.createdHint") });
      await router.push(`/c/${created.id}/get-started`);
    },
  },
);

const zones = computed(() => zoneOptions(t));
const languages = [
  { value: "uz" as const, label: "O‘zbekcha" },
  { value: "ru" as const, label: "Русский" },
  { value: "en" as const, label: "English" },
];
const currencies = computed(() => [
  { value: "UZS" as const, label: t("setup.new.uzs") },
  { value: "USD" as const, label: t("setup.new.usd") },
]);
const sources = computed(() => [
  { value: 0, label: t("setup.new.fresh") },
  ...(info.data.value?.sources ?? []).map((s) => ({ value: s.id, label: s.name })),
]);
const sourceChoice = computed({
  get: () => form.values.copy_from ?? 0,
  set: (value: number | null) => (form.values.copy_from = value ? value : null),
});
const partLabels = computed(() => new Map((info.data.value?.parts ?? []).map((p) => [p.key, p.label])));
const available = computed(() => info.data.value?.sources.find((s) => s.id === form.values.copy_from)?.parts ?? []);

// Picking a company to copy from ticks everything it offers; untick what you don't want.
watch(
  () => form.values.copy_from,
  () => (form.values.parts = [...available.value]),
);

function togglePart(key: string, on: boolean): void {
  form.values.parts = on ? [...new Set([...form.values.parts, key])] : form.values.parts.filter((p) => p !== key);
}

async function submit(event?: Event): Promise<void> {
  try {
    await form.submit(event);
  } catch {
    // Missing code: the field shows why.
  }
}
</script>

<template>
  <ErrorState v-if="info.isError.value" compact :error="info.error.value" :retry="() => info.refetch()" />
  <div v-else-if="!info.data.value" class="flex flex-col gap-4" aria-busy="true">
    <SkeletonBlock height="56px" /><SkeletonBlock height="56px" /><SkeletonBlock height="36px" width="40%" />
  </div>
  <div v-else-if="!info.data.value.allowed" class="flex flex-col gap-4">
    <InlineAlert tone="neutral" :icon="Lock" :title="t('setup.new.notAllowed')" :description="info.data.value.reason" />
    <div class="flex justify-end"><UiButton @click="props.context.close?.()">{{ t("common.close") }}</UiButton></div>
  </div>
  <form v-else class="flex flex-col gap-4" novalidate @submit="submit">
    <FormField :label="t('setup.new.name')" :error="form.errors.name" required>
      <TextInput v-model="form.values.name" :icon="Building2" :maxlength="200" autofocus :placeholder="t('setup.new.namePlaceholder')" @blur="form.touch('name')" />
    </FormField>

    <div class="grid gap-4 sm:grid-cols-2">
      <FormField :label="t('setup.new.timezone')">
        <SelectBox v-model="form.values.timezone" :options="zones" />
      </FormField>
      <FormField :label="t('setup.new.currency')" :hint="t('setup.new.currencyHint')">
        <SegmentedControl v-model="form.values.base_currency" :options="currencies" block :aria-label="t('setup.new.currency')" />
      </FormField>
    </div>

    <FormField :label="t('setup.new.language')" :hint="t('setup.new.languageHint')">
      <SegmentedControl v-model="form.values.language" :options="languages" block :aria-label="t('setup.new.language')" />
    </FormField>

    <FormField v-if="info.data.value.needs_code" :label="t('setup.new.code')" :hint="t('setup.new.codeHint')" :error="form.errors.signup_code" required>
      <TextInput v-model="form.values.signup_code" :icon="KeyRound" mono :maxlength="32" placeholder="K7M2-QX9P" autocomplete="off" />
    </FormField>

    <div v-if="info.data.value.sources.length" class="rounded-[12px] border border-line bg-surface-2 p-3.5">
      <FormField :label="t('setup.new.copyFrom')" :hint="t('setup.new.copyHint')">
        <SelectBox v-model="sourceChoice" :options="sources" />
      </FormField>
      <div v-if="form.values.copy_from && available.length" class="mt-3 flex flex-col gap-2">
        <CheckBox
          v-for="key in available"
          :key="key"
          :model-value="form.values.parts.includes(key)"
          :label="partLabels.get(key) ?? key"
          @update:model-value="(on: boolean) => togglePart(key, on)"
        />
      </div>
      <p v-else-if="form.values.copy_from" class="mt-2 text-sm text-muted">{{ t("setup.new.nothingToCopy") }}</p>
    </div>

    <p v-if="info.data.value.limit !== null" class="text-xs text-muted">{{ t("setup.new.limit", { owned: info.data.value.owned, limit: info.data.value.limit }) }}</p>
    <p v-if="form.formError.value" class="rounded-[8px] bg-danger-soft px-3 py-2 text-sm text-danger">{{ form.formError.value }}</p>

    <div class="mt-1 flex justify-end gap-2">
      <UiButton variant="ghost" @click="props.context.close?.()">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="primary" type="submit" :icon="form.values.copy_from ? Copy : undefined" :loading="form.submitting.value">{{ t("setup.new.create") }}</UiButton>
    </div>
  </form>
</template>
