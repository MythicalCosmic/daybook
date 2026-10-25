<script setup lang="ts">
/**
 * /login (plan §6.2 "Login", §7.1): the QR code of a Telegram deep link, "Open in Telegram", the
 * 2-digit number to tap in the bot (number matching), a 3-minute countdown and a live status.
 * When Telegram approves, the page claims the session once and goes where the person was headed.
 * Inside Telegram this page never shows: the guard signs in with initData instead.
 */
import {
  ArrowRight,
  BadgeCheck,
  Camera,
  CircleAlert,
  Clock3,
  KeyRound,
  Lock,
  QrCode as QrCodeIcon,
  ReceiptText,
  RefreshCw,
  Send,
  ShieldAlert,
  ShieldCheck,
  Terminal,
  Users,
  WifiOff,
} from "@lucide/vue";
import { computed, defineAsyncComponent, onMounted, ref, type Component } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import LanguageChoice from "@/components/LanguageChoice.vue";
import ProgressRing from "@/components/ProgressRing.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import UiButton from "@/components/UiButton.vue";
import { safeNext } from "@/lib/links";
import { useBreakpoints } from "@/lib/useBreakpoints";
import { useSessionStore } from "@/stores/session";

import BrandMark from "../components/BrandMark.vue";
import { useLoginLink, type LoginPhase } from "../useLoginLink";

const QrCode = defineAsyncComponent(() => import("@/components/QrCode.vue"));

const { t } = useI18n();
const route = useRoute();
const router = useRouter();
const session = useSessionStore();
const { isPhone } = useBreakpoints();
const dev = import.meta.env.DEV;
/** On a phone the deep link opens Telegram on the same phone; the QR is for another device. */
const showQr = ref(false);
const qrSize = computed(() => (isPhone.value ? 176 : 208));

const login = useLoginLink({
  onSignedIn: async (access) => {
    session.setAccess(access);
    await session.loadMe();
    await router.replace(safeNext(route.query.next));
  },
});

onMounted(() => void login.start());

const countdown = computed(() => {
  const seconds = login.remaining.value;
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
});
const digits = computed(() => (login.link.value?.match_code ?? "").split(""));
const busy = computed(() => login.phase.value === "approved" || login.phase.value === "signing-in" || login.phase.value === "done");

interface Outcome {
  icon: Component;
  tone: "danger" | "warning" | "info" | "neutral";
  title: string;
  body: string;
  action: string;
}

const outcomes = computed<Partial<Record<LoginPhase, Outcome>>>(() => ({
  denied: { icon: ShieldAlert, tone: "danger", title: t("auth.login.denied.title"), body: t("auth.login.denied.body"), action: t("auth.login.tryAgain") },
  expired: { icon: Clock3, tone: "warning", title: t("auth.login.expired.title"), body: t("auth.login.expired.body"), action: t("auth.login.newCode") },
  "no-access": { icon: Lock, tone: "neutral", title: t("auth.login.noAccess.title"), body: t("auth.login.noAccess.body"), action: t("auth.login.tryAgain") },
  unavailable: { icon: CircleAlert, tone: "info", title: t("auth.login.unavailable.title"), body: t("auth.login.unavailable.body"), action: t("auth.login.tryAgain") },
  throttled: { icon: Clock3, tone: "warning", title: t("auth.login.throttled.title"), body: t("auth.login.throttled.body"), action: t("auth.login.newCode") },
  offline: { icon: WifiOff, tone: "neutral", title: t("auth.login.offline.title"), body: t("auth.login.offline.body"), action: t("auth.login.tryAgain") },
}));
const outcome = computed(() => outcomes.value[login.phase.value] ?? null);

const toneClass: Record<Outcome["tone"], string> = {
  danger: "bg-danger-soft text-danger",
  warning: "bg-warning-soft text-warning",
  info: "bg-info-soft text-info",
  neutral: "bg-surface-2 text-muted",
};

const features = computed(() => [
  { icon: BadgeCheck, text: t("auth.login.feature.tasks") },
  { icon: ReceiptText, text: t("auth.login.feature.money") },
  { icon: Users, text: t("auth.login.feature.people") },
]);
const steps = computed(() => [
  { icon: Camera, text: t("auth.login.step1") },
  { icon: KeyRound, text: t("auth.login.step2") },
  { icon: ShieldCheck, text: t("auth.login.step3") },
]);
</script>

