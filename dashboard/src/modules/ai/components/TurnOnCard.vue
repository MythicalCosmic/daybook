<script setup lang="ts">
/**
 * "Turn on AI": what the agents will do, the terms in one sentence, and the switch. Owners and
 * ai.configure people see it while AI is off (the Agents page hero, Settings › AI). Turning it on
 * adds "ai" to the company's modules and starts the agents that are on by default.
 */
import { AlarmClock, Mic, Sparkles, Sunrise } from "@lucide/vue";
import { useQueryClient } from "@tanstack/vue-query";
import { ref } from "vue";
import { useI18n } from "vue-i18n";

import CheckBox from "@/components/CheckBox.vue";
import UiButton from "@/components/UiButton.vue";
import { toast } from "@/components/useToast";
import { useBreakpoints } from "@/lib/useBreakpoints";
import { useSessionStore } from "@/stores/session";

import { aiApi, aiKeys, useCompanyId } from "../api";

withDefaults(defineProps<{ compact?: boolean }>(), { compact: false });
const emit = defineEmits<{ enabled: [] }>();

const { t } = useI18n();
const { isPhone } = useBreakpoints();
const cid = useCompanyId();
const client = useQueryClient();
const session = useSessionStore();
const accepted = ref(false);
const saving = ref(false);
const showTermsError = ref(false);

const points = [
  { icon: Mic, key: "ai.turnOn.point.voice" },
  { icon: AlarmClock, key: "ai.turnOn.point.deadlines" },
  { icon: Sunrise, key: "ai.turnOn.point.morning" },
];

async function turnOn(): Promise<void> {
  if (!accepted.value) {
    showTermsError.value = true;
    return;
  }
  saving.value = true;
  try {
    const status = await aiApi.enable(cid.value);
    client.setQueryData(aiKeys.status(cid.value), status);
    void client.invalidateQueries({ queryKey: aiKeys.all(cid.value) });
    // "ai" is now among the company's modules: the shell's Ask AI and every AI surface follow.
    void session.loadMe().catch(() => undefined);
    toast.success(t("ai.turnOn.done"), { description: t("ai.turnOn.doneBody") });
    emit("enabled");
  } catch {
    // The reason comes as a toast from the HTTP layer.
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <section
    :class="[
      'ai-hero relative overflow-hidden rounded-card border border-line',
      compact ? 'p-4 md:p-5' : 'p-5 md:p-7',
    ]"
    data-testid="ai-turn-on"
  >
    <div :class="['relative flex flex-col gap-5', !compact && 'lg:flex-row lg:items-start lg:gap-10']">
      <div class="flex min-w-0 flex-1 flex-col gap-3">
        <span class="grid size-11 place-items-center rounded-full bg-primary text-on-primary shadow-raised" aria-hidden="true">
          <Sparkles :size="22" />
        </span>
        <h2 :class="['font-display text-fg', compact ? 'text-lg' : 'text-xl md:text-2xl']">{{ t("ai.turnOn.title") }}</h2>
        <p class="max-w-[560px] text-base text-muted">{{ t("ai.turnOn.body") }}</p>
      </div>
      <div class="flex min-w-0 flex-1 flex-col gap-4">
        <ul class="flex flex-col gap-2.5">
          <li v-for="point in points" :key="point.key" class="flex items-start gap-3">
            <span class="grid size-8 shrink-0 place-items-center rounded-full bg-surface text-accent-fg shadow-xs" aria-hidden="true">
              <component :is="point.icon" :size="16" />
            </span>
            <span class="pt-1.5 text-base text-fg">{{ t(point.key) }}</span>
          </li>
        </ul>
        <div class="rounded-[10px] bg-surface/80 p-3 ring-1 ring-line">
          <CheckBox v-model="accepted" :label="t('ai.turnOn.terms')" :description="t('ai.turnOn.termsBody')" :invalid="showTermsError && !accepted" data-testid="ai-terms" />
          <p v-if="showTermsError && !accepted" class="mt-2 text-sm text-danger" role="alert">{{ t("ai.turnOn.termsNeeded") }}</p>
        </div>
        <div class="flex flex-wrap items-center gap-3">
          <UiButton variant="primary" :size="isPhone ? 'lg' : 'md'" :icon="Sparkles" :loading="saving" :block="isPhone" data-testid="ai-enable" @click="turnOn">
            {{ t("ai.turnOn.button") }}
          </UiButton>
          <span class="text-sm text-muted">{{ t("ai.turnOn.later") }}</span>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.ai-hero {
  background:
    radial-gradient(120% 140% at 0% 0%, color-mix(in srgb, var(--c-primary) 16%, transparent) 0%, transparent 55%),
    radial-gradient(90% 120% at 100% 100%, color-mix(in srgb, var(--c-success) 12%, transparent) 0%, transparent 60%),
    var(--c-accent-soft);
}
:global([data-theme="dark"]) .ai-hero {
  background:
    radial-gradient(120% 140% at 0% 0%, color-mix(in srgb, var(--c-primary) 22%, transparent) 0%, transparent 55%),
    radial-gradient(90% 120% at 100% 100%, color-mix(in srgb, var(--c-success) 10%, transparent) 0%, transparent 60%),
    var(--c-surface);
}
</style>
