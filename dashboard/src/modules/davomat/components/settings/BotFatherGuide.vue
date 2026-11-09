<script setup lang="ts">
/**
 * How to make the organization's own bot, step by step: open @BotFather, send /newbot, a name, a
 * username ending in "bot", copy the token, paste it here. "/newbot" and the example username
 * copy with one click.
 */
import { Check, Copy, ExternalLink } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import UiButton from "@/components/UiButton.vue";

const { t } = useI18n();
const copied = ref<string | null>(null);

async function copy(text: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text);
    copied.value = text;
    setTimeout(() => (copied.value = copied.value === text ? null : copied.value), 1800);
  } catch {
    // No clipboard: the text is right there to type.
  }
}

const steps = computed(() => [
  { key: "open", text: t("davomat.telegram.guide.step1"), link: "https://t.me/BotFather" },
  { key: "newbot", text: t("davomat.telegram.guide.step2"), code: "/newbot" },
  { key: "name", text: t("davomat.telegram.guide.step3") },
  { key: "username", text: t("davomat.telegram.guide.step4"), code: t("davomat.telegram.guide.example") },
  { key: "token", text: t("davomat.telegram.guide.step5") },
]);
</script>

<template>
  <ol class="flex flex-col" data-guide>
    <li v-for="(step, index) in steps" :key="step.key" class="relative flex gap-3.5 pb-5 last:pb-0">
      <!-- The line that joins the steps -->
      <span v-if="index < steps.length - 1" class="absolute bottom-0 left-[13px] top-8 w-px bg-line" aria-hidden="true" />
      <span class="relative z-[1] grid size-7 shrink-0 place-items-center rounded-full border border-line bg-surface text-xs font-semibold tabular-nums text-fg shadow-xs">{{ index + 1 }}</span>
      <div class="min-w-0 flex-1 pt-[3px]">
        <p class="text-base text-fg">{{ step.text }}</p>
        <div v-if="step.link || step.code" class="mt-2 flex flex-wrap items-center gap-2">
          <UiButton v-if="step.link" size="sm" variant="secondary" :icon-right="ExternalLink" :href="step.link" target="_blank">{{ t("davomat.telegram.guide.openBotFather") }}</UiButton>
          <button
            v-if="step.code"
            type="button"
            class="pressable inline-flex h-7 items-center gap-2 rounded-[7px] border border-line bg-surface-2 pl-2.5 pr-2 font-mono text-sm text-fg hover:border-line-strong"
            :aria-label="t('davomat.telegram.guide.copy', { text: step.code })"
            @click="copy(step.code)"
          >
            {{ step.code }}
            <Check v-if="copied === step.code" :size="13" class="text-success" />
            <Copy v-else :size="13" class="text-subtle" />
          </button>
        </div>
      </div>
    </li>
  </ol>
</template>
