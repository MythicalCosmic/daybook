<script setup lang="ts">
/**
 * The History tab on any record (plan §1.10: `AuditTrail` + `audit/records/`): who changed what and
 * when, newest first, grouped by day, field changes as "old → new". Values the viewer may not see
 * come redacted from the server ("•••") and show as "hidden".
 *
 *   <AuditTrail target-type="finance.transaction" :target-id="txn.id" />
 */
import { useInfiniteQuery } from "@tanstack/vue-query";
import { ArrowRight, History } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import { http, ownerPath } from "@/api/http";
import { qk } from "@/api/keys";
import type { Page, PersonRef } from "@/api/types";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import EmptyState from "./EmptyState.vue";
import ErrorState from "./ErrorState.vue";
import SkeletonBlock from "./SkeletonBlock.vue";
import TimelineList, { type TimelineEvent } from "./TimelineList.vue";
import UiButton from "./UiButton.vue";

/** One row of `GET audit/records/` (W0-L's endpoint; redacted on the server). */
export interface AuditChange {
  field: string;
  label: string;
  old: string | null;
  new: string | null;
}

export interface AuditRecord {
  id: number;
  created_at: string;
  actor: PersonRef | null;
  action: string;
  action_label: string;
  summary?: string;
  changes?: AuditChange[];
}

const props = withDefaults(defineProps<{ targetType: string; targetId: number | string; pageSize?: number }>(), { pageSize: 30 });

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const companyId = computed(() => company.currentId ?? 0);

const query = useInfiniteQuery({
  queryKey: computed(() => qk(companyId.value, "shell", "audit-records", { type: props.targetType, id: props.targetId })),
  queryFn: ({ pageParam, signal }) =>
    http.get<Page<AuditRecord>>(
      ownerPath(companyId.value, "audit/records/"),
      { target_type: props.targetType, target_id: props.targetId, page: pageParam, page_size: props.pageSize },
      { signal },
    ),
  initialPageParam: 1,
  getNextPageParam: (last, _all, page) => (last.next ? page + 1 : undefined),
  enabled: computed(() => companyId.value > 0),
});

const records = computed(() => query.data.value?.pages.flatMap((page) => page.results) ?? []);
const byKey = computed(() => new Map(records.value.map((record) => [record.id, record])));
const events = computed<TimelineEvent[]>(() =>
  records.value.map((record) => ({ key: record.id, at: record.created_at, title: record.action_label, body: record.summary, actor: record.actor ?? { name: t("common.audit.system") } })),
);

const HIDDEN = /^•+$/;
const isHidden = (value: string | null) => value !== null && HIDDEN.test(value);
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
    <EmptyState v-else-if="!records.length" size="sm" tone="neutral" :icon="History" :title="t('common.audit.empty')" />
    <template v-else>
      <TimelineList :events="events">
        <template #event="{ event }">
          <div class="flex items-baseline gap-3">
            <p class="min-w-0 flex-1 text-base text-fg">
              <span class="font-semibold">{{ event.actor?.name }}</span>
              <span class="text-muted"> · {{ event.title }}</span>
            </p>
            <time :datetime="event.at" :title="fmt.instant(event.at)" class="shrink-0 text-xs tabular-nums text-subtle">{{ fmt.instant(event.at, "time") }}</time>
          </div>
          <p v-if="event.body" class="mt-0.5 text-sm text-muted">{{ event.body }}</p>
          <ul v-if="byKey.get(Number(event.key))?.changes?.length" class="mt-1.5 flex flex-col gap-1 rounded-[8px] bg-surface-2/50 px-2.5 py-2 text-sm dark:bg-surface-2/60">
            <li v-for="change in byKey.get(Number(event.key))!.changes" :key="change.field" class="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5">
              <span class="shrink-0 text-xs font-semibold text-muted">{{ change.label }}</span>
              <span v-if="isHidden(change.old) || isHidden(change.new)" class="rounded-full bg-surface-3 px-1.5 text-[11px] font-semibold text-muted">{{ t("common.audit.hidden") }}</span>
              <template v-else>
                <span :class="['min-w-0 truncate', change.old === null ? 'italic text-subtle' : 'text-muted line-through decoration-[color-mix(in_srgb,var(--c-text)_30%,transparent)]']">{{
                  change.old ?? t("common.audit.blank")
                }}</span>
                <ArrowRight :size="12" class="shrink-0 text-subtle" aria-hidden="true" />
                <span :class="['min-w-0 truncate font-medium', change.new === null ? 'italic text-subtle' : 'text-fg']">{{ change.new ?? t("common.audit.blank") }}</span>
              </template>
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
