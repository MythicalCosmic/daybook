<script setup lang="ts">
/**
 * Person 360 › History: audit rows about the person and their time off (`people/{id}/history/`),
 * newest first and grouped by day, changes as "old → new". Rows touching salaries or IDs are
 * left out by the server for people without the permission.
 */
import { useInfiniteQuery } from "@tanstack/vue-query";
import { ArrowRight, History } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import TimelineList, { type TimelineEvent } from "@/components/TimelineList.vue";
import UiButton from "@/components/UiButton.vue";
import { useFormat } from "@/lib/useFormat";

import { listHistory, peopleKeys, useCompanyId } from "../api";
import type { HistoryRecord } from "../types";

const props = defineProps<{ memberId: number }>();

const { t, te } = useI18n();
const fmt = useFormat();
const cid = useCompanyId();

const query = useInfiniteQuery({
  queryKey: computed(() => peopleKeys.history(cid.value, props.memberId)),
  queryFn: ({ pageParam, signal }) => listHistory(cid.value, props.memberId, pageParam, signal),
  initialPageParam: 1,
  getNextPageParam: (last, _all, page) => (last.next ? page + 1 : undefined),
  enabled: computed(() => cid.value > 0),
});

const records = computed(() => query.data.value?.pages.flatMap((page) => page.results) ?? []);
const HIDDEN = /^•+$/;
const NOTES = ["reason", "note"];

function label(field: string): string {
  const key = `people.field.${field}`;
  return te(key) ? t(key) : field.replace(/[_.]+/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

function text(value: unknown): string | null {
  if (value === null || value === undefined || value === "") return null;
  if (Array.isArray(value)) return value.length ? value.map(String).join(", ") : null;
  if (typeof value === "boolean") return value ? t("common.yes") : t("common.no");
  if (typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value)) return fmt.day(value, "medium");
  return String(value);
}

function changes(record: HistoryRecord) {
  const raw = record.details?.changes;
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return [];
  return Object.entries(raw as Record<string, unknown>).map(([field, pair]) => {
    const [before, after] = Array.isArray(pair) ? pair : [null, pair];
    return { field, label: label(field), old: text(before), new: text(after), hidden: [before, after].some((v) => typeof v === "string" && HIDDEN.test(v)) };
  });
}

function extras(record: HistoryRecord) {
  return Object.entries(record.details ?? {})
    .filter(([key, value]) => key !== "changes" && !NOTES.includes(key) && ["string", "number"].includes(typeof value))
    .map(([key, value]) => ({ key, label: label(key), value: text(value) ?? "" }))
    .filter((row) => row.value)
    .slice(0, 4);
}

function note(record: HistoryRecord): string | undefined {
  for (const key of NOTES) {
    const value = record.details?.[key];
    if (typeof value === "string" && value.trim() && !/^[a-z_]+$/.test(value)) return value;
    if (typeof value === "string" && value.trim() && te(`people.offboard.reason.${value}`)) return t(`people.offboard.reason.${value}`);
  }
  return undefined;
}

const byId = computed(() => new Map(records.value.map((record) => [record.id, { changes: changes(record), extras: extras(record) }])));
const events = computed<TimelineEvent[]>(() =>
  records.value.map((record) => ({
    key: record.id,
    at: record.created_at,
    title: record.action_label,
    body: note(record),
    actor: record.actor ?? { name: t("common.audit.system") },
    meta: record.target_type === "timeoff" ? t("people.history.timeOff") : undefined,
  })),
);
</script>

<template>
  <div class="min-w-0">
    <div v-if="query.isPending.value" class="flex flex-col gap-4">
      <div v-for="n in 4" :key="n" class="flex gap-3">
        <SkeletonBlock circle height="28px" />
        <div class="flex flex-1 flex-col gap-2 pt-1"><SkeletonBlock width="55%" /><SkeletonBlock width="35%" height="12px" /></div>
      </div>
    </div>
    <ErrorState v-else-if="query.isError.value" compact :error="query.error.value" :retry="() => query.refetch()" />
    <EmptyState v-else-if="!records.length" size="sm" tone="neutral" :icon="History" :title="t('people.history.emptyTitle')" :description="t('people.history.emptyBody')" />
    <template v-else>
      <TimelineList :events="events">
        <template #event="{ event }">
          <div class="flex items-baseline gap-3">
            <p class="min-w-0 flex-1 text-base text-fg">
              <span class="font-semibold">{{ event.actor?.name }}</span>
              <span class="text-muted"> · {{ event.title }}</span>
              <span v-if="event.meta" class="ml-1.5 rounded-full bg-info-soft px-1.5 py-px text-[11px] font-semibold text-info">{{ event.meta }}</span>
            </p>
            <time :datetime="event.at" :title="fmt.instant(event.at)" class="shrink-0 text-xs tabular-nums text-subtle">{{ fmt.instant(event.at, "time") }}</time>
          </div>
          <p v-if="event.body" class="mt-0.5 text-sm text-muted">{{ event.body }}</p>
          <ul
            v-if="byId.get(Number(event.key))?.changes.length || byId.get(Number(event.key))?.extras.length"
            class="mt-1.5 flex flex-col gap-1 rounded-[8px] bg-surface-2/50 px-2.5 py-2 text-sm dark:bg-surface-2/60"
          >
            <li v-for="change in byId.get(Number(event.key))!.changes" :key="change.field" class="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5">
              <span class="shrink-0 text-xs font-semibold text-muted">{{ change.label }}</span>
              <span v-if="change.hidden" class="rounded-full bg-surface-3 px-1.5 text-[11px] font-semibold text-muted">{{ t("common.audit.hidden") }}</span>
              <template v-else>
                <span :class="['min-w-0 truncate', change.old === null ? 'italic text-subtle' : 'text-muted line-through']">{{ change.old ?? t("common.audit.blank") }}</span>
                <ArrowRight :size="12" class="shrink-0 text-subtle" aria-hidden="true" />
                <span :class="['min-w-0 truncate font-medium', change.new === null ? 'italic text-subtle' : 'text-fg']">{{ change.new ?? t("common.audit.blank") }}</span>
              </template>
            </li>
            <li v-for="extra in byId.get(Number(event.key))!.extras" :key="extra.key" class="flex min-w-0 items-center gap-2">
              <span class="shrink-0 text-xs font-semibold text-muted">{{ extra.label }}</span>
              <span class="min-w-0 truncate text-fg">{{ extra.value }}</span>
            </li>
          </ul>
        </template>
      </TimelineList>
      <div v-if="query.hasNextPage.value" class="mt-1 flex justify-center">
        <UiButton size="sm" variant="ghost" :loading="query.isFetchingNextPage.value" @click="query.fetchNextPage()">{{ t("common.audit.loadMore") }}</UiButton>
      </div>
    </template>
  </div>
</template>
