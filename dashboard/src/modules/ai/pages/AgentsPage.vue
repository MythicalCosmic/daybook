<script setup lang="ts">
/**
 * AI › Agents (the module's first page): one line on what the agents do, the engines' state, the
 * "Turn on AI" hero while AI is off, and a card per agent with its switch and numbers; a card opens
 * the agent's own page (AgentPage.vue). Dictate and Smart add are one tap away from here too.
 * While AI is on, Claude's little helper lives in a strip at the top and wanders over the cards
 * (AiBuddyStage.vue), and every agent card has its own chibi. The agents an owner made in their own
 * words are cards like the others, in the colour they picked; who may set up AI finds "New agent"
 * at the end of the grid (CustomAgentDialog.vue, briefs/v6-k.md).
 */
import { Bot, KeyRound, Mic, Plus, Settings2, Sparkles, WalletCards } from "@lucide/vue";
import { computed, defineAsyncComponent, ref, useId } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink } from "vue-router";

import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import UiButton from "@/components/UiButton.vue";
import { useBreakpoints } from "@/lib/useBreakpoints";
import { useCompanyStore } from "@/stores/company";

import { useAgentActions } from "../agentActions";
import { useAgents, useAiStatus } from "../api";
import AgentCard from "../components/AgentCard.vue";
import AiBuddyStage from "../components/AiBuddyStage.vue";
import { useBuddyCues } from "../components/buddyCues";
import { buddyEverywhere } from "../components/buddyPrefs";
import AiHeader from "../components/AiHeader.vue";
import TurnOnCard from "../components/TurnOnCard.vue";
import { agentsLeft, CUSTOM_MAX } from "../customAgent";
import { openDictation } from "../dictation";
import { aiVisibility, isMissingEndpoint } from "../lib";

// The New agent dialog loads when it is first opened.
const CustomAgentDialog = defineAsyncComponent(() => import("../components/CustomAgentDialog.vue"));

const { t } = useI18n();
const company = useCompanyStore();
const { isPhone } = useBreakpoints();

const status = useAiStatus();
const agents = useAgents();
const show = computed(() => aiVisibility(status.data.value));
const aiOn = computed(() => status.data.value?.enabled ?? false);
const canConfigure = computed(() => status.data.value?.can_configure ?? false);
const { switching, starting, toggle, runNow } = useAgentActions();

const settingsPath = computed(() => `/c/${company.currentId}/settings/ai`);

// The agents an owner makes in their own words: at most CUSTOM_MAX, made by who may set up AI.
const left = computed(() => agentsLeft(agents.data.value));
const creating = ref(false);
const dialogWanted = ref(false);
function newAgent(): void {
  dialogWanted.value = true;
  creating.value = true;
}
// The helpers react to what happens in the company: voice notes, late and finished tasks.
useBuddyCues(aiOn);
const everywhereId = useId();

/** What Claude's helper says next to itself: the agent at work now, else today's count. */
const runningAgent = computed(() => agents.data.value?.find((agent) => agent.running) ?? null);
const doneToday = computed(() => (agents.data.value ?? []).reduce((sum, agent) => sum + (agent.stats?.today ?? 0), 0));
const buddyLine = computed(() => {
  if (runningAgent.value) return t("ai.buddy.doing", { name: runningAgent.value.name });
  if (doneToday.value > 0) return `${t("ai.agents.today")}: ${t("ai.kpi.actions", { n: doneToday.value }, doneToday.value)}`;
  return t("ai.buddy.ready");
});
</script>

