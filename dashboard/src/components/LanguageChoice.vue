<script setup lang="ts">
/**
 * The three languages as small buttons, O‘zbekcha first, for pages before anyone signs in (the
 * sign-in pages): Uzbek is the default when nothing else is known, and a Russian or English reader
 * switches here. The choice is kept in this browser; once signed in, the account's language wins.
 */
import { useI18n } from "vue-i18n";

import { LANGUAGES } from "@/api/types";
import { setLanguage } from "@/i18n";

const { t, locale } = useI18n();
</script>

<template>
  <div class="flex flex-wrap items-center justify-center gap-1" role="group" :aria-label="t('shell.topbar.language')">
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
</template>
