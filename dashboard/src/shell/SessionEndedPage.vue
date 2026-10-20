<script setup lang="ts">
/**
 * Inside Telegram there is no login page and no refresh cookie (plan §6.5): when initData can no
 * longer sign in (too old, or access was removed), the only way back is reopening from the bot.
 */
import { Clock4, X } from "@lucide/vue";
import { useI18n } from "vue-i18n";

import UiButton from "@/components/UiButton.vue";

import AuthLayout from "@/components/AuthLayout.vue";
import { closeTelegram, telegram } from "./TelegramBridge";

const { t } = useI18n();
const inside = telegram().inside;
</script>

<template>
  <AuthLayout>
    <div class="flex flex-col items-center text-center">
      <span class="grid size-12 place-items-center rounded-full bg-warning-soft text-warning" aria-hidden="true">
        <Clock4 :size="22" />
      </span>
      <h1 class="mt-4 text-lg font-semibold text-fg">{{ t("shell.telegram.endedTitle") }}</h1>
      <p class="mt-2 text-base text-muted">{{ t("shell.telegram.endedBody") }}</p>
      <UiButton v-if="inside" class="mt-6" block variant="primary" :icon="X" @click="closeTelegram">{{ t("shell.telegram.close") }}</UiButton>
    </div>
  </AuthLayout>
</template>
