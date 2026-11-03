<script setup lang="ts">
/**
 * AI › Agents › one agent (briefs/v5-agent-page.md): its own page, opened from its card. At the
 * top its name, what it does, how it is (working, on, off, waiting for a Claude key), its switch
 * and "Run now"; then the page's main thing, its scene — the agent's chibi at its computer, the
 * screen showing what it did lately, asleep while it is off, the room dark at night; its numbers
 * (last run, next run, tokens and cost this month); and its sections, named in the URL (`?tab=`):
 * what it did, its internal log (runs and Claude calls), tokens, what comes next, its settings.
 * Read-only without ai.configure (and the money hidden, never shown as 0).
 */
import { Activity, Bot, CalendarClock, Coins, History, Play, Settings2 } from "@lucide/vue";
import { computed, useId } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";

import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import PageHeader from "@/components/PageHeader.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import UiBadge from "@/components/UiBadge.vue";
import UiButton from "@/components/UiButton.vue";
import { isApiError } from "@/api/http";
import { useBreakpoints } from "@/lib/useBreakpoints";
import { useFormat } from "@/lib/useFormat";
import { useNow } from "@/lib/useNow";
import { usePageTitle } from "@/lib/usePageTitle";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useCompanyStore } from "@/stores/company";

import { useAgentActions } from "../agentActions";
import { AGENT_TABS, agentKpis, agentStatus, isNight, isScheduled, sceneOf, screenLines, type AgentTab } from "../agentPage";
import { useActivityFeed, useAgent, useAiStatus } from "../api";
import ActivityFeed from "../components/ActivityFeed.vue";
import AgentKpis from "../components/AgentKpis.vue";
import AgentLog from "../components/AgentLog.vue";
import AgentScenePlaceholder from "../components/AgentScenePlaceholder.vue";
import AgentSectionTabs, { type SectionTab } from "../components/AgentSectionTabs.vue";
import AgentSettings from "../components/AgentSettings.vue";
import AgentUpcoming from "../components/AgentUpcoming.vue";
import AgentUsage from "../components/AgentUsage.vue";
import { buddyVariant } from "../lib";

const { t } = useI18n();
const fmt = useFormat();
const route = useRoute();
const company = useCompanyStore();
const now = useNow();
const { isPhone } = useBreakpoints();

const key = computed(() => String(route.params.key ?? ""));
const status = useAiStatus();
const query = useAgent(key);
const agent = computed(() => query.data.value ?? null);
const feed = useActivityFeed(key, { limit: 30 });
const { switching, starting, toggle, runNow } = useAgentActions();
// The breadcrumb and the browser tab read the agent's name.
usePageTitle(() => agent.value?.name);

const aiOn = computed(() => status.data.value?.enabled ?? false);
const canConfigure = computed(() => status.data.value?.can_configure ?? false);
const claude = computed(() => status.data.value?.claude ?? null);
const on = computed(() => aiOn.value && (agent.value?.enabled ?? false));
const notFound = computed(() => isApiError(query.error.value) && query.error.value.status === 404);

const pill = computed(() => (agent.value ? agentStatus(agent.value, aiOn.value) : null));
const switchDisabled = computed(() => !agent.value || !canConfigure.value || !aiOn.value || (!agent.value.available && !agent.value.enabled));
const runnable = computed(() => !!agent.value && isScheduled(agent.value) && canConfigure.value && on.value && agent.value.available);

// The scene: its state, what is on its screen, day or night in the company.
const scene = computed(() => (agent.value ? sceneOf(agent.value, aiOn.value) : "asleep"));
const lines = computed(() => (agent.value ? screenLines(feed.items.value, agent.value.runs, t) : []));
const night = computed(() => isNight(company.timezone, now.value));
const sceneLabel = computed(() => (agent.value ? t("ai.agent.scene.label", { name: agent.value.name, state: t(`ai.agent.scene.${scene.value}`) }) : ""));

const kpis = computed(() => (agent.value ? agentKpis(agent.value, { t, lang: fmt.lang.value, timeZone: company.timezone, now: now.value, aiOn: aiOn.value }) : []));

const tab = useRouteState("tab", rs.enum<AgentTab>(AGENT_TABS, "done"));
const panelId = useId();
const SECTION_ICONS = { done: Activity, log: History, tokens: Coins, next: CalendarClock, settings: Settings2 } as const;
const tabs = computed<SectionTab<AgentTab>[]>(() =>
  AGENT_TABS.map((id) => ({ id, label: t(`ai.agent.tab.${id}`), icon: SECTION_ICONS[id], count: id === "next" && agent.value?.upcoming.length ? agent.value.upcoming.length : undefined })),
);
const switchId = useId();
const agentsLink = computed(() => ({ name: "ai.agents", params: { companyId: company.currentId ?? 0 } }));
</script>