<template>
  <div class="relative isolate min-h-dvh overflow-hidden bg-canvas">
    <div class="login-glow pointer-events-none absolute inset-0 -z-10" aria-hidden="true" />
    <div class="mx-auto grid min-h-dvh w-full max-w-[1120px] items-center gap-10 px-4 py-8 md:grid-cols-[1.1fr_minmax(380px,440px)] md:gap-16 md:px-8 md:py-12">
      <!-- The story (desktop) -->
      <section class="hidden flex-col md:flex">
        <BrandMark />
        <h1 class="mt-10 max-w-[520px] font-display text-[44px] leading-[1.08] text-fg">
          {{ t("auth.login.headline") }}
        </h1>
        <p class="mt-4 max-w-[460px] text-md text-muted">{{ t("auth.login.subline") }}</p>
        <ul class="mt-8 flex flex-col gap-3">
          <li v-for="feature in features" :key="feature.text" class="flex items-center gap-3 text-base text-fg">
            <span class="grid size-9 shrink-0 place-items-center rounded-[10px] border border-line bg-surface text-primary">
              <component :is="feature.icon" :size="18" />
            </span>
            {{ feature.text }}
          </li>
        </ul>
        <div class="mt-9 max-w-[440px] border-t border-line pt-6">
          <p class="text-xs font-semibold uppercase tracking-[0.06em] text-subtle">{{ t("auth.login.steps.title") }}</p>
          <ol class="mt-3 flex flex-col gap-2.5">
            <li v-for="(step, index) in steps" :key="index" class="flex items-center gap-3 text-sm text-muted">
              <span class="grid size-6 shrink-0 place-items-center rounded-full bg-accent-soft text-xs font-semibold tabular-nums text-accent-fg">{{ index + 1 }}</span>
              <span>{{ step.text }}</span>
            </li>
          </ol>
        </div>
        <p class="mt-8 inline-flex items-center gap-2 text-sm text-muted">
          <ShieldCheck :size="16" class="text-success" />
          {{ t("auth.login.secure") }}
        </p>
      </section>

      <!-- The sign-in card -->
      <section class="w-full">
        <div class="mb-6 flex justify-center md:hidden"><BrandMark compact /></div>
        <div class="rounded-[20px] border border-line bg-surface p-6 shadow-drawer md:p-8">
          <h2 class="text-lg font-semibold tracking-[-0.01em] text-fg">{{ t("auth.login.title") }}</h2>
          <p v-if="login.phase.value === 'starting' || login.phase.value === 'waiting'" class="mt-1 text-base text-muted">
            {{ isPhone ? t("auth.login.leadPhone") : t("auth.login.lead") }}
          </p>

          <Transition name="swap" mode="out-in">
            <!-- Waiting for Telegram (or getting the code) -->
            <div v-if="login.phase.value === 'starting' || login.phase.value === 'waiting'" key="waiting" class="mt-6 flex flex-col items-center">
              <!-- A phone can't scan its own screen: there the code waits behind "another device". -->
              <div v-if="!isPhone || showQr" :class="['relative', isPhone && 'order-last mt-5']">
                <QrCode v-if="login.link.value" :value="login.link.value.deep_link" :size="qrSize" level="M" :label="undefined" />
                <div v-else class="grid place-items-center rounded-[14px] border border-line bg-surface-2" :style="{ width: `${qrSize + 24}px`, height: `${qrSize + 24}px` }">
                  <SkeletonBlock :width="`${qrSize}px`" :height="`${qrSize}px`" radius="8px" />
                </div>
                <span class="absolute -bottom-2 -right-2 grid size-9 place-items-center rounded-full border-[3px] border-surface bg-primary text-on-primary" aria-hidden="true">
                  <Send :size="15" />
                </span>
              </div>

              <div :class="['flex flex-col items-center', isPhone ? 'mt-1' : 'mt-7']" aria-live="polite">
                <p class="text-sm font-medium text-muted">{{ t("auth.login.tapLabel") }}</p>
                <div class="mt-2 flex gap-2" :aria-label="login.link.value?.match_code" role="img">
                  <template v-if="digits.length">
                    <span
                      v-for="(digit, index) in digits"
                      :key="index"
                      class="grid h-[64px] w-[52px] place-items-center rounded-[14px] border border-line-strong bg-surface-2 text-[38px] font-bold leading-none tabular-nums text-fg"
                    >{{ digit }}</span>
                  </template>
                  <template v-else>
                    <SkeletonBlock width="52px" height="64px" radius="14px" />
                    <SkeletonBlock width="52px" height="64px" radius="14px" />
                  </template>
                </div>
                <p class="mt-3 max-w-[300px] text-balance text-center text-xs text-muted">{{ t("auth.login.tapHint") }}</p>
              </div>

              <div class="mt-6 flex w-full items-center justify-between gap-3 rounded-[12px] bg-surface-2 px-3.5 py-2.5 text-sm">
                <span class="flex min-w-0 items-center gap-2 text-fg">
                  <span class="relative flex size-2.5 shrink-0" aria-hidden="true">
                    <span class="absolute inline-flex size-full animate-ping rounded-full bg-primary opacity-60 motion-reduce:hidden" />
                    <span class="relative inline-flex size-2.5 rounded-full bg-primary" />
                  </span>
                  <span class="min-w-0 leading-snug">{{ login.reconnecting.value ? t("auth.login.reconnecting") : t("auth.login.waiting") }}</span>
                </span>
                <span v-if="login.phase.value === 'waiting'" class="flex shrink-0 items-center gap-1.5 tabular-nums text-muted" :title="t('auth.login.expiresIn', { time: countdown })">
                  <ProgressRing :value="login.progress.value * 100" :size="16" :stroke="2.5" tone="primary" />
                  {{ countdown }}
                </span>
              </div>

              <div class="mt-5 flex w-full flex-col gap-2">
                <UiButton
                  variant="primary"
                  size="lg"
                  block
                  :icon="Send"
                  :href="login.link.value?.deep_link"
                  target="_blank"
                  :disabled="!login.link.value"
                >{{ t("auth.login.open") }}</UiButton>
                <UiButton variant="ghost" block :icon="RefreshCw" :disabled="login.phase.value === 'starting'" @click="login.start()">{{ t("auth.login.newCode") }}</UiButton>
                <UiButton v-if="isPhone" variant="ghost" size="sm" block :icon="QrCodeIcon" :aria-expanded="showQr" @click="showQr = !showQr">
                  {{ showQr ? t("auth.login.hideQr") : t("auth.login.showQr") }}
                </UiButton>
              </div>
            </div>

            <!-- Approved: claiming the session -->
            <div v-else-if="busy" key="busy" class="mt-8 flex flex-col items-center py-10 text-center">
              <span class="pop grid size-16 place-items-center rounded-full bg-success-soft text-success">
                <ShieldCheck :size="30" />
              </span>
              <p class="mt-5 text-md font-semibold text-fg">{{ t("auth.login.approved") }}</p>
              <p class="mt-1 text-sm text-muted">{{ t("auth.login.approvedHint") }}</p>
            </div>

            <!-- Every way it can end without signing in -->
            <div v-else-if="outcome" key="outcome" class="mt-8 flex flex-col items-center py-6 text-center">
              <span :class="['grid size-14 place-items-center rounded-full', toneClass[outcome.tone]]">
                <component :is="outcome.icon" :size="26" />
              </span>
              <p class="mt-5 text-md font-semibold text-fg">{{ outcome.title }}</p>
              <p class="mt-1.5 max-w-[320px] text-balance text-sm text-muted">{{ outcome.body }}</p>
              <UiButton class="mt-6" variant="primary" size="lg" :icon="RefreshCw" @click="login.start()">{{ outcome.action }}</UiButton>
            </div>
          </Transition>

          <div v-if="login.phase.value === 'waiting' || login.phase.value === 'starting'" class="mt-7 border-t border-line pt-5 md:hidden">
            <p class="text-xs font-semibold uppercase tracking-[0.06em] text-subtle">{{ t("auth.login.steps.title") }}</p>
            <ol class="mt-3 flex flex-col gap-2.5">
              <li v-for="(step, index) in steps" :key="index" class="flex items-start gap-3 text-sm text-muted">
                <span class="grid size-6 shrink-0 place-items-center rounded-full bg-accent-soft text-xs font-semibold tabular-nums text-accent-fg">{{ index + 1 }}</span>
                <span class="pt-0.5">{{ step.text }}</span>
              </li>
            </ol>
          </div>
        </div>

        <div v-if="dev" class="mt-4 flex justify-center">
          <UiButton variant="ghost" size="sm" :icon="Terminal" :icon-right="ArrowRight" :to="{ path: '/dev/login', query: route.query }">{{ t("auth.login.dev") }}</UiButton>
        </div>
        <p class="mt-4 flex items-center justify-center gap-2 text-center text-xs text-muted md:hidden">
          <ShieldCheck :size="14" class="text-success" />
          {{ t("auth.login.secure") }}
        </p>
        <!-- Uzbek until the reader picks another language (nothing else is known before sign-in). -->
        <LanguageChoice class="mt-3" data-testid="login-languages" />
      </section>
    </div>
  </div>
</template>

<style scoped>
.login-glow {
  background:
    radial-gradient(44rem 30rem at 12% 8%, color-mix(in srgb, var(--c-chart-1) 15%, transparent), transparent 70%),
    radial-gradient(40rem 28rem at 92% 92%, color-mix(in srgb, var(--c-chart-2) 16%, transparent), transparent 70%),
    radial-gradient(30rem 22rem at 70% 10%, color-mix(in srgb, var(--c-chart-4) 9%, transparent), transparent 70%);
}
.swap-enter-active,
.swap-leave-active {
  transition:
    opacity var(--dur-fade) var(--ease-out),
    transform var(--dur-fade) var(--ease-out);
}
.swap-enter-from {
  opacity: 0;
  transform: translateY(6px);
}
.swap-leave-to {
  opacity: 0;
}
.pop {
  animation: pop 420ms var(--ease-out) both;
}
@keyframes pop {
  from {
    transform: scale(0.6);
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
@media (prefers-reduced-motion: reduce) {
  .pop {
    animation: none;
  }
}
</style>
