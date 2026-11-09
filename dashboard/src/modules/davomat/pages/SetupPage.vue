<script setup lang="ts">
/**
 * /setup: Davomat's first run (docs/DAVOMAT.md §1.1), shown at every address until it has run once.
 * Three steps: the organization (name, time zone, language), the administrator's account, and
 * done: signed in, with "Add your first terminal" as the next thing to do. The language picked in
 * step one switches the wizard at once.
 */
import { ArrowLeft, ArrowRight, Building2, Languages, PartyPopper, ScanFace, Send, UserRound, Users } from "@lucide/vue";
import { computed, nextTick, onMounted, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";

import { isApiError } from "@/api/http";
import { LANGUAGES, type Language } from "@/api/types";
import ComboBox from "@/components/ComboBox.vue";
import FormField from "@/components/FormField.vue";
import LanguageChoice from "@/components/LanguageChoice.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import TextInput from "@/components/TextInput.vue";
import UiButton from "@/components/UiButton.vue";
import WizardSteps from "@/components/WizardSteps.vue";
import { editionInfo, refreshEdition } from "@/core/edition";
import { rememberSession } from "@/core/remember";
import { currentLanguage, setLanguage } from "@/i18n";
import { useSessionStore } from "@/stores/session";

import { runSetup } from "../api";
import DavomatMark from "../components/brand/DavomatMark.vue";
import PasswordField from "../components/fields/PasswordField.vue";
import { MIN_LENGTH, suggestUsername, USERNAME_PATTERN } from "../lib/password";
import { browserZone, DEFAULT_ZONE, MAIN_ZONES, zoneOptions } from "../lib/zones";

type Step = "organization" | "admin" | "done";

const { t } = useI18n();
const router = useRouter();
const session = useSessionStore();

const step = ref<Step>("organization");
const steps = computed(() => [
  { id: "organization", label: t("davomat.setup.step.organization") },
  { id: "admin", label: t("davomat.setup.step.admin") },
  { id: "done", label: t("davomat.setup.step.done") },
]);
const completed = computed(() => (step.value === "admin" ? ["organization"] : step.value === "done" ? ["organization", "admin"] : []));

const detected = browserZone();
const org = reactive({
  name: "",
  timezone: detected && MAIN_ZONES.some((z) => z.zone === detected) ? detected : DEFAULT_ZONE,
  language: currentLanguage() as Language,
});
const admin = reactive({ first_name: "", last_name: "", username: "", password: "", confirm: "" });
const usernameEdited = ref(false);
const errors = reactive<Record<string, string | undefined>>({});
const busy = ref(false);
const taken = ref(false);
const failure = ref<string | null>(null);

const zones = computed(() => zoneOptions(t, org.timezone));
const languages = computed(() => LANGUAGES.map((language) => ({ value: language, label: t(`shell.language.${language}`) })));

// The wizard speaks the organization's language as soon as it is picked.
watch(
  () => org.language,
  (language) => void setLanguage(language).catch(() => undefined),
);
// The username follows the name until the person types one.
watch(
  () => [admin.first_name, admin.last_name] as const,
  ([first, last]) => {
    if (!usernameEdited.value) admin.username = suggestUsername(first, last);
  },
);

const nameInput = ref<InstanceType<typeof TextInput> | null>(null);
const firstInput = ref<InstanceType<typeof TextInput> | null>(null);
onMounted(() => {
  // A server set up already (someone else finished it, or a reload after the last step).
  if (!editionInfo.value.needs_setup) {
    if (session.signedIn) step.value = "done";
    else void router.replace("/login");
    return;
  }
  void nextTick(() => nameInput.value?.focus());
});

function clearErrors(): void {
  for (const key of Object.keys(errors)) errors[key] = undefined;
}

function validateOrganization(): boolean {
  errors.organization = org.name.trim() ? (org.name.trim().length > 200 ? t("common.form.tooLong") : undefined) : t("common.form.required");
  errors.timezone = org.timezone ? undefined : t("common.form.required");
  return !errors.organization && !errors.timezone;
}

function validateAdmin(): boolean {
  errors.first_name = admin.first_name.trim() ? undefined : t("common.form.required");
  errors.username = !admin.username.trim() ? t("common.form.required") : USERNAME_PATTERN.test(admin.username.trim()) ? undefined : t("davomat.setup.admin.usernameInvalid");
  errors.password = admin.password.length < MIN_LENGTH ? t("davomat.password.tooShort") : undefined;
  errors.confirm = !errors.password && admin.confirm !== admin.password ? t("davomat.setup.admin.mismatch") : undefined;
  return !errors.first_name && !errors.username && !errors.password && !errors.confirm;
}

async function next(): Promise<void> {
  if (!validateOrganization()) return void nameInput.value?.focus();
  step.value = "admin";
  await nextTick();
  firstInput.value?.focus();
}

/** DRF errors, nested (`{admin: {password: [...]}}`) or flat, onto the wizard's fields. */
function applyServerErrors(body: unknown): boolean {
  if (!body || typeof body !== "object") return false;
  const record = body as Record<string, unknown>;
  const first = (value: unknown) => (Array.isArray(value) && typeof value[0] === "string" ? value[0] : typeof value === "string" ? value : undefined);
  let found = false;
  const place = (field: string, value: unknown) => {
    const message = first(value);
    if (message) {
      errors[field] = message;
      found = true;
    }
  };
  place("organization", record.organization);
  place("timezone", record.timezone);
  const nested = record.admin && typeof record.admin === "object" ? (record.admin as Record<string, unknown>) : record;
  for (const field of ["first_name", "last_name", "username", "password"]) place(field, nested[field]);
  return found;
}

async function create(): Promise<void> {
  if (busy.value || !validateAdmin()) return;
  busy.value = true;
  failure.value = null;
  clearErrors();
  try {
    const { access } = await runSetup({
      organization: org.name.trim(),
      timezone: org.timezone,
      language: org.language,
      admin: { username: admin.username.trim(), password: admin.password, first_name: admin.first_name.trim(), last_name: admin.last_name.trim() },
    });
    rememberSession(true);
    session.setAccess(access);
    await session.loadMe();
    await refreshEdition();
    step.value = "done";
  } catch (error) {
    if (isApiError(error) && (error.status === 403 || error.status === 409 || error.status === 404)) {
      taken.value = true;
    } else if (isApiError(error) && error.status === 400 && applyServerErrors(error.body)) {
      if (errors.organization || errors.timezone) step.value = "organization";
    } else {
      failure.value = isApiError(error) && error.isNetwork ? t("davomat.login.offline") : (isApiError(error) && error.detail) || t("davomat.setup.error.generic");
    }
  } finally {
    busy.value = false;
  }
}

const companyId = computed(() => session.me?.companies[0]?.id ?? null);
const home = computed(() => (companyId.value ? `/c/${companyId.value}` : "/"));
const nextSteps = computed(() => [
  { icon: ScanFace, text: t("davomat.setup.done.nextTerminal"), to: `${home.value}/faceid/terminals?add=1` },
  { icon: Users, text: t("davomat.setup.done.nextTeam"), to: `${home.value}/team?import=1` },
  { icon: Send, text: t("davomat.setup.done.nextTelegram"), to: `${home.value}/settings/telegram` },
]);
const greetingName = computed(() => admin.first_name.trim() || session.me?.user.first_name || "");
const organizationName = computed(() => editionInfo.value.organization?.name ?? org.name.trim());
</script>

<template>
  <div class="relative isolate min-h-dvh overflow-hidden bg-canvas">
    <div class="glow pointer-events-none absolute inset-0 -z-10" aria-hidden="true" />
    <div class="mx-auto flex min-h-dvh w-full max-w-[640px] flex-col px-4 py-8 md:py-14">
      <header class="flex items-center gap-3">
        <DavomatMark :size="40" />
        <div class="min-w-0">
          <p class="text-lg font-bold leading-tight tracking-[-0.02em] text-fg">{{ editionInfo.product }}</p>
          <p class="text-sm text-muted">{{ t("davomat.brand.tagline") }}</p>
        </div>
      </header>

      <div class="mt-8 md:mt-10">
        <h1 class="text-[28px] font-bold leading-tight tracking-[-0.025em] text-fg md:text-[34px]">{{ step === "done" ? t("davomat.setup.done.title", { name: greetingName }) : t("davomat.setup.welcome") }}</h1>
        <p v-if="step !== 'done'" class="mt-2 text-md text-muted">{{ t("davomat.setup.lead") }}</p>
      </div>

      <div class="mt-7 rounded-[22px] border border-line bg-surface p-5 shadow-drawer md:p-8">
        <!-- Once created there is no going back to the forms. -->
        <WizardSteps v-if="step !== 'done'" v-model="step" :steps="steps" :completed="completed" :linear="true" class="mb-7" />

        <!-- Someone set this server up already -->
        <div v-if="taken" class="flex flex-col items-center py-6 text-center" data-testid="setup-taken">
          <span class="grid size-14 place-items-center rounded-full bg-info-soft text-info"><Building2 :size="26" /></span>
          <p class="mt-4 max-w-[360px] text-md font-semibold text-fg">{{ t("davomat.setup.error.taken") }}</p>
          <UiButton class="mt-6" variant="primary" size="lg" to="/login">{{ t("davomat.setup.signIn") }}</UiButton>
        </div>

        <Transition v-else name="step" mode="out-in">
          <!-- 1. The organization -->
          <form v-if="step === 'organization'" key="organization" class="flex flex-col gap-5" novalidate data-testid="setup-organization" @submit.prevent="next">
            <div>
              <h2 class="text-lg font-semibold tracking-[-0.01em] text-fg">{{ t("davomat.setup.org.title") }}</h2>
              <p class="mt-1 text-base text-muted">{{ t("davomat.setup.org.hint") }}</p>
            </div>
            <FormField :label="t('davomat.setup.org.name')" :error="errors.organization" required>
              <TextInput ref="nameInput" v-model="org.name" size="lg" :icon="Building2" :placeholder="t('davomat.setup.org.namePlaceholder')" :maxlength="200" autocomplete="organization" data-testid="setup-name" />
            </FormField>
            <FormField :label="t('davomat.setup.org.timezone')" :hint="t('davomat.setup.org.timezoneHint')" :error="errors.timezone">
              <ComboBox v-model="org.timezone" :options="zones" size="lg" :search-placeholder="t('davomat.tz.search')" data-testid="setup-timezone" />
            </FormField>
            <FormField :label="t('davomat.setup.org.language')" :hint="t('davomat.setup.org.languageHint')">
              <SegmentedControl v-model="org.language" :options="languages" block :aria-label="t('davomat.setup.org.language')" />
            </FormField>
            <div class="mt-2 flex justify-end">
              <UiButton type="submit" variant="primary" size="lg" :icon-right="ArrowRight" data-testid="setup-next">{{ t("davomat.setup.next") }}</UiButton>
            </div>
          </form>

          <!-- 2. The administrator -->
          <form v-else-if="step === 'admin'" key="admin" class="flex flex-col gap-5" novalidate data-testid="setup-admin" @submit.prevent="create">
            <div>
              <h2 class="text-lg font-semibold tracking-[-0.01em] text-fg">{{ t("davomat.setup.admin.title") }}</h2>
              <p class="mt-1 text-base text-muted">{{ t("davomat.setup.admin.hint") }}</p>
            </div>
            <div class="grid gap-4 sm:grid-cols-2">
              <FormField :label="t('davomat.setup.admin.firstName')" :error="errors.first_name" required>
                <TextInput ref="firstInput" v-model="admin.first_name" size="lg" autocomplete="given-name" :maxlength="150" data-testid="setup-first" />
              </FormField>
              <FormField :label="t('davomat.setup.admin.lastName')" :error="errors.last_name" optional>
                <TextInput v-model="admin.last_name" size="lg" autocomplete="family-name" :maxlength="150" />
              </FormField>
            </div>
            <FormField :label="t('davomat.setup.admin.username')" :hint="t('davomat.setup.admin.usernameHint')" :error="errors.username" required>
              <TextInput
                v-model="admin.username"
                size="lg"
                :icon="UserRound"
                autocomplete="username"
                autocapitalize="none"
                spellcheck="false"
                :maxlength="150"
                data-testid="setup-username"
                @input="usernameEdited = true"
              />
            </FormField>
            <FormField :label="t('davomat.setup.admin.password')" :hint="errors.password ? undefined : t('davomat.setup.admin.passwordHint')" :error="errors.password" required>
              <PasswordField v-model="admin.password" size="lg" :username="admin.username" :invalid="!!errors.password" data-testid="setup-password" />
            </FormField>
            <FormField :label="t('davomat.setup.admin.confirm')" :error="errors.confirm" required>
              <PasswordField v-model="admin.confirm" size="lg" :meter="false" :invalid="!!errors.confirm" data-testid="setup-confirm" />
            </FormField>
            <p v-if="failure" role="alert" class="rounded-[12px] bg-danger-soft px-3.5 py-3 text-sm text-danger" data-testid="setup-failure">{{ failure }}</p>
            <div class="mt-2 flex items-center justify-between gap-3">
              <UiButton variant="ghost" size="lg" :icon="ArrowLeft" :disabled="busy" @click="step = 'organization'">{{ t("davomat.setup.back") }}</UiButton>
              <UiButton type="submit" variant="primary" size="lg" :loading="busy" data-testid="setup-create">{{ busy ? t("davomat.setup.creating") : t("davomat.setup.create") }}</UiButton>
            </div>
          </form>

          <!-- 3. Done -->
          <div v-else key="done" class="flex flex-col" data-testid="setup-done">
            <div class="flex flex-col items-center py-2 text-center">
              <span class="celebrate relative grid size-20 place-items-center rounded-full bg-success-soft text-success">
                <PartyPopper :size="34" />
                <span v-for="n in 8" :key="n" class="spark" :style="{ '--i': n }" aria-hidden="true" />
              </span>
              <p class="mt-5 max-w-[460px] text-balance text-md text-muted">{{ t("davomat.setup.done.body", { organization: organizationName }) }}</p>
              <div class="mt-6 flex w-full flex-col gap-2 sm:w-auto sm:flex-row">
                <UiButton variant="primary" size="lg" :icon="ScanFace" :to="nextSteps[0]!.to" data-testid="setup-terminal">{{ t("davomat.setup.done.terminal") }}</UiButton>
                <UiButton variant="ghost" size="lg" :to="home">{{ t("davomat.setup.done.later") }}</UiButton>
              </div>
            </div>
            <div class="mt-8 border-t border-line pt-6">
              <p class="text-xs font-semibold uppercase tracking-[0.06em] text-subtle">{{ t("davomat.setup.done.next") }}</p>
              <ul class="mt-3 flex flex-col gap-1">
                <li v-for="(item, index) in nextSteps" :key="item.to">
                  <RouterLink :to="item.to" class="pressable group flex items-center gap-3 rounded-[12px] px-2.5 py-2.5 hover:bg-highlight">
                    <span class="grid size-9 shrink-0 place-items-center rounded-[10px] bg-accent-soft text-accent-fg"><component :is="item.icon" :size="18" /></span>
                    <span class="min-w-0 flex-1 text-base font-medium text-fg">{{ item.text }}</span>
                    <span class="text-xs font-semibold tabular-nums text-subtle">{{ index + 1 }}</span>
                    <ArrowRight :size="16" class="text-subtle transition-transform group-hover:translate-x-0.5 group-hover:text-muted" />
                  </RouterLink>
                </li>
              </ul>
            </div>
          </div>
        </Transition>
      </div>

      <div class="mt-6 flex items-center justify-center gap-2 text-muted">
        <Languages :size="15" aria-hidden="true" />
        <LanguageChoice />
      </div>
    </div>
  </div>
</template>

<style scoped>
.glow {
  background:
    radial-gradient(44rem 30rem at 12% 0%, color-mix(in srgb, var(--c-primary) 12%, transparent), transparent 70%),
    radial-gradient(40rem 28rem at 92% 96%, color-mix(in srgb, var(--c-chart-2) 11%, transparent), transparent 70%);
}
.step-enter-active,
.step-leave-active {
  transition:
    opacity 200ms var(--ease-out),
    transform 200ms var(--ease-out);
}
.step-enter-from {
  opacity: 0;
  transform: translateX(14px);
}
.step-leave-to {
  opacity: 0;
  transform: translateX(-10px);
}
.celebrate {
  animation: pop 520ms var(--ease-out) both;
}
.spark {
  position: absolute;
  left: 50%;
  top: 50%;
  width: 7px;
  height: 7px;
  margin: -3.5px;
  border-radius: 999px;
  background: var(--c-chart-1);
  opacity: 0;
  animation: spark 900ms var(--ease-out) 180ms both;
  transform: rotate(calc(var(--i) * 45deg)) translateY(0);
}
.spark:nth-child(3n) {
  background: var(--c-chart-4);
}
.spark:nth-child(3n + 1) {
  background: var(--c-chart-2);
}
@keyframes pop {
  from {
    transform: scale(0.5);
    opacity: 0;
  }
  60% {
    transform: scale(1.08);
    opacity: 1;
  }
  to {
    transform: scale(1);
  }
}
@keyframes spark {
  0% {
    opacity: 0;
    transform: rotate(calc(var(--i) * 45deg)) translateY(0) scale(0.6);
  }
  30% {
    opacity: 1;
  }
  100% {
    opacity: 0;
    transform: rotate(calc(var(--i) * 45deg)) translateY(-58px) scale(1);
  }
}
@media (prefers-reduced-motion: reduce) {
  .celebrate,
  .spark {
    animation: none;
  }
  .spark {
    display: none;
  }
  .step-enter-active,
  .step-leave-active {
    transition: none;
  }
}
</style>
