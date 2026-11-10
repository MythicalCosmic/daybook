<script setup lang="ts">
/**
 * A policy in the list: its category, title and version, who it applies to, and how the signing
 * goes (signed of everyone asked, waiting and late, the deadline), or that it is a draft or only
 * to read. The whole card opens the policy.
 */
import { CalendarClock, MapPin, PenLine, Users } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink } from "vue-router";

import ProgressBar from "@/components/ProgressBar.vue";
import StatusPill from "@/components/StatusPill.vue";
import { useFormat } from "@/lib/useFormat";
import { useCompanyToday } from "@/stores/company";

import { audienceParts, CATEGORY_ICONS, CATEGORY_TINTS, daysUntil } from "./lib";
import type { Policy } from "./types";

const props = defineProps<{ policy: Policy; to: string }>();

const { t } = useI18n();
const fmt = useFormat();
const today = useCompanyToday();

const audience = computed(() => audienceParts(props.policy, { everyPosition: t("hr.policy.everyPosition"), everyBranch: t("hr.policy.everyBranch") }));
const tally = computed(() => props.policy.tally);
const segments = computed(() => {
  const row = tally.value;
  if (!row || !row.total) return [];
  // The bar scales its segments to their sum: the ones still waiting are the empty track.
  return [
    { value: row.signed, color: "var(--c-success)", label: t("hr.policy.kpi.signed") },
    { value: row.late, color: "var(--c-danger)", label: t("hr.policy.kpi.late") },
    { value: row.waiting, color: "transparent", label: t("hr.policy.kpi.waiting") },
  ];
});
const deadline = computed(() => {
  const due = props.policy.due_on;
  const row = tally.value;
  if (!due || !row || row.waiting + row.late === 0) return null;
  const left = daysUntil(due, today.value);
  return left >= 0 ? t("hr.policy.signBy", { date: fmt.day(due, "short") }) : t("hr.policy.deadlinePassed", { date: fmt.day(due, "short") });
});
</script>

<template>
  <RouterLink :to="to" class="ui-card group flex h-full flex-col gap-3.5 p-4 transition-colors hover:border-line-strong" :data-policy="policy.id">
    <div class="flex items-start gap-3">
      <span :class="['grid size-10 shrink-0 place-items-center rounded-[10px]', CATEGORY_TINTS[policy.category]]" aria-hidden="true">
        <component :is="CATEGORY_ICONS[policy.category]" :size="19" />
      </span>
      <div class="min-w-0 flex-1">
        <p class="line-clamp-2 text-base font-semibold text-fg group-hover:text-primary">{{ policy.title }}</p>
        <p class="truncate text-sm text-muted">
          {{ t(`hr.policy.category.${policy.category}`) }}
          <template v-if="policy.version"> · {{ t("hr.policy.version", { n: policy.version.number }) }}</template>
        </p>
      </div>
      <StatusPill v-if="!policy.is_active" tone="neutral" size="sm" :label="t('hr.policy.status.archived')" />
      <StatusPill v-else-if="!policy.version" tone="warning" size="sm" :label="t('hr.policy.status.draft')" />
      <StatusPill v-else-if="policy.draft" tone="neutral" variant="outline" size="sm" :dot="false" :icon="PenLine" :label="t('hr.policy.draftOf', { n: policy.draft.number })" />
    </div>

    <dl class="flex flex-col gap-1 text-sm">
      <div class="flex min-w-0 items-center gap-2 text-muted">
        <dt class="sr-only">{{ t("hr.policy.field.positions") }}</dt>
        <Users :size="14" class="shrink-0 text-subtle" aria-hidden="true" />
        <dd class="min-w-0 truncate" :title="audience.positions">{{ audience.positions }}</dd>
      </div>
      <div class="flex min-w-0 items-center gap-2 text-muted">
        <dt class="sr-only">{{ t("hr.policy.field.branches") }}</dt>
        <MapPin :size="14" class="shrink-0 text-subtle" aria-hidden="true" />
        <dd class="min-w-0 truncate" :title="audience.branches">{{ audience.branches }}</dd>
      </div>
    </dl>

    <div class="mt-auto flex flex-col gap-2">
      <template v-if="policy.is_active && policy.version && policy.requires_ack && tally">
        <div class="flex items-baseline justify-between gap-2">
          <p class="text-sm font-medium text-fg tabular-nums">
            {{ tally.total ? t("hr.policy.signedOf", { signed: tally.signed, total: tally.total }) : t("hr.policy.nobodyAsked") }}
          </p>
          <p v-if="tally.total && tally.signed === tally.total" class="text-xs font-medium text-success">{{ t("hr.policy.allSigned") }}</p>
        </div>
        <ProgressBar v-if="tally.total" :segments="segments" :max="tally.total" size="sm" />
        <div class="flex flex-wrap items-center gap-1.5">
          <StatusPill v-if="tally.late" tone="danger" size="sm" :label="t('hr.policy.count.late', { n: tally.late }, tally.late)" />
          <StatusPill v-if="tally.waiting" tone="info" size="sm" :label="t('hr.policy.count.waiting', { n: tally.waiting }, tally.waiting)" />
          <span v-if="deadline" class="ml-auto inline-flex items-center gap-1 text-xs text-muted"><CalendarClock :size="13" aria-hidden="true" />{{ deadline }}</span>
        </div>
      </template>
      <div v-else class="flex flex-wrap items-center gap-1.5">
        <StatusPill v-if="!policy.requires_ack" tone="neutral" variant="outline" size="sm" :dot="false" :label="t('hr.policy.toRead')" />
        <span v-if="!policy.version" class="text-xs text-muted">{{ t("hr.policy.neverPublished") }}</span>
        <span class="ml-auto text-xs text-subtle">{{ t("hr.policy.updated", { date: fmt.day(policy.updated_at.slice(0, 10), "medium") }) }}</span>
      </div>
    </div>
  </RouterLink>
</template>
