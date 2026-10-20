<script setup lang="ts">
/**
 * Overview widget "Off today": who is on approved time off today, and the requests waiting.
 * Fetches its own data and fails on its own.
 */
import { ArrowRight, TreePalm } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink } from "vue-router";

import type { Range } from "@/api/types";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { todayIn } from "@/lib/dates";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { useStats, useTimeOffList } from "../api";

const props = defineProps<{ companyId: number; range?: Range; compare?: Range | null }>();

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const today = computed(() => todayIn(company.timezone));
const off = useTimeOffList(computed(() => ({ status: ["approved" as const], from: today.value, to: today.value, page_size: 6, ordering: "first_day" })));
const stats = useStats();
const skeleton = useDelayedPending(computed(() => off.isPending.value));
const rows = computed(() => off.data.value?.results ?? []);
const base = computed(() => `/c/${props.companyId}/time-off`);
</script>

<template>
  <section class="ui-card flex h-full min-w-0 flex-col" :aria-label="t('timeoff.widget.title')">
    <header class="flex items-center gap-2 px-4 pb-2 pt-4">
      <TreePalm :size="16" class="text-subtle" aria-hidden="true" />
      <h3 class="text-sm font-semibold text-fg">{{ t("timeoff.widget.title") }}</h3>
      <span class="flex-1" />
      <RouterLink :to="base" class="inline-flex items-center gap-1 rounded-[6px] px-1.5 py-0.5 text-sm font-semibold text-muted hover:bg-highlight hover:text-fg">
        {{ t("common.viewAll") }}<ArrowRight :size="14" />
      </RouterLink>
    </header>
    <div class="min-h-0 flex-1 px-2 pb-2">
      <div v-if="skeleton" class="flex flex-col gap-2 p-2"><SkeletonBlock v-for="n in 3" :key="n" height="30px" radius="8px" /></div>
      <ErrorState v-else-if="off.isError.value" compact class="m-2" :error="off.error.value" :retry="() => off.refetch()" />
      <EmptyState v-else-if="off.data.value && !rows.length" size="sm" tone="success" :title="t('timeoff.widget.emptyTitle')" :description="t('timeoff.widget.emptyBody')" />
      <ul v-else class="flex flex-col">
        <li v-for="row in rows" :key="row.id">
          <RouterLink :to="{ path: base, query: { request: String(row.id) } }" class="flex items-center gap-2.5 rounded-[10px] px-2 py-1.5 transition-colors hover:bg-highlight">
            <UserAvatar :name="row.member.name" :src="row.member.photo_url" :size="28" status="off" />
            <span class="min-w-0 flex-1">
              <span class="block truncate text-sm font-semibold text-fg">{{ row.member.name }}</span>
              <span class="block truncate text-xs text-muted">{{ t("timeoff.widget.until", { date: fmt.day(row.last_day, "short") }) }}{{ row.reason ? ` · ${row.reason}` : "" }}</span>
            </span>
          </RouterLink>
        </li>
      </ul>
    </div>
    <RouterLink
      v-if="stats.data.value?.pending"
      :to="base"
      class="mx-4 mb-4 inline-flex items-center gap-2 rounded-[10px] bg-warning-soft px-3 py-2 text-sm font-semibold text-warning"
    >
      {{ t("timeoff.widget.waiting", { n: stats.data.value.pending }, stats.data.value.pending) }}
    </RouterLink>
  </section>
</template>
