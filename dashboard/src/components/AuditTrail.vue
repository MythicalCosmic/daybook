<script setup lang="ts">
/**
 * The History tab on any record (plan §1.10: `AuditTrail` + `GET audit/records/`): who did what
 * and when, newest first, grouped by day, field changes as "old → new". The server leaves out rows
 * the viewer may not see and masks secret values as "•••", shown here as "hidden".
 *
 *   <AuditTrail target-type="task" :target-id="task.id" :field-labels="{ due_at: t('tasks.field.due') }" />
 *
 * `target-type` is the record's model name as the backend audits it ("task", "membership",
 * "transaction"). A row's `details.changes` is `{field: [old, new]}`; other plain details (a
 * reason, a note) are listed under it. `field-labels` names fields in the person's language
 * (otherwise "due_at" reads "Due at"); `format-value` formats a field's values.
 */
import { useInfiniteQuery } from "@tanstack/vue-query";
import { ArrowRight, History } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import { http, ownerPath } from "@/api/http";
import { qk } from "@/api/keys";
import type { Page } from "@/api/types";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import EmptyState from "./EmptyState.vue";
import ErrorState from "./ErrorState.vue";
import SkeletonBlock from "./SkeletonBlock.vue";
import TimelineList, { type TimelineEvent } from "./TimelineList.vue";
import UiButton from "./UiButton.vue";

/** One row of `GET audit/records/?target_type=&target_id=` (apps.audit.owner_api). */
export interface AuditRecord {
  id: number;
  created_at: string;
  action: string;
  /** The action in the caller's language ("Changed a task"). */
  action_label: string;
  /** `id` is their membership here, when they have one. */
  actor: { id: number | null; name: string } | null;
  target_type: string;
  target_id: number | null;
  /** The record's name at the time. */
  target: string;
  /** `changes: {field: [old, new]}` plus whatever else the action recorded; secrets are "•••". */
  details: Record<string, unknown>;
}

export interface AuditChange {
  field: string;
  label: string;
  old: string | null;
  new: string | null;
  hidden: boolean;
}

const props = withDefaults(
  defineProps<{
    targetType: string;
    targetId: number | string;
    pageSize?: number;
    fieldLabels?: Record<string, string>;
    formatValue?: (field: string, value: unknown) => string | null;
  }>(),
  { pageSize: 30, fieldLabels: () => ({}), formatValue: undefined },
);

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

const HIDDEN = /^•+$/;
/** Details that say why rather than what: shown as the row's text. */
const NOTE_KEYS = ["reason", "note", "comment", "message"];

/** "due_at" → "Due at", "home_branch" → "Home branch". */
function humanizeField(field: string): string {
  const words = field.replace(/[_.]+/g, " ").trim();
  return words ? words[0]!.toUpperCase() + words.slice(1) : field;
}

function label(field: string): string {
  return props.fieldLabels[field] ?? humanizeField(field);
}

function text(field: string, value: unknown): string | null {
  if (value === null || value === undefined || value === "") return null;
  const custom = props.formatValue?.(field, value);
  if (custom !== undefined && custom !== null) return custom;
  if (typeof value === "boolean") return value ? t("common.yes") : t("common.no");
  if (Array.isArray(value)) return value.length ? value.map((item) => String(item)).join(", ") : null;
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function changesOf(record: AuditRecord): AuditChange[] {
  const changes = record.details?.changes;
  if (!changes || typeof changes !== "object" || Array.isArray(changes)) return [];
  return Object.entries(changes as Record<string, unknown>).map(([field, pair]) => {
    const [before, after] = Array.isArray(pair) ? pair : [null, pair];
    const hidden = [before, after].some((value) => typeof value === "string" && HIDDEN.test(value));
    return { field, label: label(field), old: text(field, before), new: text(field, after), hidden };
  });
}

function noteOf(record: AuditRecord): string | undefined {
  for (const key of NOTE_KEYS) {
    const value = record.details?.[key];
    if (typeof value === "string" && value.trim()) return value;
  }
  return undefined;
}

/** Other plain details ("Branch: Chilonzor"), at most four. */
function extrasOf(record: AuditRecord): Array<{ key: string; label: string; value: string }> {
  return Object.entries(record.details ?? {})
    .filter(([key, value]) => key !== "changes" && !NOTE_KEYS.includes(key) && ["string", "number", "boolean"].includes(typeof value))
    .map(([key, value]) => ({ key, label: label(key), value: typeof value === "string" && HIDDEN.test(value) ? t("common.audit.hidden") : (text(key, value) ?? "") }))
    .filter((row) => row.value)
    .slice(0, 4);
}

const records = computed(() => query.data.value?.pages.flatMap((page) => page.results) ?? []);
const byKey = computed(
  () => new Map(records.value.map((record) => [record.id, { changes: changesOf(record), extras: extrasOf(record) }])),
);
const events = computed<TimelineEvent[]>(() =>
  records.value.map((record) => ({
    key: record.id,
    at: record.created_at,
    title: record.action_label,
    body: noteOf(record),
    actor: record.actor ?? { name: t("common.audit.system") },
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
          <ul
            v-if="byKey.get(Number(event.key))?.changes.length || byKey.get(Number(event.key))?.extras.length"
            class="mt-1.5 flex flex-col gap-1 rounded-[8px] bg-surface-2/50 px-2.5 py-2 text-sm dark:bg-surface-2/60"
          >
            <li v-for="change in byKey.get(Number(event.key))!.changes" :key="change.field" class="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5">
              <span class="shrink-0 text-xs font-semibold text-muted">{{ change.label }}</span>
              <span v-if="change.hidden" class="rounded-full bg-surface-3 px-1.5 text-[11px] font-semibold text-muted">{{ t("common.audit.hidden") }}</span>
              <template v-else>
                <span :class="['min-w-0 truncate', change.old === null ? 'italic text-subtle' : 'text-muted line-through decoration-[color-mix(in_srgb,var(--c-text)_30%,transparent)]']">{{
                  change.old ?? t("common.audit.blank")
                }}</span>
                <ArrowRight :size="12" class="shrink-0 text-subtle" aria-hidden="true" />
                <span :class="['min-w-0 truncate font-medium', change.new === null ? 'italic text-subtle' : 'text-fg']">{{ change.new ?? t("common.audit.blank") }}</span>
              </template>
            </li>
            <li v-for="extra in byKey.get(Number(event.key))!.extras" :key="extra.key" class="flex min-w-0 items-center gap-2">
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
