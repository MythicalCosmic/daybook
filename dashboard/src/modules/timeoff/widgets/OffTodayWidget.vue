<script setup lang="ts">
/**
 * Overview widget "Off today": who is on approved time off today, and the requests waiting.
 * Fetches its own data and fails on its own.
 */
import { TreePalm } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink } from "vue-router";

import type { Range } from "@/api/types";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import WidgetCard from "@/components/WidgetCard.vue";
import { useWidgetSkeleton } from "@/components/widgetSkeleton";
import { todayIn } from "@/lib/dates";
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
const skeleton = useWidgetSkeleton(() => off.isPending.value);
const rows = computed(() => off.data.value?.results ?? []);
const base = computed(() => `/c/${props.companyId}/time-off`);
</script>

<template>
  <WidgetCard :title="t('timeoff.widget.title')" :icon="TreePalm" :count="off.data.value?.count ?? null" count-tone="neutral" :to="base">
    <div v-if="skeleton" class="flex flex-col gap-2 p-2"><SkeletonBlock v-for="n in 3" :key="n" height="30px" radius="8px" /></div>
    <ErrorState v-else-if="off.isError.value" compact class="m-2" :error="off.error.value" :retry="() => off.refetch()" />
    <EmptyState v-else-if="off.data.value && !rows.length" class="my-auto" size="sm" tone="success" :title="t('timeoff.widget.emptyTitle')" :description="t('timeoff.widget.emptyBody')" />
    <ul v-else class="flex flex-col">
      <li v-for="row in rows" :key="row.id">
        <RouterLink :to="{ path: base, query: { request: String(row.id) } }" class="flex items-center gap-2.5 rounded-[10px] px-2 py-1.5 transition-colors hover:bg-highlight">
          <UserAvatar :name="row.member.name" :src="row.member.photo_url" :size="28" status="off" />
          <span class="min-w-0 flex-1">
            <span class="block truncate text-sm font-semibold text-fg">{{ row.member.name }}</span>
            <span class="block truncate text-xs text-muted" :title="row.reason || undefined">{{ t("timeoff.widget.until", { date: fmt.day(row.last_day, "short") }) }}{{ row.reason ? ` · ${row.reason}` : "" }}</span>
          </span>
        </RouterLink>
      </li>
    </ul>
    <template v-if="stats.data.value?.pending" #footer>
      <RouterLink :to="base" class="-mx-1 inline-flex items-center gap-2 rounded-[8px] px-1 font-semibold text-warning hover:underline">
        <span class="size-1.5 rounded-full bg-warning" aria-hidden="true" />{{ t("timeoff.widget.waiting", { n: stats.data.value.pending }, stats.data.value.pending) }}
      </RouterLink>
    </template>
  </WidgetCard>
</template>
