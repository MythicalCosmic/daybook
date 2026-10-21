<script setup lang="ts">
/**
 * How old the money owed is (plan §6.2 "aging bar"): one bar split into not yet due, 1–30,
 * 31–60, 61–90 and 90+ days late, with the amount of each part underneath.
 */
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import MoneyText from "@/components/MoneyText.vue";
import ProgressBar from "@/components/ProgressBar.vue";
import { dec } from "@/lib/decimal";

import { AGING_BUCKETS, AGING_COLORS } from "../lib";
import type { AgingTotals } from "../types";

const props = withDefaults(defineProps<{ totals: AgingTotals | null | undefined; compact?: boolean }>(), { compact: false });

const { t } = useI18n();
const segments = computed(() =>
  AGING_BUCKETS.map((bucket) => ({ value: props.totals ? dec(props.totals[bucket]).toNumber() : 0, color: AGING_COLORS[bucket], label: t(`finance.aging.${bucket}`) })),
);
const empty = computed(() => !props.totals || dec(props.totals.total).isZero());
</script>

<template>
  <!-- The legend takes as many columns as its own width allows (not the window's: beside the
       sidebar and the total, five columns cut every amount to "UZS …" on a 1024 px screen). -->
  <div class="@container flex flex-col gap-2.5">
    <ProgressBar v-if="!empty" :segments="segments" size="md" role="img" :aria-label="t('finance.aging.title')" />
    <div v-else class="h-2 rounded-full bg-surface-2" />
    <ul :class="['grid grid-cols-2 gap-x-4 gap-y-1.5 @sm:grid-cols-3', compact ? '@xl:grid-cols-5' : '@2xl:grid-cols-5']" data-testid="aging-legend">
      <li v-for="bucket in AGING_BUCKETS" :key="bucket" class="flex min-w-0 items-center gap-2" :title="t(`finance.aging.${bucket}`)">
        <span class="size-2.5 shrink-0 rounded-full" :style="{ background: AGING_COLORS[bucket] }" aria-hidden="true" />
        <span class="min-w-0">
          <span class="block truncate text-xs text-muted">{{ t(`finance.aging.${bucket}`) }}</span>
          <span class="block truncate text-sm font-semibold tabular-nums text-fg"><MoneyText :value="totals?.[bucket] ?? '0'" compact /></span>
        </span>
      </li>
    </ul>
  </div>
</template>