<template>
  <div class="flex min-w-0 flex-col gap-4 md:gap-5">
    <PageHeader :title="agent?.name ?? t('ai.agent.title')" :description="agent?.description" :back="agentsLink" :back-label="t('ai.agents.title')">
      <template v-if="agent" #actions>
        <div class="flex h-10 items-center gap-2.5 rounded-button border border-line bg-surface pl-3 pr-2 max-sm:flex-1" data-testid="agent-switch">
          <label :for="switchId" class="flex-1 cursor-pointer text-sm font-medium text-fg">{{ t("ai.agents.onLabel") }}</label>
          <ToggleSwitch
            :id="switchId"
            :model-value="on"
            :loading="switching === agent.key"
            :disabled="switchDisabled"
            @update:model-value="(value: boolean) => agent && toggle(agent, value)"
          />
        </div>
        <UiButton
          v-if="runnable"
          variant="primary"
          :size="isPhone ? 'lg' : 'md'"
          :icon="Play"
          :loading="starting === agent.key"
          :disabled="agent.running"
          class="max-sm:flex-1"
          data-testid="agent-run"
          @click="agent && runNow(agent)"
        >
          {{ agent.running ? t("ai.agents.working") : t("ai.agents.runNow") }}
        </UiButton>
      </template>
      <template v-if="agent && pill" #meta>
        <StatusPill :tone="pill.tone" :live="pill.live" :label="t(`ai.agent.status.${pill.key}`)" data-testid="agent-status" />
        <span class="text-sm text-muted">{{ agent.schedule }}</span>
        <UiBadge v-if="agent.unavailable_reason === 'needs_speech'" tone="warning" size="md">{{ t("ai.agents.needsSpeech") }}</UiBadge>
      </template>
    </PageHeader>

    <EmptyState v-if="notFound" class="ui-card" :icon="Bot" :title="t('ai.agents.notFound')" :description="t('ai.agent.notFoundBody')" data-testid="agent-not-found">
      <UiButton :to="agentsLink">{{ t("ai.agent.backToAgents") }}</UiButton>
    </EmptyState>
    <ErrorState v-else-if="query.isError.value && !agent" class="ui-card" :error="query.error.value" :retry="() => query.refetch()" />
    <template v-else>
      <InlineAlert v-if="status.data.value && !aiOn" tone="neutral" :icon="Bot" :title="t('ai.off.title')" :description="canConfigure ? t('ai.agent.aiOffOwner') : t('ai.off.body')">
        <template v-if="canConfigure" #actions>
          <UiButton size="sm" :to="agentsLink">{{ t("ai.turnOn.button") }}</UiButton>
        </template>
      </InlineAlert>

      <AgentScenePlaceholder v-if="agent" :variant="buddyVariant(agent.key)" :state="scene" :lines="lines" :night="night" :label="sceneLabel" />
      <SkeletonBlock v-else class="!h-[240px] md:!h-[380px]" radius="12px" />

      <AgentKpis :kpis="kpis" :loading="!agent" />

      <section class="flex min-w-0 flex-col gap-4" :aria-label="t('ai.agent.sections')">
        <AgentSectionTabs v-model="tab" :tabs="tabs" :label="t('ai.agent.sections')" :panel-id="panelId" />
        <div :id="panelId" role="tabpanel" :aria-labelledby="isPhone ? undefined : `${panelId}-tab-${tab}`" :aria-label="isPhone ? t(`ai.agent.tab.${tab}`) : undefined" class="min-w-0" :data-section-panel="tab">
          <div v-if="!agent" class="flex flex-col gap-2" aria-hidden="true">
            <SkeletonBlock v-for="n in 4" :key="n" height="56px" radius="10px" />
          </div>
          <template v-else-if="tab === 'done'">
            <div class="ui-card px-3 py-2 md:px-5 md:py-4">
              <div v-if="feed.isPending.value" class="flex flex-col gap-3 py-2" aria-hidden="true">
                <div v-for="n in 4" :key="n" class="flex items-start gap-3">
                  <SkeletonBlock circle width="32px" height="32px" />
                  <div class="flex flex-1 flex-col gap-1.5"><SkeletonBlock height="14px" width="80%" /><SkeletonBlock height="12px" width="40%" /></div>
                </div>
              </div>
              <ErrorState v-else-if="feed.isError.value" :error="feed.error.value" :retry="() => feed.refetch()" />
              <EmptyState v-else-if="!feed.items.value.length" size="sm" tone="neutral" :icon="Activity" :title="t('ai.activity.emptyAgent')" :description="on ? t('ai.agent.done.emptyBody') : t('ai.agent.done.emptyOff')" data-testid="agent-no-activity" />
              <ActivityFeed
                v-else
                :items="feed.items.value"
                :fresh="feed.fresh.value"
                :has-older="feed.hasOlder.value"
                :loading-older="feed.loadingOlder.value"
                :older-failed="feed.olderFailed.value"
                @older="feed.loadOlder()"
              />
            </div>
          </template>
          <AgentLog v-else-if="tab === 'log'" :agent="agent" :can-configure="canConfigure" :claude="claude" />
          <AgentUsage v-else-if="tab === 'tokens'" :agent="agent" :claude="claude" />
          <AgentUpcoming v-else-if="tab === 'next'" :items="agent.upcoming" :on="on" />
          <AgentSettings v-else :agent="agent" :can-configure="canConfigure" :ai-on="aiOn" />
        </div>
      </section>
    </template>
  </div>
</template>
