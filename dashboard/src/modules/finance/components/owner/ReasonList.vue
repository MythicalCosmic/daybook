<script setup lang="ts">
/**
 * Why the safe amount is what it is, as a receipt: the cash on the business's accounts, less each
 * payment due within the horizon (overdue first, then the biggest; payroll's own estimate marked),
 * the buffer and the planned purchases, down to the safe amount. Bills whose amount nobody knows
 * yet are listed apart. Each line opens where it is paid.
 */
import { Banknote, CalendarClock, ChevronDown, Landmark, ListChecks, Receipt, ShieldHalf, ShoppingCart, Truck, Users, Wifi } from "@lucide/vue";
import type { Component } from "vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink } from "vue-router";

import MoneyText from "@/components/MoneyText.vue";
import UiBadge from "@/components/UiBadge.vue";
import { useFormat } from "@/lib/useFormat";

import type { OwnerMoney, ReasonKind } from "../../ownerMoney";

const props = defineProps<{ data: OwnerMoney }>();
const emit = defineEmits<{ settings: [] }>();

const { t } = useI18n();
const fmt = useFormat();
const SHOWN = 6;
const expanded = ref(false);

const ICONS: Record<ReasonKind, Component> = {
  bill: Receipt,
  auto: Wifi,
  tax: Landmark,
  payable: Truck,
  payroll: Users,
  loan: Banknote,
  installment: CalendarClock,
};
const known = computed(() => props.data.reasons.filter((reason) => reason.amount !== null));
const unknown = computed(() => props.data.reasons.filter((reason) => reason.amount === null));
const visible = computed(() => (expanded.value ? known.value : known.value.slice(0, SHOWN)));
const hidden = computed(() => known.value.length - visible.value.length);

function when(reason: { date: string; overdue: boolean }): string {
  if (reason.overdue) return t("finance.myMoney.overdueSince", { date: fmt.day(reason.date, "short") });
  if (reason.date === props.data.today) return t("finance.myMoney.dueToday");
  return fmt.day(reason.date, "weekdayShort");
}
</script>

