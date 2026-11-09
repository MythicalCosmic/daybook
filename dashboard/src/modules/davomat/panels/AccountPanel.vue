<script setup lang="ts">
/**
 * Settings › Your account: who is signed in (name, username, role), a new password (the current one
 * first; the server's validators decide what is strong enough), and this person's language and
 * appearance. Everyone has it, whatever their role.
 */
import { Monitor, Moon, ShieldCheck, Sun } from "@lucide/vue";
import { useQueryClient } from "@tanstack/vue-query";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import { z } from "zod";

import { shellApi } from "@/api/shell";
import { LANGUAGES, type Language } from "@/api/types";
import FormField from "@/components/FormField.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import PageSection from "@/components/PageSection.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import UiButton from "@/components/UiButton.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { toast } from "@/components/useToast";
import { editionInfo } from "@/core/edition";
import { isLanguage, setLanguage } from "@/i18n";
import { useForm } from "@/lib/useForm";
import { useCompanyStore } from "@/stores/company";
import { useSessionStore } from "@/stores/session";
import { useUiStore, type ThemeMode } from "@/stores/ui";

import { changePassword } from "../api";
import PasswordField from "../components/fields/PasswordField.vue";
import SecretInput from "../components/settings/SecretInput.vue";
import { MIN_LENGTH } from "../lib/password";

const { t, locale } = useI18n();
const session = useSessionStore();
const company = useCompanyStore();
const ui = useUiStore();
const client = useQueryClient();

const user = computed(() => session.me?.user ?? null);
const name = computed(() => user.value?.full_name || [user.value?.first_name, user.value?.last_name].filter(Boolean).join(" ") || user.value?.username || "");

// ─── Password ─────────────────────────────────────────────────────────────────

const schema = z
  .object({
    current: z.string().min(1, "common.form.required"),
    new: z.string().min(MIN_LENGTH, "davomat.password.tooShort"),
    confirm: z.string(),
  })
  .superRefine((values, ctx) => {
    if (values.new && values.new === values.current) ctx.addIssue({ code: "custom", path: ["new"], message: "davomat.account.password.same" });
    if (values.confirm !== values.new) ctx.addIssue({ code: "custom", path: ["confirm"], message: "davomat.account.password.mismatch" });
  });

const changed = ref(false);
const form = useForm(schema, { current: "", new: "", confirm: "" }, {
  onSubmit: async (values) => {
    await changePassword(values.current, values.new);
    form.reset({ current: "", new: "", confirm: "" });
    changed.value = true;
    toast.success(t("davomat.account.password.changed"));
  },
});

// ─── Language and appearance ──────────────────────────────────────────────────

const languages = computed(() => LANGUAGES.map((language) => ({ value: language, label: t(`shell.language.${language}`) })));
const language = computed<Language>({
  get: () => (isLanguage(locale.value) ? locale.value : "uz"),
  set: (next) => void pickLanguage(next),
});

async function pickLanguage(next: Language): Promise<void> {
  // Its dictionary first, so what refetches below already comes in the new language.
  await setLanguage(next).catch(() => undefined);
  session.setLanguage(next);
  void client.invalidateQueries();
  try {
    await shellApi.setLanguage(next);
  } catch {
    // Kept in this browser; the account keeps its old language until the next save.
  }
}

const themes = computed(() => [
  { value: "light" as ThemeMode, label: t("davomat.account.appearance.light"), icon: Sun },
  { value: "dark" as ThemeMode, label: t("davomat.account.appearance.dark"), icon: Moon },
  { value: "system" as ThemeMode, label: t("davomat.account.appearance.system"), icon: Monitor },
]);
const theme = computed<ThemeMode>({ get: () => ui.themeMode, set: (mode) => ui.setThemeMode(mode) });
</script>

<template>
  <div class="flex flex-col gap-6" data-account>
    <!-- Who is signed in -->
    <section class="ui-card flex flex-wrap items-center gap-4 p-5" data-profile>
      <UserAvatar :name="name || '·'" :src="user?.photo_url ?? null" :size="56" />
      <div class="min-w-[min(100%,200px)] flex-1">
        <p class="text-md font-semibold text-fg">{{ name }}</p>
        <p class="mt-0.5 flex flex-wrap items-center gap-x-2 text-sm text-muted">
          <span v-if="user?.username" class="font-mono">{{ user.username }}</span>
          <span v-if="user?.username && company.current?.role" aria-hidden="true">·</span>
          <span v-if="company.current?.role">{{ company.current.role.name }}</span>
        </p>
      </div>
      <p class="flex items-center gap-2 text-sm text-muted">
        <ShieldCheck :size="16" class="shrink-0 text-success" />
        {{ t("davomat.account.signedInto", { organization: company.current?.name ?? editionInfo.organization?.name ?? "" }) }}
      </p>
    </section>

    <!-- Password -->
    <PageSection variant="card" :title="t('davomat.account.password.title')" :description="t('davomat.account.password.hint')">
      <form class="flex max-w-[460px] flex-col gap-4" novalidate data-password-form @submit="form.submit">
        <InlineAlert v-if="form.formError.value" tone="danger" :description="form.formError.value" />
        <InlineAlert v-else-if="changed && !form.dirty.value" tone="success" size="sm" :description="t('davomat.account.password.changedHint')" />
        <!-- A hidden username lets the browser's password manager file the new password under the right account. -->
        <input type="text" class="hidden" autocomplete="username" :value="user?.username ?? ''" readonly tabindex="-1" aria-hidden="true" />
        <FormField :label="t('davomat.account.password.current')" :error="form.errors.current" required>
          <SecretInput v-model="form.values.current" autocomplete="current-password" :invalid="!!form.errors.current" data-field="current" @blur="form.touch('current')" />
        </FormField>
        <FormField :label="t('davomat.account.password.new')" :error="form.errors.new" required>
          <PasswordField v-model="form.values.new" :username="user?.username ?? ''" autocomplete="new-password" :invalid="!!form.errors.new" data-field="new" />
        </FormField>
        <FormField :label="t('davomat.account.password.confirm')" :error="form.errors.confirm" required>
          <SecretInput v-model="form.values.confirm" autocomplete="new-password" :invalid="!!form.errors.confirm" data-field="confirm" @blur="form.touch('confirm')" />
        </FormField>
        <div>
          <UiButton variant="primary" type="submit" :loading="form.submitting.value">{{ t("davomat.account.password.submit") }}</UiButton>
        </div>
      </form>
    </PageSection>

    <!-- Language and appearance -->
    <PageSection variant="card" :title="t('davomat.account.prefs.title')" :description="t('davomat.account.prefs.hint')">
      <div class="grid gap-5 md:grid-cols-2">
        <FormField :label="t('davomat.account.language')">
          <SegmentedControl v-model="language" :options="languages" block :aria-label="t('davomat.account.language')" data-language />
        </FormField>
        <FormField :label="t('davomat.account.appearance.title')">
          <SegmentedControl v-model="theme" :options="themes" block :aria-label="t('davomat.account.appearance.title')" data-theme-mode />
        </FormField>
      </div>
    </PageSection>
  </div>
</template>
