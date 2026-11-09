<script setup lang="ts">
/**
 * Settings › Organization: the name and logo everyone sees (the sign-in page, the sidebar, the
 * browser tab, reports and Telegram), the time zone that decides "today", lateness and reports,
 * and the language of Telegram messages and new users. One form with a save bar; the logo saves
 * on its own. Read-only without `company.settings`.
 */
import { Clock3, Image as ImageIcon, Lock, ScanFace, Trash2, Upload } from "@lucide/vue";
import { useQueryClient } from "@tanstack/vue-query";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { z } from "zod";

import { LANGUAGES, type Language } from "@/api/types";
import ComboBox from "@/components/ComboBox.vue";
import CompanyLogo from "@/components/CompanyLogo.vue";
import ErrorState from "@/components/ErrorState.vue";
import FormField from "@/components/FormField.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import PageSection from "@/components/PageSection.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StickyActionBar from "@/components/StickyActionBar.vue";
import TextInput from "@/components/TextInput.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import UiButton from "@/components/UiButton.vue";
import { toast } from "@/components/useToast";
import { editionInfo } from "@/core/edition";
import { useCan } from "@/lib/usePermission";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { useForm } from "@/lib/useForm";
import { useNow } from "@/lib/useNow";
import { useCompanyId } from "@/stores/company";
import { useSessionStore } from "@/stores/session";

import { davomatKeys, removeLogo, saveDavomatSettings, saveOrganization, uploadLogo, useBrandRefresh, useDavomatSettings, useOrganization } from "../api";
import { DEFAULT_ZONE, utcOffset, zoneOptions } from "../lib/zones";
import type { DavomatSettings, Organization } from "../types";

const { t, locale } = useI18n();
const cid = useCompanyId();
const client = useQueryClient();
const session = useSessionStore();
const brandRefresh = useBrandRefresh();
const canEdit = useCan("company.settings");
const now = useNow();

const organization = useOrganization();
// This install's own switches (`davomat/settings/`): optional, so an older server still shows the rest.
const extras = useDavomatSettings();
const skeleton = useDelayedPending(computed(() => organization.isPending.value));

const schema = z.object({
  name: z.string().trim().min(1, "common.form.required").max(200, "common.form.tooLong"),
  timezone: z.string().min(1, "common.form.required"),
  default_language: z.enum(["uz", "ru", "en"]),
  product_name: z.string().trim().max(60, "common.form.tooLong"),
  auto_create_employees: z.boolean(),
});
type Values = z.input<typeof schema>;

function valuesOf(data: Organization | undefined, more: DavomatSettings | undefined): Values {
  return {
    name: data?.name ?? "",
    timezone: data?.timezone ?? DEFAULT_ZONE,
    default_language: data?.default_language ?? "uz",
    product_name: more?.product_name ?? "",
    auto_create_employees: more?.auto_create_employees ?? true,
  };
}

/** After any change: the shell's `me` (name and logo in the sidebar) and the edition (sign-in page, tab). */
async function afterChange(data: Organization): Promise<void> {
  client.setQueryData(davomatKeys.organization(cid.value), data);
  await Promise.allSettled([session.loadMe(), brandRefresh()]);
}

const form = useForm(schema, valuesOf(undefined, undefined), {
  onSubmit: async (values) => {
    const data = await saveOrganization(cid.value, { name: values.name.trim(), timezone: values.timezone, default_language: values.default_language });
    let more = extras.data.value;
    if (more && (values.product_name.trim() !== more.product_name || values.auto_create_employees !== more.auto_create_employees)) {
      // An emptied name keeps the one in use (type "Davomat" to go back to it).
      more = await saveDavomatSettings(cid.value, { product_name: values.product_name.trim() || more.product_name, auto_create_employees: values.auto_create_employees });
      client.setQueryData(davomatKeys.settings(cid.value), more);
    }
    form.reset(valuesOf(data, more));
    toast.success(t("davomat.org.saved"));
    await afterChange(data);
  },
});

watch(
  () => [organization.data.value, extras.data.value] as const,
  ([data, more]) => data && !form.dirty.value && form.reset(valuesOf(data, more)),
  { immediate: true },
);

