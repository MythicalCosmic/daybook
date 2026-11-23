<script setup lang="ts">
/**
 * A Ko‘z box: online or not, its branch and PC, how many cameras, its version and when it was last
 * heard from; a box that waits for its pairing says so. The menu gives a new pairing code (which
 * revokes the old key) or removes the box (its cameras stay, offline, with their history).
 */
import { Cpu, Ellipsis, KeyRound, Trash2 } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import DropdownMenu from "@/components/DropdownMenu.vue";
import IconButton from "@/components/IconButton.vue";
import type { MenuEntry } from "@/components/menuTypes";
import StatusPill from "@/components/StatusPill.vue";
import { useFormat } from "@/lib/useFormat";
import { useNow } from "@/lib/useNow";

import type { Agent } from "../types";

const props = defineProps<{ agent: Agent }>();
const emit = defineEmits<{ repair: [agent: Agent]; remove: [agent: Agent] }>();

const { t } = useI18n();
const fmt = useFormat();
const now = useNow();

const menu = computed<MenuEntry[]>(() => [
  { label: t("vision.boxes.newCode"), icon: KeyRound, onSelect: () => emit("repair", props.agent) },
  { type: "separator" },
  { label: t("vision.boxes.remove"), icon: Trash2, danger: true, onSelect: () => emit("remove", props.agent) },
]);
</script>

<template>
  <article class="ui-card flex min-w-0 flex-col gap-3 p-4" :data-agent="agent.id">
    <header class="flex items-start gap-3">
      <span :class="['grid size-10 shrink-0 place-items-center rounded-[11px]', agent.online ? 'bg-success-soft text-success' : agent.paired ? 'bg-danger-soft text-danger' : 'bg-surface-2 text-muted dark:bg-surface-3']">
        <Cpu :size="19" />
      </span>
      <div class="min-w-0 flex-1">
        <h3 class="truncate text-base font-semibold text-fg">{{ agent.name }}</h3>
        <p class="line-clamp-2 text-sm text-muted">{{ agent.branch.name }}<template v-if="agent.host"> · {{ agent.host.hostname }} ({{ agent.host.os }})</template></p>
      </div>
      <StatusPill v-if="!agent.paired" tone="neutral" size="sm" :label="t('vision.boxes.waiting')" />
      <StatusPill v-else :tone="agent.online ? 'success' : 'danger'" :live="agent.online" size="sm" :label="agent.online ? t('vision.boxes.online') : t('vision.boxes.offline')" />
      <DropdownMenu :items="menu">
        <template #trigger><IconButton :icon="Ellipsis" :label="t('vision.boxes.actions', { name: agent.name })" size="sm" /></template>
      </DropdownMenu>
    </header>
    <p class="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
      <span class="font-semibold text-fg">{{ t("vision.boxes.cameras", { n: agent.cameras }, agent.cameras) }}</span>
      <span v-if="agent.version">{{ t("vision.boxes.version", { version: agent.version }) }}</span>
      <span v-if="agent.last_seen_at">{{ t("vision.boxes.seen", { time: fmt.relative(agent.last_seen_at, now) }) }}</span>
      <span v-else>{{ t("vision.boxes.never") }}</span>
    </p>
  </article>
</template>
