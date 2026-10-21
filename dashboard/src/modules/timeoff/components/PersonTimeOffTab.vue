<script setup lang="ts">
/**
 * Person 360 › Time off (registered by this module): everything they asked for or had recorded,
 * newest first, with the status and who decided. "Record time off" is the profile header's action.
 */
import { FileText, TreePalm } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink } from "vue-router";

import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill, { type StatusTone } from "@/components/StatusPill.vue";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { useTimeOffList } from "../api";
import type { TimeOffStatus } from "../types";

const props = defineProps<{ memberId: number }>();

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const query = useTimeOffList(computed(() => ({ member: props.memberId, ordering: "-first_day", page_size: 100 })));
const skeleton = useDelayedPending(computed(() => query.isPending.value));
const rows = computed(() => query.data.value?.results ?? []);
const TONES: Record<TimeOffStatus, StatusTone> = { pending: "warning", approved: "success", rejected: "danger", cancelled: "neutral" };
const approvedDays = computed(() => {
  const year = new Date().getFullYear().toString();
  return rows.value.filter((row) => row.status === "approved" && row.first_day.startsWith(year)).reduce((sum, row) => sum + row.days, 0);
});
const base = computed(() => `/c/${company.currentId}/time-off`);
</script>

<template>
  <section class="ui-card overflow-hidden">
    <header class="flex flex-wrap items-center gap-2 border-b border-line px-5 py-3">
      <h2 class="text-md font-semibold text-fg">{{ t("timeoff.tab") }}</h2>
      <span v-if="rows.length" class="text-sm text-muted">· {{ t("timeoff.person.thisYear", { n: approvedDays }, approvedDays) }}</span>
      <!-- "Record time off" is in the profile header right above, for the people who may. -->
    </header>
    <div v-if="skeleton" class="flex flex-col gap-2 p-4"><SkeletonBlock v-for="n in 4" :key="n" height="44px" radius="8px" /></div>
    <ErrorState v-else-if="query.isError.value" compact class="m-4" :error="query.error.value" :retry="() => query.refetch()" />
    <EmptyState v-else-if="query.data.value && !rows.length" size="sm" tone="neutral" :icon="TreePalm" :title="t('timeoff.person.emptyTitle')" :description="t('timeoff.person.emptyBody')" />
    <ul v-else class="divide-y divide-[var(--c-border)]">
      <li v-for="row in rows" :key="row.id">
        <RouterLink :to="{ path: base, query: { request: String(row.id), view: 'list' } }" class="flex items-center gap-3 px-5 py-3 transition-colors hover:bg-highlight">
          <div class="min-w-0 flex-1">
            <p class="truncate text-base font-medium text-fg">
              {{ row.first_day === row.last_day ? fmt.day(row.first_day, "medium") : fmt.range({ from: row.first_day, to: row.last_day }) }}
              <span class="font-normal text-muted">· {{ t("timeoff.days", { n: row.days }, row.days) }}</span>
            </p>
            <p class="truncate text-xs text-muted">
              {{ row.reason || t("timeoff.person.noReason") }}
              <template v-if="row.recorded_by"> · {{ t("timeoff.list.recordedBy", { name: row.recorded_by.name }) }}</template>
              <template v-else-if="row.decided_by"> · {{ row.decided_by }}</template>
            </p>
          </div>
          <FileText v-if="row.attachment" :size="15" class="shrink-0 text-info" :aria-label="t('timeoff.drawer.attachment')" />
          <StatusPill size="sm" :tone="TONES[row.status]" :label="row.revoked_at && row.status === 'approved' ? t('timeoff.state.shortened') : t(`timeoff.state.${row.status}`)" />
        </RouterLink>
      </li>
    </ul>
  </section>
</template>