const zones = computed(() => zoneOptions(t, form.values.timezone));
const languages = computed(() => LANGUAGES.map((language: Language) => ({ value: language, label: t(`shell.language.${language}`) })));

const localTime = computed(() => {
  try {
    return new Intl.DateTimeFormat(locale.value === "en" ? "en-GB" : locale.value, {
      timeZone: form.values.timezone,
      hour: "2-digit",
      minute: "2-digit",
      weekday: "long",
      hour12: false,
    }).format(new Date(now.value));
  } catch {
    return "";
  }
});

// ─── The logo ─────────────────────────────────────────────────────────────────

const MAX_BYTES = 5 * 1024 * 1024;
const TYPES = ["image/png", "image/jpeg", "image/webp"];
const fileInput = ref<HTMLInputElement | null>(null);
const logoBusy = ref(false);
const logo = computed(() => organization.data.value?.logo ?? null);

async function pickLogo(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = "";
  if (!file) return;
  if (!TYPES.includes(file.type)) return void toast.error(t("davomat.org.logoType"));
  if (file.size > MAX_BYTES) return void toast.error(t("davomat.org.logoTooBig"));
  logoBusy.value = true;
  try {
    const data = await uploadLogo(cid.value, file);
    toast.success(t("davomat.org.logoSaved"));
    await afterChange(data);
  } finally {
    logoBusy.value = false;
  }
}

async function dropLogo(): Promise<void> {
  logoBusy.value = true;
  try {
    const data = await removeLogo(cid.value);
    toast.success(t("davomat.org.logoRemoved"));
    await afterChange(data);
  } finally {
    logoBusy.value = false;
  }
}

const previewName = computed(() => form.values.name.trim() || organization.data.value?.name || "");
const previewProduct = computed(() => form.values.product_name.trim() || editionInfo.value.product);
</script>

