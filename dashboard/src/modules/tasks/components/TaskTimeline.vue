<script setup lang="ts">
/**
 * A task's merged timeline (plan §4.5 `timeline/`): created, comments, heads-ups, reminders,
 * escalations, blocked notices, finishing and audited changes, oldest first.
 */
import { AlarmClock, Ban, BellRing, CircleCheck, MessageSquare, Pencil, Plus, Siren } from "@lucide/vue";
import { computed, type Component } from "vue";
import { useI18n } from "vue-i18n";

import ErrorState from "@/components/ErrorState.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import TimelineList, { type TimelineEvent } from "@/components/TimelineList.vue";
import { useDelayedPending } from "@/lib/useDelayedPending";

import { useTimeline } from "../api";
import type { TaskTimelineEntry } from "../types";

const props = defineProps<{ taskId: number }>();
const { t } = useI18n();

const query = useTimeline(computed(() => props.taskId));
const skeleton = useDelayedPending(computed(() => query.isPending.value));

const ICONS: Record<TaskTimelineEntry["kind"], Component> = {
  created: Plus,
  comment: MessageSquare,
  completed: CircleCheck,
  heads_up: AlarmClock,
  reminder: BellRing,
  escalation: Siren,
  blocked: Ban,
  audit: Pencil,
};
const TONES: Partial<Record<TaskTimelineEntry["kind"], TimelineEvent["tone"]>> = {
  completed: "success",
  reminder: "warning",
  escalation: "danger",
  blocked: "danger",
  heads_up: "info",
  created: "primary",
};

function title(entry: TaskTimelineEntry): string {
  const who = entry.actor?.name ?? t("tasks.timeline.system");
  switch (entry.kind) {
    case "created":
      return t("tasks.timeline.created", { name: who });
    case "comment":
      return t("tasks.timeline.comment", { name: who });
    case "completed":
      return t("tasks.timeline.completed", { name: who });
    case "heads_up":
      return t("tasks.timeline.headsUp", { name: who });
    case "reminder":
      return entry.meta.delivered === false ? t("tasks.timeline.reminderFailed", { n: entry.meta.step ?? 0, name: who }) : t("tasks.timeline.reminder", { n: entry.meta.step ?? 0, name: who });
    case "escalation":
      return t("tasks.timeline.escalation", { name: who });
    case "blocked":
      return t("tasks.timeline.blocked", { name: who });
    default:
      return `${who} · ${entry.text}`;
  }
}

function body(entry: TaskTimelineEntry): string | undefined {
  if (entry.kind === "comment" || entry.kind === "completed") return entry.text || undefined;
  if (entry.kind === "audit") {
    if (typeof entry.meta.reason === "string") return entry.meta.reason;
    const changes = entry.meta.changes;
    if (changes && typeof changes === "object") {
      return Object.keys(changes)
        .map((field) => t(`tasks.field.${field}`, field))
        .join(", ");
    }
  }
  if (entry.kind === "reminder" && entry.text) return entry.text;
  return undefined;
}

const events = computed<TimelineEvent[]>(() =>
  (query.data.value ?? []).map((entry, index) => ({
    key: `${entry.kind}:${entry.at}:${index}`,
    at: entry.at,
    title: title(entry),
    body: body(entry),
    icon: ICONS[entry.kind],
    tone: TONES[entry.kind] ?? "neutral",
    // The title already names the person, in each language's word order (TimelineList would
    // print the name a second time in front of it).
    actor: null,
  })),
);
</script>

<template>
  <div>
    <div v-if="skeleton" class="flex flex-col gap-3 py-2">
      <div v-for="n in 4" :key="n" class="flex gap-3"><SkeletonBlock circle height="24px" /><div class="flex flex-1 flex-col gap-1.5"><SkeletonBlock width="60%" /><SkeletonBlock width="30%" height="11px" /></div></div>
    </div>
    <ErrorState v-else-if="query.isError.value" compact :error="query.error.value" :retry="() => query.refetch()" />
    <TimelineList v-else :events="events" dense />
  </div>
</template>
