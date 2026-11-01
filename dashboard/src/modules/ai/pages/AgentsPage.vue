<script setup lang="ts">
/**
 * AI › Agents (the module's first page): one line on what the agents do, the engines' state, the
 * "Turn on AI" hero while AI is off, and a card per agent with its switch, numbers and settings.
 * Dictate and Smart add are one tap away from here too.
 */
import { Bot, KeyRound, Mic, Settings2, Sparkles, WalletCards } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink, useRoute, useRouter } from "vue-router";

import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import UiButton from "@/components/UiButton.vue";
import UiDrawer from "@/components/UiDrawer.vue";
import { toast } from "@/components/useToast";
import { useBreakpoints } from "@/lib/useBreakpoints";
import { patchQuery } from "@/lib/useRouteState";
import { useCompanyStore } from "@/stores/company";

import { useAgents, useAiStatus, usePatchAgent, useRunAgent } from "../api";
import AgentCard from "../components/AgentCard.vue";
import AgentDrawerBody from "../components/AgentDrawerBody.vue";
import AiHeader from "../components/AiHeader.vue";
import TurnOnCard from "../components/TurnOnCard.vue";
import { openDictation } from "../dictation";
import { aiVisibility } from "../lib";
import type { Agent } from "../types";

const { t } = useI18n();
const route = useRoute();
const router = useRouter();
const company = useCompanyStore();
const { isPhone } = useBreakpoints();

const status = useAiStatus();
const agents = useAgents();
const patch = usePatchAgent();
const run = useRunAgent();
const show = computed(() => aiVisibility(status.data.value));
const aiOn = computed(() => status.data.value?.enabled ?? false);
const canConfigure = computed(() => status.data.value?.can_configure ?? false);
const switching = ref<string | null>(null);
const starting = ref<string | null>(null);

const openKey = computed(() => {
  const value = route.query.agent;
  return typeof value === "string" ? value : null;
});
const openAgent = computed(() => agents.data.value?.find((agent) => agent.key === openKey.value) ?? null);
function openDrawer(agent: Agent): void {
  patchQuery(router, { agent: agent.key }, true);
}

async function toggle(agent: Agent, enabled: boolean): Promise<void> {
  switching.value = agent.key;
  try {
    await patch.mutateAsync({ key: agent.key, patch: { enabled } });
    toast.success(t(enabled ? "ai.agents.turnedOn" : "ai.agents.turnedOff", { name: agent.name }));
  } catch {
    // Rolled back; the reason is a toast.
  } finally {
    switching.value = null;
  }
}

async function runNow(agent: Agent): Promise<void> {
  starting.value = agent.key;
  try {
    await run.mutateAsync(agent.key);
    toast.success(t("ai.agents.started", { name: agent.name }));
  } catch {
    // The reason is a toast.
  } finally {
    starting.value = null;
  }
}

const settingsPath = computed(() => `/c/${company.currentId}/settings/ai`);
</script>

<template>
  <div class="flex min-w-0 flex-col gap-5">
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
    </template>

    <section class="flex flex-col gap-3" :aria-label="t('ai.agents.list')">
      <h2 v-if="show.turnOn" class="px-1 text-sm font-semibold text-muted">{{ t("ai.agents.preview") }}</h2>
      <div v-if="agents.isPending.value" class="grid gap-3 md:grid-cols-2" aria-hidden="true">
        <SkeletonBlock v-for="n in 4" :key="n" height="196px" radius="12px" />
      </div>
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
          @open="openDrawer(agent)"
          @toggle="(value) => toggle(agent, value)"
          @run="runNow(agent)"
        />
      </div>
      <p v-if="canConfigure && aiOn" class="px-1 text-sm text-muted">
        {{ t("ai.agents.settingsHint") }}
        <RouterLink :to="settingsPath" class="font-medium text-accent-fg hover:underline">{{ t("ai.agents.settingsLink") }}</RouterLink>
      </p>
    </section>

    <UiDrawer query-key="agent" :title="openAgent?.name ?? t('ai.agents.title')" :description="openAgent?.schedule" size="md">
      <template v-if="openAgent" #header-actions>
        <ToggleSwitch
          class="mr-1"
          :model-value="aiOn && openAgent.enabled"
          :loading="switching === openAgent.key"
          :disabled="!canConfigure || !aiOn || (!openAgent.available && !openAgent.enabled)"
          :label="t('ai.agents.onLabel')"
          @update:model-value="(value: boolean) => openAgent && toggle(openAgent, value)"
        />
      </template>
      <AgentDrawerBody v-if="openAgent" :agent="openAgent" :can-configure="canConfigure" :ai-on="aiOn" />
      <div v-else-if="agents.isPending.value" class="flex flex-col gap-3 p-5" aria-hidden="true">
        <SkeletonBlock v-for="n in 3" :key="n" height="56px" radius="10px" />
      </div>
      <EmptyState v-else class="my-10" :icon="Bot" :title="t('ai.agents.notFound')" />
      <template v-if="openAgent && (openAgent.key === 'deadline_watcher' || openAgent.key === 'morning_plan' || openAgent.next_run_at) && canConfigure && aiOn && openAgent.enabled" #footer>
        <UiButton :loading="starting === openAgent.key" :disabled="openAgent.running" @click="openAgent && runNow(openAgent)">{{ openAgent.running ? t("ai.agents.working") : t("ai.agents.runNow") }}</UiButton>
      </template>
    </UiDrawer>
  </div>
</template>
