<script setup lang="ts">
/**
 * The contract's term on one line: how much of it has passed, today, the notice deadline of an
 * auto-renewing contract (a diamond) and the end, with the start and end dates under it. Amber
 * once the end is within the warning days, red once it has passed. `compact` is the list's
 * version: the track alone.
 */
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import { useFormat } from "@/lib/useFormat";

import { daysUntil, termPosition, termProgress } from "../lib";
import type { ContractStatus } from "../types";

const props = withDefaults(
  defineProps<{
    startsOn: string | null;
    endsOn: string | null;
    today: string;
    notice?: string | null;
    status: ContractStatus;
    autoRenews?: boolean;
    compact?: boolean;
  }>(),
  { notice: null, autoRenews: false, compact: false },
);

const { t } = useI18n();
const fmt = useFormat();

const progress = computed(() => termProgress(props.startsOn, props.endsOn, props.today));
const noticeAt = computed(() => termPosition(props.startsOn, props.endsOn, props.notice));
const left = computed(() => (props.endsOn ? daysUntil(props.endsOn, props.today) : null));
const fill = computed(() => {
  if (props.status === "terminated" || props.status === "ended") return "bg-subtle";
  if (props.status === "ending") return "bg-warning";
  if (props.status === "draft") return "bg-line-strong";
  return props.autoRenews ? "bg-info" : "bg-success";
});
</script>

<template>
  <div v-if="progress !== null" class="w-full" :data-testid="compact ? undefined : 'contract-term'">
    <div class="relative" :class="compact ? 'h-1.5' : 'h-2.5'" role="img" :aria-label="t('contracts.term.aria', { percent: Math.round(progress) })">
      <div class="absolute inset-0 overflow-hidden rounded-full bg-surface-3">
        <div class="h-full rounded-full transition-[width] duration-500" :class="fill" :style="{ width: `${progress}%` }" />
      </div>
      <span
        v-if="noticeAt !== null && !compact"
        class="absolute top-1/2 size-3 -translate-x-1/2 -translate-y-1/2 rotate-45 rounded-[2px] border-2 border-surface bg-warning shadow-sm"
        :style="{ left: `${noticeAt}%` }"
        :title="t('contracts.term.notice', { day: notice ? fmt.day(notice, 'medium') : '' })"
      />
      <span
        v-if="progress > 0 && progress < 100 && !compact"
        class="absolute top-1/2 size-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-surface bg-fg shadow-sm"
        :style="{ left: `${progress}%` }"
        :title="t('contracts.term.today')"
      />
    </div>
    <div v-if="!compact" class="mt-2 flex items-start justify-between gap-3 text-xs">
      <span class="text-muted">
        <span class="block text-subtle">{{ t("contracts.term.start") }}</span>
        <span class="font-medium tabular-nums text-fg">{{ startsOn ? fmt.day(startsOn, "medium") : "—" }}</span>
      </span>
      <span v-if="notice && noticeAt !== null" class="text-center text-muted">
        <span class="block text-subtle">{{ t("contracts.term.noticeShort") }}</span>
        <span class="font-medium tabular-nums text-warning">{{ fmt.day(notice, "medium") }}</span>
      </span>
      <span class="text-right text-muted">
        <span class="block text-subtle">{{ autoRenews ? t("contracts.term.renews") : t("contracts.term.end") }}</span>
        <span class="font-medium tabular-nums" :class="left !== null && left < 0 ? 'text-danger' : 'text-fg'">{{ endsOn ? fmt.day(endsOn, "medium") : "—" }}</span>
      </span>
    </div>
  </div>
</template>
