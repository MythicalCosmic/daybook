<script setup lang="ts">
/**
 * Inside Telegram there is no login page (plan §6.5). The session keeps itself alive with its
 * refresh token (TelegramBridge), so this page shows only when that is over: the session was ended
 * (signed out on the devices list, or idle for a week) and the launch data is too old, so the way
 * back is reopening from the bot; or this Telegram has no access; or the server couldn't be reached,
 * where trying again is enough (the kept session and launch data survive the reload).
 */
import { Clock4, RefreshCw, ShieldOff, WifiOff, X } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import UiButton from "@/components/UiButton.vue";

import AuthLayout from "@/components/AuthLayout.vue";
import { closeTelegram, telegram, telegramProblem } from "./TelegramBridge";

const { t } = useI18n();
const inside = telegram().inside;
const problem = telegramProblem();
const view = computed(() => {
  if (problem === "offline") return { icon: WifiOff, title: t("shell.telegram.offlineTitle"), body: t("shell.telegram.offlineBody") };
  if (problem === "no_access") return { icon: ShieldOff, title: t("shell.telegram.noAccessTitle"), body: t("shell.telegram.noAccessBody") };
  return { icon: Clock4, title: t("shell.telegram.endedTitle"), body: t("shell.telegram.endedBody") };
});

function retry(): void {
  window.location.reload();
}
</script>

<template>
  <AuthLayout>
    <div class="flex flex-col items-center text-center" :data-problem="problem ?? 'ended'">
      <span class="grid size-12 place-items-center rounded-full bg-warning-soft text-warning" aria-hidden="true">
        <component :is="view.icon" :size="22" />
      </span>
      <h1 class="mt-4 text-lg font-semibold text-fg">{{ view.title }}</h1>
      <p class="mt-2 text-base text-muted">{{ view.body }}</p>
      <UiButton v-if="problem === 'offline'" class="mt-6" block variant="primary" :icon="RefreshCw" data-retry @click="retry">{{ t("common.retry") }}</UiButton>
      <UiButton v-if="inside" :class="problem === 'offline' ? 'mt-2' : 'mt-6'" block :variant="problem === 'offline' ? 'ghost' : 'primary'" :icon="X" @click="closeTelegram">{{ t("shell.telegram.close") }}</UiButton>
    </div>
  </AuthLayout>
</template>
