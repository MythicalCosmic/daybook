<script setup lang="ts">
/** The Ko‘z boxes in scope: online or not, when each was last heard from, its version. */
import { ArrowRight, Cpu } from "@lucide/vue";
import { useI18n } from "vue-i18n";
import { RouterLink } from "vue-router";

import RelativeTime from "@/components/RelativeTime.vue";
import { useCompanyStore } from "@/stores/company";

import type { AgentBrief } from "../types";

defineProps<{ agents: AgentBrief[]; branchName: (id: number) => string }>();

const { t } = useI18n();
const company = useCompanyStore();
</script>

<template>
  <section class="ui-card flex min-w-0 flex-col" :aria-label="t('vision.boxes.title')">
    <header class="flex items-center gap-2.5 px-4 pb-2 pt-4">
      <span class="grid size-7 place-items-center rounded-[9px] bg-surface-2 text-muted dark:bg-surface-3"><Cpu :size="15" /></span>
      <h2 class="flex-1 text-base font-semibold text-fg">{{ t("vision.boxes.title") }}</h2>
      <RouterLink v-if="company.can('vision.manage')" :to="`/c/${company.currentId}/vision/cameras`" class="inline-flex items-center gap-1 text-xs font-semibold text-muted transition-colors hover:text-fg">
        {{ t("vision.boxes.manage") }}<ArrowRight :size="13" />
      </RouterLink>
    </header>
    <ul class="flex flex-col px-4 pb-3">
      <li v-for="agent in agents" :key="agent.id" class="flex items-center gap-3 border-t border-line py-2.5 first:border-t-0" :data-agent="agent.id">
        <span :class="['koz-dot size-2.5 shrink-0 rounded-full', agent.online ? 'bg-success' : 'bg-danger']" :data-online="agent.online || undefined" aria-hidden="true" />
        <span class="min-w-0 flex-1">
          <span class="block truncate text-sm font-semibold text-fg">{{ agent.name }}</span>
          <span class="block truncate text-xs text-muted">
            {{ branchName(agent.branch_id) }} · {{ agent.online ? t("vision.boxes.online") : t("vision.boxes.offline") }}<template v-if="agent.version"> · {{ t("vision.boxes.version", { version: agent.version }) }}</template>
          </span>
        </span>
        <span v-if="agent.last_seen_at" class="shrink-0 text-xs text-subtle"><RelativeTime :value="agent.last_seen_at" /></span>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.koz-dot[data-online] {
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--c-success) 22%, transparent);
}
</style>
