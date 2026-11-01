<script setup lang="ts">
/**
 * Inside an agent's drawer: what it does, why it can't run (when it can't), its numbers, its
 * settings (drawn from its fields, each change saved at once) and what it did lately.
 */
import { ArrowRight, Info, KeyRound, Lock } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink } from "vue-router";

import InlineAlert from "@/components/InlineAlert.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import { toast } from "@/components/useToast";
import { useFormat } from "@/lib/useFormat";
import { useNow } from "@/lib/useNow";
import { useCompanyStore } from "@/stores/company";

import { useActivityFeed, usePatchAgent } from "../api";
import type { Agent, AgentConfigValue } from "../types";
import ActivityFeed from "./ActivityFeed.vue";
import AgentField from "./AgentField.vue";

const props = defineProps<{ agent: Agent; canConfigure: boolean; aiOn: boolean }>();

const { t } = useI18n();
const fmt = useFormat();
const now = useNow();
const company = useCompanyStore();
const patch = usePatchAgent();
const saving = ref<string | null>(null);
const feed = useActivityFeed(() => props.agent.key, { limit: 8 });

const lastRun = computed(() => (props.agent.last_run_at ? fmt.relative(props.agent.last_run_at, now.value) : null));
const nextRun = computed(() => (props.agent.next_run_at && props.agent.enabled && props.aiOn ? fmt.relative(props.agent.next_run_at, now.value) : null));
const editable = computed(() => props.canConfigure && props.aiOn);

async function save(key: string, value: AgentConfigValue): Promise<void> {
  saving.value = key;
  try {
    await patch.mutateAsync({ key: props.agent.key, patch: { config: { [key]: value } } });
    toast.success(t("ai.agents.saved"));
  } catch {
    // Rolled back; the reason is a toast from the HTTP layer (or the field's own error).
  } finally {
    saving.value = null;
  }
}
</script>

<template>
  <div class="flex flex-col gap-6 px-5 py-5">
    <p class="text-base leading-[1.5] text-fg">{{ agent.description }}</p>

    <InlineAlert v-if="agent.unavailable_reason === 'needs_claude'" tone="warning" :icon="KeyRound" :title="t('ai.agents.needsClaudeTitle')" :description="t('ai.agents.needsClaudeBody')" />
    <InlineAlert v-else-if="agent.unavailable_reason === 'needs_speech'" tone="warning" :icon="Lock" :title="t('ai.agents.needsSpeechTitle')" :description="t('ai.agents.needsSpeechBody')" />
    <InlineAlert v-if="agent.key === 'photo_checker'" tone="info" :icon="Info" :description="t('ai.agents.photosNote')" />

    <dl class="grid grid-cols-2 gap-2">
      <div class="rounded-[10px] bg-surface-2 px-3 py-2.5 dark:bg-surface-3">
        <dt class="text-xs font-medium text-muted">{{ t("ai.agents.todayLong") }}</dt>
        <dd class="num text-lg font-semibold text-fg">{{ agent.stats.today }}</dd>
      </div>
      <div class="rounded-[10px] bg-surface-2 px-3 py-2.5 dark:bg-surface-3">
        <dt class="text-xs font-medium text-muted">{{ t("ai.agents.weekLong") }}</dt>
        <dd class="num text-lg font-semibold text-fg">{{ agent.stats.week }}</dd>
      </div>
      <div v-if="lastRun || nextRun" class="col-span-2 flex flex-wrap gap-x-4 gap-y-1 px-1 text-sm text-muted">
        <span v-if="lastRun" class="num">{{ t("ai.agents.last", { when: lastRun }) }}</span>
        <span v-if="nextRun" class="num">{{ t("ai.agents.next", { when: nextRun }) }}</span>
      </div>
    </dl>

    <section v-if="agent.fields.length" class="flex flex-col gap-3">
      <h3 class="text-sm font-semibold text-fg">{{ t("ai.agents.settings") }}</h3>
      <div class="ui-card flex flex-col divide-y divide-line">
        <div v-for="field in agent.fields" :key="field.key" class="px-4 py-3.5">
          <AgentField :field="field" :value="agent.config[field.key]" :disabled="!editable" :saving="saving === field.key" @change="(value) => save(field.key, value)" />
        </div>
      </div>
      <p v-if="!canConfigure" class="text-sm text-muted">{{ t("ai.agents.onlyOwner") }}</p>
    </section>

    <section class="flex flex-col gap-2">
      <div class="flex items-center justify-between gap-3">
        <h3 class="text-sm font-semibold text-fg">{{ t("ai.agents.recent") }}</h3>
        <RouterLink
          v-if="company.currentId"
          :to="{ name: 'ai.activity', params: { companyId: company.currentId }, query: { agent: agent.key } }"
          class="inline-flex h-8 items-center gap-1 rounded-button px-2 text-sm font-medium text-accent-fg hover:bg-highlight"
        >
          {{ t("ai.agents.seeAll") }}<ArrowRight :size="14" aria-hidden="true" />
        </RouterLink>
      </div>
      <div v-if="feed.isPending.value" class="flex flex-col gap-2" aria-hidden="true">
        <SkeletonBlock v-for="n in 3" :key="n" height="44px" radius="10px" />
      </div>
      <p v-else-if="!feed.items.value.length" class="rounded-[10px] bg-surface-2 px-3 py-3 text-sm text-muted dark:bg-surface-3">{{ t("ai.agents.noActivity") }}</p>
      <ActivityFeed v-else :items="feed.items.value.slice(0, 8)" :fresh="feed.fresh.value" compact :autoload="false" />
    </section>
  </div>
</template>
