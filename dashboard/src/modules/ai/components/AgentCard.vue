<script setup lang="ts">
/**
 * One agent: what it does and when, its switch, how much it did today and this week, when it last
 * ran and runs next, and "Run now" for the scheduled ones. A soft shimmer runs along the top while
 * it works. The whole card opens the agent's own page (the title is the link, stretched); its
 * switch, "Run now" and its chibi (AgentChibi.vue, where an icon would be) take their own taps.
 */
import { ChevronRight, LoaderCircle, Lock, Play, ScanEye } from "@lucide/vue";
import { computed, useId } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink } from "vue-router";

import ToggleSwitch from "@/components/ToggleSwitch.vue";
import UiBadge from "@/components/UiBadge.vue";
import UiButton from "@/components/UiButton.vue";
import { useBreakpoints } from "@/lib/useBreakpoints";
import { useFormat } from "@/lib/useFormat";
import { useNow } from "@/lib/useNow";
import { useCompanyStore } from "@/stores/company";

import { isScheduled } from "../agentPage";
import type { Agent } from "../types";
import AgentChibi from "./AgentChibi.vue";

const props = withDefaults(defineProps<{ agent: Agent; canConfigure: boolean; aiOn: boolean; switching?: boolean; starting?: boolean }>(), {
  switching: false,
  starting: false,
});
const emit = defineEmits<{ toggle: [value: boolean]; run: [] }>();

const { t } = useI18n();
const fmt = useFormat();
const now = useNow();
const switchId = useId();
const { isPhone } = useBreakpoints();
const company = useCompanyStore();

const scheduled = computed(() => isScheduled(props.agent));
const page = computed(() => ({ name: "ai.agent", params: { companyId: company.currentId ?? 0, key: props.agent.key } }));
const on = computed(() => props.aiOn && props.agent.enabled);
const blocked = computed(() => !props.agent.available && props.agent.unavailable_reason !== "" && props.agent.unavailable_reason !== "ai_off");
const switchDisabled = computed(() => !props.canConfigure || !props.aiOn || (blocked.value && !props.agent.enabled));
/** "Sends task photos to Claude", unless the agent's own description already says so. */
const photoNote = computed(() => props.agent.key === "photo_checker" && !props.agent.description.includes("Claude"));
const lastRun = computed(() => (props.agent.last_run_at ? fmt.relative(props.agent.last_run_at, now.value) : null));
const nextRun = computed(() => (props.agent.next_run_at && on.value ? fmt.relative(props.agent.next_run_at, now.value) : null));
</script>

<template>
  <article
    :class="[
      'ai-agent-card group relative flex min-w-0 flex-col gap-3 overflow-hidden rounded-card border bg-surface p-4 transition-[border-color,box-shadow] duration-150 md:p-5',
      on ? 'border-line hover:border-line-strong hover:shadow-raised' : 'border-line',
      agent.running && 'is-running',
    ]"
    :data-agent="agent.key"
  >
    <span v-if="agent.running" class="ai-shimmer pointer-events-none absolute inset-x-0 top-0 h-[3px]" aria-hidden="true" />
    <div class="flex items-start gap-3">
      <AgentChibi class="relative z-[1] -my-1 shrink-0" :agent-key="agent.key" :name="agent.name" :on="on" :running="agent.running" />
      <div class="min-w-0 flex-1">
        <h3 class="text-md font-semibold leading-6 text-fg">
          <!-- The stretched link: a tap anywhere on the card opens the agent's page. -->
          <RouterLink :to="page" class="ai-stretch inline-flex items-center gap-0.5 text-left outline-none" :aria-label="t('ai.agents.open', { name: agent.name })" :data-testid="`agent-open-${agent.key}`">
            {{ agent.name }}<ChevronRight :size="16" class="shrink-0 text-subtle transition-transform duration-150 group-hover:translate-x-0.5" aria-hidden="true" />
          </RouterLink>
        </h3>
        <p class="text-sm text-muted">{{ agent.schedule }}</p>
      </div>
      <label :for="switchId" class="sr-only">{{ t("ai.agents.switch", { name: agent.name }) }}</label>
      <ToggleSwitch
        :id="switchId"
        class="relative z-[1] -m-2.5 p-2.5"
        :model-value="on"
        :loading="switching"
        :disabled="switchDisabled"
        :data-testid="`agent-switch-${agent.key}`"
        @update:model-value="(value: boolean) => emit('toggle', value)"
      />
    </div>

    <p class="text-base leading-[1.45] text-fg/90" :class="!on && 'text-muted'">{{ agent.description }}</p>

    <div v-if="blocked || photoNote" class="flex flex-wrap gap-1.5">
      <UiBadge v-if="agent.unavailable_reason === 'needs_claude'" tone="warning" size="md"><Lock :size="12" class="mr-1" aria-hidden="true" />{{ t("ai.agents.needsClaude") }}</UiBadge>
      <UiBadge v-else-if="agent.unavailable_reason === 'needs_speech'" tone="warning" size="md"><Lock :size="12" class="mr-1" aria-hidden="true" />{{ t("ai.agents.needsSpeech") }}</UiBadge>
      <UiBadge v-if="photoNote" tone="info" size="md"><ScanEye :size="12" class="mr-1" aria-hidden="true" />{{ t("ai.agents.sendsPhotos") }}</UiBadge>
    </div>

    <div class="mt-auto flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-line pt-3 text-sm">
      <span class="flex items-baseline gap-1 text-muted">
        <span>{{ t("ai.agents.today") }}</span><span class="num font-semibold text-fg">{{ agent.stats.today }}</span>
        <span class="px-1 text-subtle" aria-hidden="true">·</span>
        <span>{{ t("ai.agents.week") }}</span><span class="num font-semibold text-fg">{{ agent.stats.week }}</span>
      </span>
      <span v-if="agent.running" class="inline-flex items-center gap-1.5 font-medium text-accent-fg" role="status">
        <LoaderCircle :size="14" class="animate-spin" aria-hidden="true" />{{ t("ai.agents.working") }}
      </span>
      <span v-else-if="nextRun" class="num text-muted">{{ t("ai.agents.next", { when: nextRun }) }}</span>
      <span v-else-if="lastRun" class="num text-muted">{{ t("ai.agents.last", { when: lastRun }) }}</span>
      <UiButton
        v-if="scheduled && canConfigure && on && !agent.running"
        class="relative z-[1] ml-auto"
        variant="ghost"
        :size="isPhone ? 'lg' : 'sm'"
        :icon="Play"
        :loading="starting"
        :data-testid="`agent-run-${agent.key}`"
        @click="emit('run')"
      >
        {{ t("ai.agents.runNow") }}
      </UiButton>
    </div>
  </article>
</template>

<style scoped>
.ai-stretch::after {
  content: "";
  position: absolute;
  inset: 0;
  border-radius: inherit;
}
.ai-stretch:focus-visible::after {
  box-shadow: inset 0 0 0 2px var(--c-ring);
}
.ai-agent-card {
  border-radius: var(--r-card);
}
.ai-shimmer {
  background: linear-gradient(90deg, transparent 0%, var(--c-primary) 35%, color-mix(in srgb, var(--c-primary) 30%, var(--c-success)) 65%, transparent 100%);
  background-size: 200% 100%;
  animation: ai-sweep 1.4s linear infinite;
}
@keyframes ai-sweep {
  from {
    background-position: 100% 0;
  }
  to {
    background-position: -100% 0;
  }
}
</style>