<template>
  <div data-organization>
    <ErrorState v-if="organization.isError.value" :error="organization.error.value" :retry="() => organization.refetch()" :retrying="organization.isFetching.value" />

    <div v-else-if="skeleton || !organization.data.value" class="flex flex-col gap-6" aria-busy="true">
      <div v-for="n in 2" :key="n" class="ui-card flex flex-col gap-4 p-5">
        <SkeletonBlock width="30%" height="16px" />
        <SkeletonBlock height="36px" />
        <SkeletonBlock width="70%" height="36px" />
      </div>
    </div>

    <form v-else class="flex flex-col gap-6" novalidate @submit="form.submit">
      <InlineAlert v-if="!canEdit" tone="info" :icon="Lock" :title="t('davomat.settings.readOnly.title')" :description="t('davomat.settings.readOnly.body')" />

      <!-- Name and logo, with how they look -->
      <PageSection variant="card" :title="t('davomat.org.identity')" :description="t('davomat.org.identityHint')">
        <div class="grid gap-6 lg:grid-cols-[minmax(0,1fr)_260px]">
          <div class="flex flex-col gap-5">
            <div class="flex flex-wrap items-center gap-4">
              <CompanyLogo :name="previewName || '·'" :src="logo" :size="64" />
              <div class="flex min-w-[12rem] flex-1 flex-col gap-0.5">
                <p class="text-base font-medium text-fg">{{ t("davomat.org.logo") }}</p>
                <p class="text-sm text-muted">{{ t("davomat.org.logoHint") }}</p>
              </div>
              <div v-if="canEdit" class="flex flex-wrap gap-2">
                <input ref="fileInput" type="file" accept="image/png,image/jpeg,image/webp" class="hidden" data-logo-input @change="pickLogo" />
                <UiButton :icon="logo ? ImageIcon : Upload" :loading="logoBusy" data-logo-upload @click="fileInput?.click()">
                  {{ logo ? t("davomat.org.changeLogo") : t("davomat.org.uploadLogo") }}
                </UiButton>
                <UiButton v-if="logo" variant="ghost" :icon="Trash2" :disabled="logoBusy" data-logo-remove @click="dropLogo">{{ t("davomat.org.removeLogo") }}</UiButton>
              </div>
            </div>
            <FormField :label="t('davomat.org.name')" :hint="t('davomat.org.nameHint')" :error="form.errors.name" required>
              <TextInput v-model="form.values.name" :maxlength="200" :disabled="!canEdit" data-field="name" @blur="form.touch('name')" />
            </FormField>
            <FormField v-if="extras.data.value" :label="t('davomat.org.productName')" :hint="t('davomat.org.productNameHint')" :error="form.errors.product_name">
              <TextInput v-model="form.values.product_name" :maxlength="60" :placeholder="editionInfo.product" :disabled="!canEdit" data-field="product_name" @blur="form.touch('product_name')" />
            </FormField>
          </div>

          <!-- The sign-in page's brand, as it will read -->
          <figure class="flex flex-col gap-2" aria-hidden="true">
            <figcaption class="text-xs font-medium text-subtle">{{ t("davomat.org.preview") }}</figcaption>
            <div class="org-preview relative flex flex-1 flex-col items-center justify-center gap-3 overflow-hidden rounded-[14px] border border-line px-5 py-7 text-center">
              <CompanyLogo :name="previewName || '·'" :src="logo" :size="48" />
              <div class="min-w-0">
                <p class="truncate text-md font-semibold text-fg">{{ previewName }}</p>
                <p class="mt-0.5 text-xs text-muted">{{ previewProduct }}</p>
              </div>
              <span class="mt-1 h-8 w-full max-w-[180px] rounded-[8px] bg-primary/90" />
            </div>
          </figure>
        </div>
      </PageSection>

      <!-- Time and language -->
      <PageSection variant="card" :title="t('davomat.org.region')" :description="t('davomat.org.regionHint')">
        <div class="grid gap-5 md:grid-cols-2">
          <FormField :label="t('davomat.org.timezone')" :hint="t('davomat.org.timezoneHint')" :error="form.errors.timezone">
            <ComboBox v-model="form.values.timezone" :options="zones" :search-placeholder="t('davomat.tz.search')" :disabled="!canEdit" />
          </FormField>
          <FormField :label="t('davomat.org.language')" :hint="t('davomat.org.languageHint')">
            <SegmentedControl v-model="form.values.default_language" :options="languages" :disabled="!canEdit" block :aria-label="t('davomat.org.language')" />
          </FormField>
        </div>
        <p v-if="localTime" class="mt-4 flex items-center gap-2 border-t border-line pt-4 text-sm text-muted" data-local-time>
          <Clock3 :size="15" class="shrink-0 text-subtle" />
          {{ t("davomat.org.localTime", { time: localTime, offset: utcOffset(form.values.timezone) }) }}
        </p>
      </PageSection>

      <!-- What a terminal does with a face nobody here has -->
      <PageSection v-if="extras.data.value" variant="card" :title="t('davomat.org.terminals')" :description="t('davomat.org.terminalsHint')">
        <div class="flex items-start gap-4">
          <span class="grid size-9 shrink-0 place-items-center rounded-[10px] bg-accent-soft text-accent-fg"><ScanFace :size="18" /></span>
          <ToggleSwitch
            v-model="form.values.auto_create_employees"
            class="min-w-0 flex-1"
            layout="row"
            :disabled="!canEdit"
            :label="t('davomat.org.autoCreate')"
            :description="t('davomat.org.autoCreateHint')"
            data-field="auto_create_employees"
          />
        </div>
      </PageSection>

      <StickyActionBar v-if="canEdit" :show="form.dirty.value" :message="form.formError.value ?? t('common.unsaved')" :tone="form.formError.value ? 'warning' : 'neutral'">
        <UiButton variant="ghost" :disabled="form.submitting.value" @click="form.reset()">{{ t("common.discard") }}</UiButton>
        <UiButton variant="primary" type="submit" :loading="form.submitting.value">{{ t("common.save") }}</UiButton>
      </StickyActionBar>
    </form>
  </div>
</template>

<style scoped>
.org-preview {
  background:
    radial-gradient(14rem 9rem at 15% 0%, color-mix(in srgb, var(--c-chart-1) 14%, transparent), transparent 70%),
    radial-gradient(12rem 9rem at 100% 100%, color-mix(in srgb, var(--c-chart-3) 12%, transparent), transparent 70%),
    var(--c-canvas);
}
</style>
