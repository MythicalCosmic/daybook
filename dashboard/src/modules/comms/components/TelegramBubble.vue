<script setup lang="ts">
/**
 * How the announcement looks in Telegram: the bot's message bubble on a chat background, with the
 * header the bot adds, the formatted text (spoilers blurred until hovered) and the "I've read it"
 * button. `text` is Telegram HTML; it is rendered through `toDisplay`, which keeps only the
 * allowed tags and escapes everything else.
 */
import { CheckCheck } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import { toDisplay } from "../telegramHtml";

const props = withDefaults(defineProps<{ text: string; author?: string; time?: string; reminder?: boolean }>(), { author: "", time: "", reminder: false });

const { t } = useI18n();
const html = computed(() => toDisplay(props.text));
</script>

<template>
  <div class="chat rounded-[14px] p-4">
    <div class="bubble max-w-[420px] rounded-[16px] rounded-bl-[6px] px-3.5 pb-2 pt-2.5 shadow-xs">
      <p class="mb-1.5 text-[13px] font-semibold text-[var(--tg-accent)]">
        📣 {{ reminder ? t("comms.bubble.reminder", { name: author || t("comms.bubble.manager") }) : t("comms.bubble.header", { name: author || t("comms.bubble.manager") }) }}
      </p>
      <!-- eslint-disable-next-line vue/no-v-html -- toDisplay keeps only Telegram's tags and escapes text -->
      <div v-if="text" class="message text-[14.5px] leading-[1.45] text-fg" v-html="html" />
      <p v-else class="text-[14.5px] italic text-subtle">{{ t("comms.bubble.empty") }}</p>
      <p class="mt-1 flex items-center justify-end gap-1 text-[11px] text-subtle">{{ time }}<CheckCheck :size="13" class="text-[var(--tg-accent)]" aria-hidden="true" /></p>
    </div>
    <div class="mt-1 max-w-[420px] rounded-[12px] bg-[color-mix(in_srgb,var(--c-surface)_72%,transparent)] py-2 text-center text-[13px] font-semibold text-[var(--tg-accent)] backdrop-blur">
      ✅ {{ t("comms.bubble.read") }}
    </div>
  </div>
</template>

<style scoped>
.chat {
  --tg-accent: var(--c-info);
  background:
    radial-gradient(circle at 20% 20%, color-mix(in srgb, var(--c-success) 10%, transparent) 0, transparent 40%),
    radial-gradient(circle at 80% 70%, color-mix(in srgb, var(--c-info) 10%, transparent) 0, transparent 45%),
    color-mix(in srgb, var(--c-surface-2) 85%, var(--c-canvas));
}
.bubble {
  background: var(--c-surface);
  word-break: break-word;
}
.message :deep(a) {
  color: var(--tg-accent);
  text-decoration: underline;
  text-underline-offset: 2px;
}
.message :deep(code) {
  padding: 0 4px;
  border-radius: 4px;
  background: var(--c-surface-2);
  font-family: var(--font-mono);
  font-size: 0.9em;
}
.message :deep(.tg-spoiler) {
  border-radius: 4px;
  color: transparent;
  background: repeating-linear-gradient(135deg, color-mix(in srgb, var(--c-text) 22%, transparent) 0 2px, color-mix(in srgb, var(--c-text) 10%, transparent) 2px 4px);
  transition: color var(--dur-fade) var(--ease-standard);
}
.message :deep(.tg-spoiler:hover) {
  color: inherit;
  background: color-mix(in srgb, var(--c-text) 8%, transparent);
}
</style>
