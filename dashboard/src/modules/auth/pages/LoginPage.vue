<script setup lang="ts">
/**
 * /login (W0 placeholder; package A replaces it with the QR code, "Open in Telegram" and number
 * matching, plan §6.2 and §7.1). It explains how to get in; in development it links to the
 * developer sign-in.
 */
import { Send, Terminal } from "@lucide/vue";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";

import AuthLayout from "@/components/AuthLayout.vue";
import UiButton from "@/components/UiButton.vue";

const { t } = useI18n();
const route = useRoute();
const dev = import.meta.env.DEV;
</script>

<template>
  <AuthLayout>
    <div class="flex flex-col items-center text-center">
      <span class="grid size-12 place-items-center rounded-full bg-info-soft text-info" aria-hidden="true">
        <Send :size="22" />
      </span>
      <h1 class="mt-4 text-lg font-semibold text-fg">{{ t("auth.login.title") }}</h1>
      <p class="mt-2 text-base text-muted">{{ t("auth.login.body") }}</p>
      <UiButton v-if="dev" class="mt-6" block :icon="Terminal" :to="{ path: '/dev/login', query: route.query }">{{ t("auth.login.dev") }}</UiButton>
    </div>
  </AuthLayout>
</template>
