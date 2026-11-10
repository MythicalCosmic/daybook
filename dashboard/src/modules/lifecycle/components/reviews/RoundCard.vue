<script setup lang="ts">
/** A review round on the Reviews page: its name, stage and period, how far everyone has got, its deadlines and who is late. */
import { CalendarClock, ChevronRight, PenLine, TriangleAlert } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import ProgressBar from "@/components/ProgressBar.vue";
import StatusPill from "@/components/StatusPill.vue";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore, useCompanyToday } from "@/stores/company";

import { ROUND_TONES } from "../../reviews/lib";
import type { Round } from "../../reviews/types";

const props = defineProps<{ round: Round }>();

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const today = useCompanyToday();

const to = computed(() => ({ path: `/c/${company.currentId}/lifecycle/reviews/${props.round.id}`, query: props.round.mine ? { mine: "1" } : {} }));
const people = computed(() => props.round.progress.people);
const share = (value: number) => (people.value ? Math.round((100 * value) / people.value) : 0);
const audience = computed(() => {
  const names = [...props.round.audience.positions, ...props.round.audience.branches].map((item) => item.name);
  return names.length ? names.join(", ") : t("lifecycle.reviews.everyone");
});
const deadline = computed(() => {
  const round = props.round;
  if (round.status === "self") return { label: t("lifecycle.reviews.card.selfDue"), day: round.self_due_on };
  if (round.status === "manager") return { label: t("lifecycle.reviews.card.managerDue"), day: round.manager_due_on };
  if (round.status === "draft") return { label: t("lifecycle.reviews.card.selfDue"), day: round.self_due_on };
  return null;
});
</script>

<template>
  <RouterLink :to="to" class="ui-card group flex flex-col gap-4 p-4 transition-shadow hover:shadow-md focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--c-primary)] sm:p-5" :data-round="round.id">
    <div class="flex items-start gap-3">
      <div class="min-w-0 flex-1">
        <div class="flex flex-wrap items-center gap-2">
          <h3 class="truncate text-base font-semibold text-fg">{{ round.name }}</h3>
          <StatusPill size="sm" :tone="ROUND_TONES[round.status]" :label="t(`lifecycle.reviews.status.${round.status}`)" />
        </div>
        <p class="mt-0.5 truncate text-sm text-muted">{{ fmt.day(round.period_start, "medium") }} – {{ fmt.day(round.period_end, "medium") }} · {{ audience }}</p>
      </div>
      <ChevronRight :size="18" class="mt-1 shrink-0 text-subtle transition-transform group-hover:translate-x-0.5" aria-hidden="true" />
    </div>

    <div v-if="round.status !== 'draft'" class="grid gap-3 sm:grid-cols-2">
      <ProgressBar :value="share(round.progress.self_sent)" size="sm" tone="info" :label="t('lifecycle.reviews.round.selfSent')" :value-text="`${round.progress.self_sent} / ${people}`" />
      <ProgressBar :value="share(round.progress.published)" size="sm" tone="success" :label="t('lifecycle.reviews.round.published')" :value-text="`${round.progress.published} / ${people}`" />
    </div>
    <p v-else class="rounded-[12px] border border-dashed border-line px-3 py-2.5 text-sm text-muted">{{ t("lifecycle.reviews.card.draft", { count: round.questions.length }, round.questions.length) }}</p>

    <div class="flex flex-wrap items-center gap-2 text-xs">
      <span v-if="deadline" :class="['inline-flex items-center gap-1.5 rounded-full px-2.5 py-1', deadline.day < today && round.status !== 'draft' ? 'bg-danger-soft text-danger' : 'bg-surface-2 text-muted dark:bg-surface-3']">
        <CalendarClock :size="13" aria-hidden="true" />{{ deadline.label }}: {{ fmt.day(deadline.day, "medium") }}
      </span>
      <span v-if="round.progress.late" class="inline-flex items-center gap-1.5 rounded-full bg-warning-soft px-2.5 py-1 text-warning">
        <TriangleAlert :size="13" aria-hidden="true" />{{ t("lifecycle.reviews.card.late", { count: round.progress.late }, round.progress.late) }}
      </span>
      <span v-if="round.mine" class="inline-flex items-center gap-1.5 rounded-full bg-primary-soft px-2.5 py-1 font-medium text-primary">
        <PenLine :size="13" aria-hidden="true" />{{ t("lifecycle.reviews.card.mine", { count: round.mine }, round.mine) }}
      </span>
      <span v-if="round.status === 'closed' && round.closed_at" class="text-muted">{{ t("lifecycle.reviews.card.closedOn", { date: fmt.instant(round.closed_at, "date") }) }}</span>
    </div>
  </RouterLink>
</template>
