<script setup lang="ts">
/**
 * The owner's money headline: what is safe to take out today in big type, how the cash splits
 * (payments due, the buffer, planned purchases, the safe part) as one bar with its legend, the
 * take / put buttons, and this month's draws beside the monthly suggestion.
 */
import { ArrowDownToLine, ArrowUpFromLine, CircleAlert, ShieldCheck, SlidersHorizontal } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import InlineAlert from "@/components/InlineAlert.vue";
import MoneyText from "@/components/MoneyText.vue";
import UiButton from "@/components/UiButton.vue";
import UiTooltip from "@/components/UiTooltip.vue";
import { useFormat } from "@/lib/useFormat";

import { cashSplit, type OwnerMoney } from "../../ownerMoney";

const props = defineProps<{ data: OwnerMoney; canWrite: boolean }>();
const emit = defineEmits<{ take: []; put: []; settings: [] }>();

const { t } = useI18n();
const fmt = useFormat();

const COLORS = { due: "var(--c-chart-1)", buffer: "var(--c-warning)", planned: "var(--c-info)", safe: "var(--c-success)" } as const;
const parts = computed(() => cashSplit(props.data));
const safe = computed(() => Number(props.data.safe));
const short = computed(() => Number(props.data.short));
const legend = computed(() =>
  parts.value
    .filter((part) => part.key !== "planned" || part.amount > 0)
    .map((part) => ({ ...part, color: COLORS[part.key], label: t(`finance.myMoney.part.${part.key}`) })),
);
</script>

<template>
  <section class="ui-card relative overflow-hidden" :aria-label="t('finance.myMoney.safeLabel')" data-safe-hero>
    <div class="pointer-events-none absolute -right-16 -top-24 size-72 rounded-full bg-success-soft opacity-70 blur-2xl dark:opacity-40" aria-hidden="true" />
    <div class="relative grid gap-6 p-5 sm:p-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,300px)]">
      <div class="min-w-0">
        <p class="flex items-center gap-1.5 text-sm font-medium text-muted">
          <ShieldCheck :size="16" :class="safe > 0 ? 'text-success' : 'text-subtle'" aria-hidden="true" />
          {{ t("finance.myMoney.safeLabel") }}
        </p>
        <p class="mt-2 text-[40px] font-semibold leading-none tracking-[-0.025em] tabular-nums sm:text-[52px]" :class="safe > 0 ? 'text-success' : 'text-fg'" data-safe-amount>
          <MoneyText :value="data.safe" />
        </p>
        <p class="mt-2 max-w-[560px] text-sm text-muted">
          {{ t("finance.myMoney.safeExplain", { days: data.horizon_days }) }}
        </p>

        <div class="mt-5">
          <div class="flex h-3 w-full overflow-hidden rounded-full bg-surface-2" role="img" :aria-label="t('finance.myMoney.splitLabel')">
            <span
              v-for="part in parts"
              :key="part.key"
              class="h-full transition-[width] duration-300 ease-out first:rounded-l-full last:rounded-r-full"
              :style="{ width: `${part.share}%`, background: COLORS[part.key] }"
            />
          </div>
          <dl class="mt-3 grid grid-cols-2 gap-x-4 gap-y-2.5 sm:grid-cols-4">
            <div class="min-w-0">
              <dt class="text-xs text-muted">{{ t("finance.myMoney.cash") }}</dt>
              <dd class="text-sm font-semibold tabular-nums text-fg"><MoneyText :value="data.cash" compact /></dd>
            </div>
            <div v-for="item in legend.filter((part) => part.key !== 'safe')" :key="item.key" class="min-w-0">
              <dt class="flex items-center gap-1.5 truncate text-xs text-muted">
                <span class="size-2 shrink-0 rounded-full" :style="{ background: item.color }" aria-hidden="true" />{{ item.label }}
              </dt>
              <dd class="text-sm font-semibold tabular-nums text-fg">−<MoneyText :value="String(item.amount)" compact /></dd>
            </div>
          </dl>
        </div>

        <InlineAlert v-if="short > 0" class="mt-4" tone="warning" size="sm" :icon="CircleAlert" :title="t('finance.myMoney.shortTitle')" :description="t('finance.myMoney.shortBody', { amount: fmt.money(data.short, undefined, { compact: true }) })" />
        <p v-if="!data.complete" class="mt-3 text-xs text-warning">{{ t("finance.myMoney.incomplete") }}</p>

        <div v-if="canWrite" class="mt-5 flex flex-wrap items-center gap-2">
          <UiButton variant="primary" :icon="ArrowUpFromLine" data-take @click="emit('take')">{{ t("finance.myMoney.take") }}</UiButton>
          <UiButton variant="secondary" :icon="ArrowDownToLine" data-put @click="emit('put')">{{ t("finance.myMoney.put") }}</UiButton>
          <UiTooltip :content="t('finance.myMoney.settingsHint')">
            <UiButton variant="ghost" :icon="SlidersHorizontal" data-settings @click="emit('settings')">{{ t("finance.myMoney.settings") }}</UiButton>
          </UiTooltip>
        </div>
      </div>

      <aside class="flex min-w-0 flex-col gap-3 rounded-[12px] border border-line bg-surface/80 p-4 backdrop-blur-sm" :aria-label="t('finance.myMoney.thisMonth')">
        <p class="text-xs font-semibold uppercase tracking-wide text-subtle">{{ t("finance.myMoney.thisMonth") }}</p>
        <div class="flex items-baseline justify-between gap-3">
          <span class="text-sm text-muted">{{ t("finance.myMoney.drawn") }}</span>
          <span class="text-lg font-semibold tabular-nums text-fg"><MoneyText :value="data.month.drawn" compact /></span>
        </div>
        <div class="flex items-baseline justify-between gap-3">
          <span class="text-sm text-muted">{{ t("finance.myMoney.putIn") }}</span>
          <span class="text-sm font-semibold tabular-nums text-fg"><MoneyText :value="data.month.put_in" compact /></span>
        </div>
        <div class="border-t border-line pt-3">
          <div class="flex items-baseline justify-between gap-3">
            <span class="text-sm text-muted">{{ t("finance.myMoney.monthly") }}</span>
            <span class="text-lg font-semibold tabular-nums" :class="Number(data.suggestion.monthly) > 0 ? 'text-fg' : 'text-subtle'" data-monthly>
              <MoneyText :value="data.suggestion.monthly" compact />
            </span>
          </div>
          <p class="mt-1 text-xs leading-relaxed text-muted">
            <template v-if="data.suggestion.below_buffer_on">{{ t("finance.myMoney.monthlyNone", { date: fmt.day(data.suggestion.below_buffer_on, "short") }) }}</template>
            <template v-else-if="data.suggestion.dates.length">{{ t("finance.myMoney.monthlyHint", { date: fmt.day(data.suggestion.dates[0]!, "short") }) }}</template>
          </p>
          <p v-if="data.suggestion.above_profit && Number(data.suggestion.monthly) > 0" class="mt-2 rounded-[8px] bg-warning-soft px-2.5 py-1.5 text-xs leading-relaxed text-warning" data-above-profit>
            {{ t("finance.myMoney.aboveProfit", { amount: fmt.money(data.suggestion.profit_average, undefined, { compact: true }) }) }}
          </p>
        </div>
      </aside>
    </div>
  </section>
</template>
