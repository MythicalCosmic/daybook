<script setup lang="ts">
/**
 * What an agent does next (its page's "Keyingi ishlar"), soonest first: its next scheduled runs
 * and what it expects (counts only: "Tasks due in the next 24 hours: 4"), or, for an agent that
 * works as things arrive, what it waits for. Each with when, as "in 25 min" and the exact time.
 */
import { CalendarClock, Inbox, MoonStar, Zap } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import EmptyState from "@/components/EmptyState.vue";
import { useFormat } from "@/lib/useFormat";
import { useNow } from "@/lib/useNow";

import type { AgentUpcoming } from "../types";

const props = defineProps<{ items: AgentUpcoming[]; on: boolean }>();

const { t } = useI18n();
const fmt = useFormat();
const now = useNow();

const rows = computed(() =>
  props.items.map((item, index) => ({
    ...item,
    id: `${index}:${item.at ?? ""}:${item.label}`,
    icon: item.at === null ? Zap : item.kind === "run" ? CalendarClock : Inbox,
    when: item.at ? fmt.relative(item.at, now.value) : null,
    exact: item.at ? fmt.instant(item.at, "short") : null,
  })),
);
</script>

<template>
  <div class="flex flex-col gap-2">
    <EmptyState v-if="!on && !items.length" class="ui-card" size="sm" tone="neutral" :icon="MoonStar" :title="t('ai.agent.next.off')" :description="t('ai.agent.next.offBody')" data-testid="agent-upcoming-off" />
    <EmptyState v-else-if="!items.length" class="ui-card" size="sm" tone="neutral" :icon="CalendarClock" :title="t('ai.agent.next.empty')" :description="t('ai.agent.next.emptyBody')" data-testid="agent-upcoming-empty" />
    <ol v-else class="ui-card flex flex-col divide-y divide-line" data-testid="agent-upcoming">
      <li v-for="row in rows" :key="row.id" class="flex items-start gap-3 px-4 py-3.5 md:px-5" :data-kind="row.kind">
        <span
          :class="['mt-0.5 grid size-9 shrink-0 place-items-center rounded-[10px]', row.kind === 'run' ? 'bg-accent-soft text-accent-fg' : 'bg-surface-2 text-muted dark:bg-surface-3']"
          aria-hidden="true"
        >
          <component :is="row.icon" :size="17" />
        </span>
        <div class="min-w-0 flex-1">
          <p class="text-base leading-[1.45] text-fg">{{ row.label }}</p>
          <p class="mt-0.5 text-sm text-muted">
            <template v-if="row.when">
              <time :datetime="row.at ?? undefined" class="num font-medium text-fg">{{ row.when }}</time>
              <span class="px-1.5 text-subtle" aria-hidden="true">·</span>
              <span class="num">{{ row.exact }}</span>
            </template>
            <template v-else>{{ t("ai.agent.next.onArrival") }}</template>
          </p>
        </div>
        <span v-if="row.kind === 'run'" class="mt-1 shrink-0 rounded-full bg-surface-2 px-2 py-0.5 text-xs font-medium text-muted dark:bg-surface-3 max-sm:hidden">{{ t("ai.agent.next.run") }}</span>
      </li>
    </ol>
    <p v-if="!on && items.length" class="px-1 text-sm text-muted">{{ t("ai.agent.next.offBody") }}</p>
  </div>
</template>
