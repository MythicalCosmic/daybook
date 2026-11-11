<script setup lang="ts">
/**
 * Turnover tax or VAT (v12): what the last twelve full months of the company's own books would
 * have cost under each regime, each with how it is worked out, the one that applies now and the
 * lowest one marked, why a regime isn't open (a business that sells medicines can't pay turnover
 * tax; income over the threshold), the threshold against the twelve months' income, the
 * assumptions, and "Check with your accountant". An estimate, never advice.
 */
import { Calculator, ChevronDown, Scale } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import ErrorState from "@/components/ErrorState.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import MoneyText from "@/components/MoneyText.vue";
import ProgressBar from "@/components/ProgressBar.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import { dec } from "@/lib/decimal";
import { useFormat } from "@/lib/useFormat";

import { useTaxCompare } from "../../credit";

const { t } = useI18n();
const fmt = useFormat();
const query = useTaxCompare();
const data = computed(() => query.data.value ?? null);
const opened = ref<string | null>(null);
const share = computed(() => {
  const d = data.value;
  if (!d || dec(d.threshold).isZero()) return 0;
  return Math.min(100, Math.round(dec(d.income).div(dec(d.threshold)).times(100).toNumber()));
});
</script>

<template>
  <section class="ui-card flex flex-col gap-3 p-4" :aria-label="t('finance.taxes.compare.title')" data-tax-compare>
    <header class="flex items-start gap-2">
      <Scale :size="16" class="mt-0.5 shrink-0 text-subtle" aria-hidden="true" />
      <div class="min-w-0 flex-1">
        <h2 class="text-sm font-semibold text-fg">{{ t("finance.taxes.compare.title") }}</h2>
        <p v-if="data" class="text-xs text-muted">{{ t("finance.taxes.compare.period", { from: fmt.day(data.from, "monthYear"), to: fmt.day(data.to, "monthYear") }) }}</p>
      </div>
    </header>

    <div v-if="query.isPending.value" class="flex flex-col gap-2"><SkeletonBlock v-for="n in 3" :key="n" height="56px" radius="10px" /></div>
    <ErrorState v-else-if="query.isError.value" compact :error="query.error.value" :retry="() => query.refetch()" />
    <template v-else-if="data">
      <InlineAlert v-if="!data.enough" tone="info" size="sm" :description="t('finance.taxes.compare.short')" />
      <p class="text-xs text-muted">
        {{ t("finance.taxes.compare.income") }}: <span class="font-semibold tabular-nums text-fg"><MoneyText :value="data.income" compact decimals="never" /></span>
      </p>
      <ul class="flex flex-col gap-2">
        <li v-for="option in data.options" :key="option.regime" :class="['rounded-[10px] border p-3', option.cheapest ? 'border-success/50 bg-success-soft/30' : 'border-line', !option.available && 'opacity-70']" :data-option="option.regime">
          <button type="button" class="flex w-full items-center gap-2 text-left" :aria-expanded="opened === option.regime" @click="opened = opened === option.regime ? null : option.regime">
            <span class="min-w-0 flex-1">
              <span class="flex flex-wrap items-center gap-1.5">
                <span class="text-sm font-semibold text-fg">{{ option.label }}</span>
                <StatusPill v-if="option.current" tone="primary" size="sm" :label="t('finance.taxes.compare.yours')" />
                <StatusPill v-if="option.cheapest" tone="success" size="sm" :label="t('finance.taxes.compare.lowest')" />
              </span>
              <span v-if="option.why_not" class="mt-0.5 block text-xs text-danger">{{ option.why_not }}</span>
            </span>
            <span class="shrink-0 text-right">
              <span class="block text-base font-semibold tabular-nums text-fg"><MoneyText :value="option.total" compact decimals="never" /></span>
              <span class="block text-[11px] text-subtle">{{ t("finance.taxes.compare.perYear") }}</span>
            </span>
            <ChevronDown :size="14" :class="['shrink-0 text-subtle transition-transform', opened === option.regime && 'rotate-180']" aria-hidden="true" />
          </button>
          <div v-if="opened === option.regime" class="mt-2 flex flex-col gap-1.5 border-t border-line pt-2">
            <p v-for="part in option.parts" :key="part.name" class="flex flex-col gap-0.5 text-xs">
              <span class="flex items-baseline justify-between gap-2"><span class="font-medium text-fg">{{ part.name }}</span><span class="font-semibold tabular-nums text-fg"><MoneyText :value="part.amount" decimals="never" /></span></span>
              <span class="flex items-start gap-1 text-muted"><Calculator :size="12" class="mt-0.5 shrink-0" aria-hidden="true" />{{ part.formula }}</span>
            </p>
            <p class="text-[11px] text-subtle">{{ option.law }}</p>
          </div>
        </li>
      </ul>
      <div class="flex flex-col gap-1">
        <ProgressBar :value="share" :max="100" :tone="data.over_threshold ? 'danger' : 'auto'" :label="t('finance.taxes.compare.threshold')" :value-text="fmt.money(data.threshold, undefined, { compact: true })" />
        <p class="text-[11px] text-subtle">{{ t("finance.taxes.compare.thresholdNote", { law: data.threshold_law }) }}</p>
      </div>
      <ul class="flex list-disc flex-col gap-0.5 pl-4 text-[11px] text-subtle">
        <li v-for="line in data.assumptions" :key="line">{{ line }}</li>
      </ul>
      <p class="text-xs font-medium text-warning">{{ data.disclaimer }}</p>
    </template>
  </section>
</template>
