<script setup lang="ts">
/** A path nothing answers. Inside a company it keeps the shell; at the top level it stands alone. */
import { ArrowLeft } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import UiButton from "@/components/UiButton.vue";
import { useCompanyStore } from "@/stores/company";

const { t } = useI18n();
const route = useRoute();
const router = useRouter();
const company = useCompanyStore();

const standalone = computed(() => route.name === "not-found");
const home = computed(() => (company.currentId ? `/c/${company.currentId}` : "/"));
const canGoBack = computed(() => typeof window !== "undefined" && !!(window.history.state as { back?: string } | null)?.back);
</script>

<template>
  <div :class="['grid place-items-center px-6', standalone ? 'min-h-dvh bg-canvas' : 'min-h-[60vh]']">
    <div class="flex max-w-[440px] flex-col items-center text-center">
      <p class="font-display text-[88px] leading-none text-primary" aria-hidden="true">404</p>
      <h1 class="mt-4 text-xl font-semibold text-fg">{{ t("shell.notFound.title") }}</h1>
      <p class="mt-2 text-base text-muted">{{ t("shell.notFound.body") }}</p>
      <div class="mt-6 flex flex-wrap justify-center gap-2">
        <UiButton v-if="canGoBack" :icon="ArrowLeft" @click="router.back()">{{ t("common.back") }}</UiButton>
        <UiButton variant="primary" :to="home">{{ t("shell.notFound.home") }}</UiButton>
      </div>
    </div>
  </div>
</template>
