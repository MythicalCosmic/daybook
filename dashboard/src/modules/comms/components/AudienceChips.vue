<script setup lang="ts">
/** Who an announcement goes to, as chips: its branches and positions, or "Everyone". */
import { Building2, BriefcaseBusiness, Users } from "@lucide/vue";
import { useI18n } from "vue-i18n";

import type { Announcement } from "../types";

defineProps<{ announcement: Pick<Announcement, "positions" | "branches">; max?: number }>();

const { t } = useI18n();
</script>

<template>
  <span class="flex min-w-0 flex-wrap items-center gap-1">
    <span v-if="!announcement.positions.length && !announcement.branches.length" class="chip"><Users :size="11" aria-hidden="true" />{{ t("comms.audience.everyone") }}</span>
    <span v-for="branch in announcement.branches.slice(0, max ?? 3)" :key="`b${branch.id}`" class="chip"><Building2 :size="11" aria-hidden="true" />{{ branch.name }}</span>
    <span v-for="position in announcement.positions.slice(0, max ?? 3)" :key="`p${position.id}`" class="chip"><BriefcaseBusiness :size="11" aria-hidden="true" />{{ position.name }}</span>
    <span v-if="announcement.positions.length + announcement.branches.length > (max ?? 3) * 2" class="text-xs text-subtle">…</span>
  </span>
</template>

<style scoped>
.chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 22px;
  padding: 0 7px;
  border-radius: 999px;
  background: var(--c-surface-2);
  color: var(--c-muted);
  font-size: var(--text-xs);
  font-weight: 550;
  white-space: nowrap;
}
:root[data-theme="dark"] .chip {
  background: var(--c-surface-3);
}
</style>