<template>
  <section class="ui-card flex flex-col p-4 sm:p-5" :aria-label="t('finance.myMoney.whyTitle')" data-reasons>
    <header class="mb-3 flex items-start gap-2">
      <ListChecks :size="16" class="mt-0.5 shrink-0 text-subtle" aria-hidden="true" />
      <div class="min-w-0 flex-1">
        <h3 class="text-sm font-semibold text-fg">{{ t("finance.myMoney.whyTitle") }}</h3>
        <p class="text-xs text-muted">{{ t("finance.myMoney.whySubtitle", { n: data.horizon_days }, data.horizon_days) }}</p>
      </div>
    </header>

    <ol class="-mx-2 flex flex-col">
      <li class="flex items-center gap-3 rounded-[10px] px-2 py-2">
        <span class="grid size-8 shrink-0 place-items-center rounded-[9px] bg-success-soft text-success" aria-hidden="true"><Banknote :size="16" /></span>
        <div class="min-w-0 flex-1">
          <p class="truncate text-sm font-semibold text-fg">{{ t("finance.myMoney.cashLine") }}</p>
          <p class="truncate text-xs text-muted">{{ t("finance.myMoney.cashLineHint") }}</p>
        </div>
        <span class="shrink-0 text-sm font-semibold tabular-nums text-fg"><MoneyText class="sm:hidden" :value="data.cash" compact /><MoneyText class="hidden sm:inline" :value="data.cash" /></span>
      </li>

      <li v-for="reason in visible" :key="reason.key">
        <RouterLink :to="reason.url" class="flex items-center gap-3 rounded-[10px] px-2 py-2 transition-colors hover:bg-highlight" :data-reason="reason.kind">
          <span :class="['grid size-8 shrink-0 place-items-center rounded-[9px]', reason.overdue ? 'bg-danger-soft text-danger' : 'bg-surface-2 text-muted']" aria-hidden="true">
            <component :is="ICONS[reason.kind]" :size="16" />
          </span>
          <div class="min-w-0 flex-1">
            <p class="flex min-w-0 items-center gap-1.5">
              <span class="truncate text-sm font-semibold text-fg" :title="reason.title">{{ reason.kind === "payroll" && reason.estimate ? t("finance.myMoney.payroll") : reason.title }}</span>
              <UiBadge v-if="reason.estimate" size="sm" tone="neutral">{{ t("finance.myMoney.estimate") }}</UiBadge>
            </p>
            <p class="truncate text-xs" :class="reason.overdue ? 'text-danger' : 'text-muted'">
              {{ when(reason) }}<template v-if="reason.kind === 'payable'"> · {{ t("finance.myMoney.payments", { n: reason.count }, reason.count) }}</template>
              <template v-else-if="reason.subtitle && !(reason.kind === 'payroll' && reason.estimate)"> · {{ reason.subtitle }}</template>
            </p>
          </div>
          <span class="shrink-0 text-sm font-semibold tabular-nums text-fg">−<MoneyText class="sm:hidden" :value="reason.amount" compact /><MoneyText class="hidden sm:inline" :value="reason.amount" /></span>
        </RouterLink>
      </li>

      <li v-if="hidden > 0 || expanded" class="px-2 py-1">
        <button type="button" class="inline-flex items-center gap-1 rounded-[6px] px-1 py-0.5 text-sm font-semibold text-muted hover:bg-highlight hover:text-fg" data-more @click="expanded = !expanded">
          <ChevronDown :size="14" :class="['transition-transform duration-180', expanded && 'rotate-180']" />
          {{ expanded ? t("finance.myMoney.fewer") : t("finance.myMoney.more", { n: hidden }, hidden) }}
        </button>
      </li>

      <li class="flex items-center gap-3 rounded-[10px] px-2 py-2">
        <span class="grid size-8 shrink-0 place-items-center rounded-[9px] bg-warning-soft text-warning" aria-hidden="true"><ShieldHalf :size="16" /></span>
        <div class="min-w-0 flex-1">
          <p class="truncate text-sm font-semibold text-fg">{{ t("finance.myMoney.bufferLine") }}</p>
          <p class="truncate text-xs text-muted">
            {{ data.buffer.auto ? t("finance.myMoney.bufferAuto") : t("finance.myMoney.bufferSet") }} ·
            <button type="button" class="font-medium text-primary hover:underline" data-buffer-edit @click="emit('settings')">{{ t("finance.myMoney.change") }}</button>
          </p>
        </div>
        <span class="shrink-0 text-sm font-semibold tabular-nums text-fg">−<MoneyText class="sm:hidden" :value="data.buffer.amount" compact /><MoneyText class="hidden sm:inline" :value="data.buffer.amount" /></span>
      </li>

      <li v-if="Number(data.planned) > 0" class="flex items-center gap-3 rounded-[10px] px-2 py-2">
        <span class="grid size-8 shrink-0 place-items-center rounded-[9px] bg-info-soft text-info" aria-hidden="true"><ShoppingCart :size="16" /></span>
        <div class="min-w-0 flex-1">
          <p class="truncate text-sm font-semibold text-fg">{{ t("finance.myMoney.plannedLine") }}</p>
          <p class="truncate text-xs text-muted">{{ t("finance.myMoney.plannedCount", { n: data.purchases.kept.length }, data.purchases.kept.length) }}</p>
        </div>
        <span class="shrink-0 text-sm font-semibold tabular-nums text-fg">−<MoneyText class="sm:hidden" :value="data.planned" compact /><MoneyText class="hidden sm:inline" :value="data.planned" /></span>
      </li>

      <li class="mt-1 flex items-center gap-3 border-t border-line px-2 pb-1 pt-3">
        <span class="min-w-0 flex-1 text-sm font-semibold text-fg">{{ t("finance.myMoney.safeLine") }}</span>
        <span class="shrink-0 text-md font-semibold tabular-nums" :class="Number(data.safe) > 0 ? 'text-success' : 'text-fg'"><MoneyText :value="data.safe" /></span>
      </li>
    </ol>

    <div v-if="unknown.length" class="mt-3 rounded-[10px] bg-surface-2/70 px-3 py-2.5 dark:bg-surface-3/40" data-unknown>
      <p class="text-xs font-semibold text-muted">{{ t("finance.myMoney.unknownTitle", { n: unknown.length }, unknown.length) }}</p>
      <p class="mt-0.5 text-xs text-muted">{{ unknown.map((reason) => `${reason.title} (${fmt.day(reason.date, "short")})`).join(" · ") }}</p>
    </div>
  </section>
</template>
