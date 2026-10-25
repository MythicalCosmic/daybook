<script setup lang="ts">
/**
 * The frame around sign-in pages: warm ground, soft brand light, the wordmark, one centered card,
 * and the three languages (Uzbek first, the default when nothing else is known).
 */
import { useI18n } from "vue-i18n";

import { LANGUAGES } from "@/api/types";
import { setLanguage } from "@/i18n";

const { t, locale } = useI18n();
</script>

<template>
  <div class="relative isolate grid min-h-dvh place-items-center overflow-hidden bg-canvas px-4 py-10">
    <div class="auth-glow pointer-events-none absolute inset-0 -z-10" aria-hidden="true" />
    <div class="flex w-full max-w-[420px] flex-col items-center">
      <div class="mb-8 flex items-center gap-3">
        <svg viewBox="0 0 50 50" class="size-10" aria-hidden="true">
          <circle cx="21" cy="21" r="21" fill="#c67139" />
          <path d="M12.25 21.9 18.4 28 29.6 15.8" fill="none" stroke="#f5ead8" stroke-width="4.2" stroke-linecap="round" stroke-linejoin="round" />
          <circle cx="39" cy="39" r="11" fill="#7a8a5e" stroke="var(--c-canvas)" stroke-width="3" />
        </svg>
        <span class="font-display text-[30px] leading-none text-fg">{{ t("shell.brand") }}</span>
        <span class="mt-1 rounded-full border border-line bg-surface px-2 py-0.5 text-xs font-semibold text-muted">{{ t("shell.brandSuffix") }}</span>
      </div>
      <div class="w-full rounded-[18px] border border-line bg-surface p-6 shadow-[0_1px_2px_rgb(32_30_29/0.04),0_24px_48px_-24px_rgb(32_30_29/0.18)] md:p-8">
        <slot />
      </div>
      <p class="mt-6 text-center text-sm text-muted">{{ t("shell.login.tagline") }}</p>
      <div class="mt-3 flex flex-wrap items-center justify-center gap-1" role="group" :aria-label="t('shell.topbar.language')">
        <button
          v-for="language in LANGUAGES"
          :key="language"
          type="button"
          :lang="language"
          :aria-pressed="locale === language"
          :class="[
            'min-h-9 rounded-full px-3 text-sm transition-colors',
            locale === language ? 'bg-surface font-semibold text-fg ring-1 ring-line' : 'text-muted hover:text-fg',
          ]"
          @click="setLanguage(language).catch(() => undefined)"
        >
          {{ t(`shell.language.${language}`) }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.auth-glow {
  background:
    radial-gradient(40rem 28rem at 15% 10%, color-mix(in srgb, var(--c-chart-1) 16%, transparent), transparent 70%),
    radial-gradient(36rem 26rem at 90% 85%, color-mix(in srgb, var(--c-chart-2) 16%, transparent), transparent 70%);
}
</style>
