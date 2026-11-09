<script setup lang="ts">
/**
 * /login in the Davomat edition (docs/DAVOMAT.md §1.2): username and password, show/hide, Remember
 * me, the three languages, and clear messages for a wrong pair, the lockout after five wrong tries
 * (429) and an unreachable server. The organization's logo and name brand the page; on a desktop a
 * calm picture of the live board sits beside the form.
 */
import { CircleAlert, Clock3, Eye, EyeOff, KeyRound, LockKeyhole, ShieldCheck, UserRound, WifiOff, type LucideIcon } from "@lucide/vue";
import { computed, nextTick, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import { isApiError } from "@/api/http";
import CheckBox from "@/components/CheckBox.vue";
import FormField from "@/components/FormField.vue";
import LanguageChoice from "@/components/LanguageChoice.vue";
import TextInput from "@/components/TextInput.vue";
import UiButton from "@/components/UiButton.vue";
import { rememberSession } from "@/core/remember";
import { safeNext } from "@/lib/links";
import { useSessionStore } from "@/stores/session";

import { passwordLogin } from "../api";
import LivePreview from "../components/brand/LivePreview.vue";
import OrgBrand from "../components/brand/OrgBrand.vue";

const { t } = useI18n();
const route = useRoute();
const router = useRouter();
const session = useSessionStore();

const username = ref("");
const password = ref("");
const remember = ref(true);
const reveal = ref(false);
const capsLock = ref(false);
const busy = ref(false);
type Problem = "required" | "wrong" | "locked" | "offline" | "failed";
const problem = ref<{ kind: Problem; text: string } | null>(null);

const usernameInput = ref<InstanceType<typeof TextInput> | null>(null);
const passwordInput = ref<InstanceType<typeof TextInput> | null>(null);

onMounted(() => void nextTick(() => usernameInput.value?.focus()));

const icons: Record<Problem, LucideIcon> = { required: CircleAlert, wrong: KeyRound, locked: Clock3, offline: WifiOff, failed: CircleAlert };

function readCaps(event: KeyboardEvent): void {
  capsLock.value = typeof event.getModifierState === "function" && event.getModifierState("CapsLock");
}

/**
 * What went wrong, in the page's language: the server's codes (`wrong_password`, `no_access`,
 * `locked` with the minutes left in its text) map to this module's own sentences.
 */
function problemOf(error: unknown): { kind: Problem; text: string } {
  if (!isApiError(error)) return { kind: "failed", text: t("davomat.login.failed") };
  if (error.isNetwork) return { kind: "offline", text: t("davomat.login.offline") };
  if (error.status === 429 || error.code === "locked") {
    const minutes = Number(/(\d+)/.exec(error.detail ?? "")?.[1] ?? 0);
    return { kind: "locked", text: minutes > 0 ? t("davomat.login.lockedFor", { n: minutes }, minutes) : t("davomat.login.locked") };
  }
  if (error.status === 403 || error.code === "no_access") return { kind: "wrong", text: t("davomat.login.noAccess") };
  if (error.status === 400 || error.status === 401) return { kind: "wrong", text: t("davomat.login.wrong") };
  return { kind: "failed", text: t("davomat.login.failed") };
}

async function submit(): Promise<void> {
  if (busy.value) return;
  const name = username.value.trim();
  if (!name || !password.value) {
    problem.value = { kind: "required", text: t("davomat.login.required") };
    (name ? passwordInput : usernameInput).value?.focus();
    return;
  }
  busy.value = true;
  problem.value = null;
  try {
    const { access } = await passwordLogin(name, password.value);
    rememberSession(remember.value);
    session.setAccess(access);
    await session.loadMe();
    await router.replace(safeNext(route.query.next));
  } catch (error) {
    problem.value = problemOf(error);
    password.value = "";
    await nextTick();
    passwordInput.value?.focus();
  } finally {
    busy.value = false;
  }
}

const features = computed(() => [t("davomat.login.feature.live"), t("davomat.login.feature.late"), t("davomat.login.feature.reports")]);
</script>

<template>
  <div class="relative isolate min-h-dvh overflow-hidden bg-canvas">
    <div class="glow pointer-events-none absolute inset-0 -z-10" aria-hidden="true" />
    <div class="mx-auto grid min-h-dvh w-full max-w-[1180px] items-center gap-10 px-4 py-8 md:grid-cols-[1.08fr_minmax(380px,440px)] md:gap-16 md:px-8 md:py-12">
      <!-- The story (desktop): who this is for, and a calm picture of the live board -->
      <section class="hidden flex-col md:flex">
        <OrgBrand size="lg" />
        <h1 class="mt-10 max-w-[540px] text-balance text-[40px] font-bold leading-[1.1] tracking-[-0.03em] text-fg">{{ t("davomat.login.headline") }}</h1>
        <p class="mt-4 max-w-[480px] text-md text-muted">{{ t("davomat.login.subline") }}</p>
        <div class="mt-8">
          <LivePreview />
        </div>
        <ul class="mt-8 flex flex-col gap-2.5">
          <li v-for="feature in features" :key="feature" class="flex items-center gap-3 text-base text-fg">
            <span class="grid size-6 shrink-0 place-items-center rounded-full bg-accent-soft text-accent-fg">
              <svg viewBox="0 0 16 16" class="size-3.5" aria-hidden="true"><path d="M3.5 8.4l2.9 2.9 6-6.3" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" /></svg>
            </span>
            {{ feature }}
          </li>
        </ul>
      </section>

      <!-- The sign-in card -->
      <section class="w-full">
        <div class="mb-7 flex justify-center md:hidden"><OrgBrand /></div>
        <form class="rounded-[22px] border border-line bg-surface p-6 shadow-drawer md:p-8" novalidate @submit.prevent="submit">
          <h2 class="text-xl font-bold tracking-[-0.02em] text-fg">{{ t("davomat.login.title") }}</h2>
          <p class="mt-1 text-base text-muted">{{ t("davomat.login.lead") }}</p>

          <Transition name="fade">
            <div
              v-if="problem"
              :key="problem.kind + problem.text"
              role="alert"
              :class="[
                'mt-5 flex items-start gap-2.5 rounded-[12px] px-3.5 py-3 text-sm',
                problem.kind === 'locked' ? 'bg-warning-soft text-warning' : problem.kind === 'offline' ? 'bg-surface-2 text-fg' : 'bg-danger-soft text-danger',
              ]"
              data-testid="login-problem"
            >
              <component :is="icons[problem.kind]" :size="17" class="mt-px shrink-0" aria-hidden="true" />
              <span class="leading-snug">{{ problem.text }}</span>
            </div>
          </Transition>

          <div class="mt-6 flex flex-col gap-4">
            <FormField :label="t('davomat.login.username')">
              <TextInput
                ref="usernameInput"
                v-model="username"
                size="lg"
                :icon="UserRound"
                autocomplete="username"
                autocapitalize="none"
                spellcheck="false"
                :invalid="problem?.kind === 'wrong' || (problem?.kind === 'required' && !username.trim())"
                data-testid="login-username"
                @enter="passwordInput?.focus()"
              />
            </FormField>
            <FormField :label="t('davomat.login.password')">
              <TextInput
                ref="passwordInput"
                v-model="password"
                size="lg"
                :type="reveal ? 'text' : 'password'"
                :icon="LockKeyhole"
                autocomplete="current-password"
                :invalid="problem?.kind === 'wrong' || (problem?.kind === 'required' && !!username.trim() && !password)"
                data-testid="login-password"
                @keydown="readCaps"
                @keyup="readCaps"
              >
                <template #trailing>
                  <button
                    type="button"
                    class="pressable -mr-1 grid size-8 shrink-0 place-items-center rounded-[8px] text-muted hover:bg-highlight hover:text-fg"
                    :aria-label="reveal ? t('davomat.login.hide') : t('davomat.login.show')"
                    :aria-pressed="reveal"
                    data-testid="login-reveal"
                    @click.stop="reveal = !reveal"
                  >
                    <EyeOff v-if="reveal" :size="17" />
                    <Eye v-else :size="17" />
                  </button>
                </template>
              </TextInput>
              <p v-if="capsLock" class="mt-1.5 flex items-center gap-1.5 text-xs font-medium text-warning" data-testid="login-caps">
                <CircleAlert :size="13" aria-hidden="true" />
                {{ t("davomat.login.capsLock") }}
              </p>
            </FormField>
            <CheckBox v-model="remember" :label="t('davomat.login.remember')" :description="t('davomat.login.rememberHint')" data-testid="login-remember" />
          </div>

          <UiButton class="mt-6" type="submit" variant="primary" size="lg" block :loading="busy" data-testid="login-submit">
            {{ busy ? t("davomat.login.signingIn") : t("davomat.login.submit") }}
          </UiButton>
          <p class="mt-4 text-center text-sm text-muted">{{ t("davomat.login.forgot") }}</p>
        </form>

        <p class="mt-5 flex items-center justify-center gap-2 text-center text-xs text-muted">
          <ShieldCheck :size="14" class="shrink-0 text-success" aria-hidden="true" />
          {{ t("davomat.login.secure") }}
        </p>
        <LanguageChoice class="mt-3" data-testid="login-languages" />
      </section>
    </div>
  </div>
</template>

<style scoped>
.glow {
  background:
    radial-gradient(46rem 32rem at 8% 0%, color-mix(in srgb, var(--c-primary) 13%, transparent), transparent 70%),
    radial-gradient(40rem 30rem at 96% 100%, color-mix(in srgb, var(--c-chart-2) 12%, transparent), transparent 70%),
    radial-gradient(30rem 24rem at 60% 12%, color-mix(in srgb, var(--c-chart-3) 8%, transparent), transparent 70%);
}
.fade-enter-active,
.fade-leave-active {
  transition:
    opacity var(--dur-fade, 180ms) var(--ease-out),
    transform var(--dur-fade, 180ms) var(--ease-out);
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}
</style>