<template>
  <div class="relative flex min-w-0 flex-col gap-5">
    <AiHeader :title="t('ai.agents.title')" :description="t('ai.agents.description')" :status="status.data.value">
      <template v-if="show.dictate || show.smartAdd" #actions>
        <UiButton v-if="show.smartAdd" :size="isPhone ? 'lg' : 'md'" :icon="Sparkles" class="max-sm:flex-1" data-testid="ai-smart-add" @click="openDictation('text')">
          {{ t("ai.dictate.smartAdd") }}
        </UiButton>
        <UiButton v-if="show.dictate" variant="primary" :size="isPhone ? 'lg' : 'md'" :icon="Mic" class="max-sm:flex-1" data-testid="ai-dictate" @click="openDictation('voice')">
          {{ t("ai.dictate.button") }}
        </UiButton>
      </template>
    </AiHeader>

    <div v-if="status.isPending.value" class="flex flex-col gap-4" aria-hidden="true">
      <SkeletonBlock height="64px" radius="12px" />
    </div>
    <ErrorState v-else-if="status.isError.value" :error="status.error.value" :retry="() => status.refetch()" />
    <template v-else-if="status.data.value">
      <TurnOnCard v-if="show.turnOn" />
      <InlineAlert v-else-if="show.offNotice" tone="neutral" :icon="Bot" :title="t('ai.off.title')" :description="t('ai.off.body')" />

      <InlineAlert v-if="aiOn && show.keyNotice" tone="info" :icon="KeyRound" :title="t('ai.key.title')" :description="t('ai.key.body')" data-testid="ai-key-notice" />
      <InlineAlert v-if="aiOn && status.data.value.claude === 'budget_reached'" tone="warning" :icon="WalletCards" :title="t('ai.budget.reachedTitle')" :description="t('ai.budget.reachedBody')">
        <template v-if="canConfigure" #actions>
          <UiButton size="sm" :to="settingsPath" :icon="Settings2">{{ t("ai.budget.raise") }}</UiButton>
        </template>
      </InlineAlert>

      <AiBuddyStage v-if="aiOn" :mood="runningAgent ? 'busy' : 'on'" :size="isPhone ? 60 : 72">
        <div class="flex items-center gap-3">
          <div class="min-w-0 flex-1">
            <p class="text-md font-semibold leading-6 text-fg">{{ runningAgent ? t("ai.buddy.busy") : t("ai.buddy.onDuty") }}</p>
            <p class="text-sm text-muted">{{ buddyLine }}</p>
          </div>
          <div class="flex shrink-0 flex-col items-end gap-1 sm:flex-row sm:items-center sm:gap-2">
            <label :for="everywhereId" class="text-xs text-muted sm:text-sm">{{ t("ai.buddy.everywhere") }}</label>
            <ToggleSwitch :id="everywhereId" v-model="buddyEverywhere" data-testid="ai-buddy-everywhere" />
          </div>
        </div>
      </AiBuddyStage>
    </template>

    <section class="flex flex-col gap-3" :aria-label="t('ai.agents.list')">
      <h2 v-if="show.turnOn" class="px-1 text-sm font-semibold text-muted">{{ t("ai.agents.preview") }}</h2>
      <div v-if="agents.isPending.value" class="grid gap-3 md:grid-cols-2" aria-hidden="true">
        <SkeletonBlock v-for="n in 4" :key="n" height="196px" radius="12px" />
      </div>
      <EmptyState
        v-else-if="agents.isError.value && isMissingEndpoint(agents.error.value)"
        class="ui-card py-10"
        :icon="Bot"
        :title="t('ai.agents.comingTitle')"
        :description="t('ai.agents.comingBody')"
        data-testid="ai-agents-coming"
      />
      <ErrorState v-else-if="agents.isError.value" :error="agents.error.value" :retry="() => agents.refetch()" />
      <EmptyState v-else-if="!agents.data.value?.length" :icon="Bot" :title="t('ai.agents.empty')" :description="t('ai.agents.emptyBody')" />
      <div v-else class="grid gap-3 md:grid-cols-2">
        <AgentCard
          v-for="agent in agents.data.value"
          :key="agent.key"
          :agent="agent"
          :can-configure="canConfigure"
          :ai-on="aiOn"
          :switching="switching === agent.key"
          :starting="starting === agent.key"
          @toggle="(value) => toggle(agent, value)"
          @run="runNow(agent)"
        />
        <button
          v-if="canConfigure && aiOn"
          type="button"
          class="flex min-h-[176px] min-w-0 flex-col items-center justify-center gap-2 rounded-card border-2 border-dashed border-line-strong bg-surface-2/30 p-5 text-center transition-[border-color,background-color] hover:border-accent-fg/50 hover:bg-surface-2/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-60"
          :disabled="left === 0"
          data-testid="agent-new"
          @click="newAgent"
        >
          <span class="flex size-11 items-center justify-center rounded-full bg-surface text-accent-fg shadow-raised" aria-hidden="true"><Plus :size="22" /></span>
          <span class="text-md font-semibold text-fg">{{ t("ai.custom.new") }}</span>
          <span class="max-w-xs text-sm text-muted">{{ left ? t("ai.custom.newBody") : t("ai.custom.full", { max: CUSTOM_MAX }) }}</span>
          <span class="num text-xs text-subtle">{{ t("ai.custom.count", { n: CUSTOM_MAX - left, max: CUSTOM_MAX }) }}</span>
        </button>
      </div>
      <CustomAgentDialog v-if="dialogWanted" v-model:open="creating" />
      <p v-if="canConfigure && aiOn" class="px-1 text-sm text-muted">
        {{ t("ai.agents.settingsHint") }}
        <RouterLink :to="settingsPath" class="font-medium text-accent-fg hover:underline">{{ t("ai.agents.settingsLink") }}</RouterLink>
      </p>
    </section>
  </div>
</template>
