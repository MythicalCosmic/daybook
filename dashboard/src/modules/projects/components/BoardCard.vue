<script setup lang="ts">
/**
 * The face of a card on the board: labels, the proof photo as a cover, key and title, and a footer
 * with the due chip, checklist, comments, logged time and the assignee. Status shows as a quiet
 * pill (waiting for a check, sent back) or a struck-through title when done.
 */
import { AlarmClock, ArrowUp, CheckSquare, ChevronsUp, Hourglass, Lock, MessageSquare, Timer, Undo2 } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import UiTooltip from "@/components/UiTooltip.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { zonedDay } from "@/lib/dates";
import { useFormat } from "@/lib/useFormat";
import { useNow } from "@/lib/useNow";
import { useCompanyStore } from "@/stores/company";

import { colorVar, DUE_CLASS, dueState, hhmm, tint } from "../lib";
import type { Card, Label } from "../types";

const props = withDefaults(defineProps<{ card: Card; labels: Label[]; running?: boolean }>(), { running: false });

const { t } = useI18n();
const fmt = useFormat();
const now = useNow();
const company = useCompanyStore();

const cardLabels = computed(() => props.card.label_ids.map((id) => props.labels.find((l) => l.id === id)).filter((l): l is Label => !!l));
const due = computed(() => dueState(props.card, now.value));
const done = computed(() => props.card.status === "done");
const dueText = computed(() => {
  if (!props.card.due_at) return "";
  if (due.value === "today") return t("projects.card.dueToday", { time: fmt.instant(props.card.due_at, "time") });
  return fmt.day(zonedDay(props.card.due_at, company.timezone), "short");
});
</script>

<template>
  <div class="flex flex-col gap-2" :class="!card.can_move && 'cursor-default'">
    <div v-if="card.proof_thumb" class="-mx-3 -mt-3 mb-0.5 overflow-hidden rounded-t-[9px] bg-surface-2">
      <img :src="card.proof_thumb" alt="" loading="lazy" class="h-28 w-full object-cover" />
    </div>
    <div v-if="cardLabels.length" class="flex flex-wrap gap-1">
      <span
        v-for="label in cardLabels"
        :key="label.id"
        class="inline-flex h-5 max-w-full items-center gap-1 truncate rounded-full px-2 text-[11px] font-semibold"
        :style="{ background: tint(label.color, 18), color: colorVar(label.color) }"
        ><span class="size-1.5 shrink-0 rounded-full" :style="{ background: colorVar(label.color) }" />{{ label.name }}</span
      >
    </div>
    <div class="flex items-start gap-1.5">
      <p class="min-w-0 flex-1 text-sm font-medium leading-snug" :class="done ? 'text-muted line-through decoration-line-strong' : 'text-fg'">{{ card.title }}</p>
      <UiTooltip v-if="card.priority === 'urgent' || card.priority === 'high'" :content="t(`projects.priority.task.${card.priority}`)">
        <ChevronsUp v-if="card.priority === 'urgent'" :size="15" class="mt-0.5 shrink-0 text-danger" />
        <ArrowUp v-else :size="15" class="mt-0.5 shrink-0 text-warning" />
      </UiTooltip>
    </div>
    <div v-if="card.status === 'review' || card.status === 'returned'" class="flex">
      <span v-if="card.status === 'review'" class="inline-flex items-center gap-1 rounded-full bg-warning-soft px-2 py-0.5 text-[11px] font-semibold text-warning"><Hourglass :size="11" />{{ t("projects.card.waiting") }}</span>
      <span v-else class="inline-flex items-center gap-1 rounded-full bg-danger-soft px-2 py-0.5 text-[11px] font-semibold text-danger"><Undo2 :size="11" />{{ t("projects.card.returned") }}</span>
    </div>
    <div class="flex items-end gap-2">
    <div class="flex min-w-0 flex-1 flex-wrap items-center gap-x-2 gap-y-1 whitespace-nowrap text-[11px] font-medium text-muted">
      <span class="font-mono text-subtle">{{ card.key }}</span>
      <span v-if="card.due_at" :class="['inline-flex h-5 items-center gap-1 rounded-[5px] px-1.5 tabular-nums', DUE_CLASS[due ?? 'later']]">
        <AlarmClock :size="11" />{{ dueText }}
      </span>
      <span v-if="card.checklist_total" class="inline-flex items-center gap-0.5 tabular-nums" :class="card.checklist_done === card.checklist_total && 'text-success'">
        <CheckSquare :size="12" />{{ card.checklist_done }}/{{ card.checklist_total }}
      </span>
      <span v-if="card.comments" class="inline-flex items-center gap-0.5 tabular-nums"><MessageSquare :size="12" />{{ card.comments }}</span>
      <span v-if="card.minutes || running" class="inline-flex items-center gap-0.5 tabular-nums" :class="running && 'text-primary'">
        <Timer :size="12" :class="running && 'animate-pulse'" />{{ hhmm(card.minutes) }}
      </span>
      <UiTooltip v-if="!card.can_move" :content="t('projects.card.locked')">
        <Lock :size="11" class="text-subtle" />
      </UiTooltip>
    </div>
    <UiTooltip v-if="card.assignee" :content="card.assignee.name">
      <UserAvatar :name="card.assignee.name" :src="card.assignee.photo_url" :size="22" class="shrink-0" />
    </UiTooltip>
    </div>
  </div>
</template>
