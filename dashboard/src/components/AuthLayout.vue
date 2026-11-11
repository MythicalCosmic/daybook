<script setup lang="ts">
/**
 * The frame around sign-in pages: warm ground, soft brand light, the wordmark, one centered card,
 * and the three languages (Uzbek first, the default when nothing else is known). In Davomat the
 * head is the organization's (its logo, else Davomat's mark, its name and the product), never
 * Daybook's wordmark, and Daybook's tagline stays out: the Davomat Mini App's "Session ended"
 * page is framed by it.
 */
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import { davomatMark } from "@/core/brand";
import { editionInfo, isDavomat } from "@/core/edition";

import CompanyLogo from "./CompanyLogo.vue";
import LanguageChoice from "./LanguageChoice.vue";

const { t } = useI18n();
const davomat = computed(() => isDavomat());
const organization = computed(() => editionInfo.value.organization);
// A static mark drawn in core/brand.ts, never from input: safe for v-html.
const mark = davomatMark();
</script>

<template>
  <div class="relative isolate grid min-h-dvh place-items-center overflow-hidden bg-canvas px-4 py-10">
    <div class="auth-glow pointer-events-none absolute inset-0 -z-10" aria-hidden="true" />
    <div class="flex w-full max-w-[420px] flex-col items-center">
      <div v-if="davomat" class="mb-8 flex min-w-0 items-center gap-3" data-testid="auth-brand">
        <CompanyLogo v-if="organization?.logo_url" :name="organization.name" :src="organization.logo_url" :size="44" />
        <span v-else class="brand-mark size-11 shrink-0" aria-hidden="true" v-html="mark" />
        <div class="min-w-0">
          <p class="truncate text-lg font-bold leading-tight tracking-[-0.02em] text-fg">{{ organization?.name ?? editionInfo.product }}</p>
          <p v-if="organization" class="mt-0.5 truncate text-sm text-muted">{{ editionInfo.product }}</p>
        </div>
      </div>
      <div v-else class="mb-8 flex items-center gap-3">
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
      <p v-if="!davomat" class="mt-6 text-center text-sm text-muted">{{ t("shell.login.tagline") }}</p>
      <LanguageChoice :class="davomat ? 'mt-6' : 'mt-3'" />
    </div>
  </div>
</template>

<style scoped>
.auth-glow {
  background:
    radial-gradient(40rem 28rem at 15% 10%, color-mix(in srgb, var(--c-chart-1) 16%, transparent), transparent 70%),
    radial-gradient(36rem 26rem at 90% 85%, color-mix(in srgb, var(--c-chart-2) 16%, transparent), transparent 70%);
}

.brand-mark :deep(svg) {
  display: block;
  width: 100%;
  height: 100%;
}
</style>
