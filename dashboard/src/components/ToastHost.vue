<script setup lang="ts">
/** Renders toasts: bottom right on desktop, above the tab bar on phones. Mounted once by App.vue. */
import { CircleAlert, CircleCheck, Info, TriangleAlert, X } from "@lucide/vue";
import { useI18n } from "vue-i18n";

import { dismissToast, pauseToast, resumeToast, toasts, type Toast, type ToastTone } from "./useToast";

const { t } = useI18n();

const icons: Record<ToastTone, typeof Info> = { success: CircleCheck, error: CircleAlert, info: Info, warning: TriangleAlert };
const colors: Record<ToastTone, string> = { success: "text-success", error: "text-danger", info: "text-info", warning: "text-warning" };

async function act(toast: Toast): Promise<void> {
  dismissToast(toast.id);
  await toast.action?.onClick();
}
</script>

<template>
  <section
    :aria-label="t('shell.inbox.notifications')"
    class="pointer-events-none fixed inset-x-3 bottom-[calc(var(--tabbar-h)+12px+var(--safe-bottom))] z-[90] flex flex-col items-center md:inset-x-auto md:bottom-5 md:right-5 md:items-end"
  >
    <TransitionGroup name="toast" tag="ol" class="relative flex w-full flex-col gap-2 md:w-[380px]">
      <li
        v-for="toast in toasts"
        :key="toast.id"
        :role="toast.tone === 'error' ? 'alert' : 'status'"
        class="pointer-events-auto flex w-full items-start gap-3 rounded-[12px] border border-line bg-surface p-3 pr-2 shadow-pop"
        @mouseenter="pauseToast(toast.id)"
        @mouseleave="resumeToast(toast.id)"
      >
        <component :is="icons[toast.tone]" :size="18" :class="['mt-px', colors[toast.tone]]" aria-hidden="true" />
        <div class="min-w-0 flex-1">
          <p class="text-base font-semibold leading-5 text-fg">{{ toast.title }}</p>
          <p v-if="toast.description" class="mt-0.5 text-sm text-muted">{{ toast.description }}</p>
        </div>
        <button
          v-if="toast.action"
          type="button"
          class="pressable -my-0.5 shrink-0 rounded-[7px] px-2 py-1 text-sm font-semibold text-primary hover:bg-accent-soft"
          @click="act(toast)"
        >
          {{ toast.action.label }}
        </button>
        <button
          type="button"
          class="pressable -my-0.5 grid size-6 shrink-0 place-items-center rounded-[6px] text-subtle hover:bg-highlight hover:text-fg"
          :aria-label="t('common.dismiss')"
          @click="dismissToast(toast.id)"
        >
          <X :size="14" />
        </button>
      </li>
    </TransitionGroup>
  </section>
</template>
