<script setup lang="ts">
/**
 * Overview tile "Payroll this month" (plan §1.2 KPI strip "next payroll", widget `payroll.kpi.next`):
 * the month's pay as it stands, projected to the month's end at today's pay setups, for how many
 * people, and the pay day. Opens the payroll runs. Only for payroll.view.
 */
import { ArrowUpRight, Banknote } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink } from "vue-router";

import type { Range } from "@/api/types";
import ErrorState from "@/components/ErrorState.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import { useFormat } from "@/lib/useFormat";

import { useOverview } from "../api";
import { hasAmount } from "../lib";

const props = defineProps<{ companyId: number; range?: Range; compare?: Range | null }>();

const { t } = useI18n();
const fmt = useFormat();
const overview = useOverview();
const projected = computed(() => overview.data.value?.projected ?? null);
const to = computed(() => `/c/${props.companyId}/payroll`);
</script>

<template>
  <RouterLink :to="to" class="ui-card group flex h-full min-h-[148px] min-w-0 flex-col p-4 transition-colors @container hover:border-line-strong" :aria-busy="overview.isPending.value || undefined" data-testid="payroll-widget">
    <div class="flex items-start gap-2">
      <Banknote :size="15" class="mt-px shrink-0 text-subtle" aria-hidden="true" />
      <span class="kpi-label" :title="t('payroll.widget.title')">{{ t("payroll.widget.title") }}</span>
      <ArrowUpRight :size="15" class="mt-px shrink-0 text-subtle opacity-0 transition-opacity group-hover:opacity-100" aria-hidden="true" />
    </div>
    <ErrorState v-if="overview.isError.value" class="mt-2.5" compact bare :error="overview.error.value" :retry="() => overview.refetch()" @click.stop.prevent />
    <template v-else-if="overview.isPending.value">
      <SkeletonBlock class="mt-2.5" width="62%" height="26px" />
      <SkeletonBlock class="mt-auto" height="32px" />
    </template>
    <template v-else-if="projected && hasAmount(projected.net)">
      <p class="kpi-value mt-1.5 truncate" :title="fmt.money(projected.net)">{{ fmt.money(projected.net, overview.data.value?.currency, { compact: true, decimals: "never" }) }}</p>
      <p class="mt-1 text-xs text-muted">{{ t("payroll.widget.projected", { month: fmt.day(projected.period, "monthYear") }) }}</p>
      <div class="mt-auto flex flex-wrap items-center gap-x-3 gap-y-1 pt-3 text-xs text-muted">
        <span>{{ t("payroll.runs.peopleCount", { n: projected.people }, projected.people) }}</span>
        <span v-if="overview.data.value?.next_pay_day">{{ t("payroll.widget.payDay", { date: fmt.day(overview.data.value.next_pay_day, "short") }) }}</span>
      </div>
    </template>
    <template v-else>
      <p class="kpi-value mt-1.5 text-subtle">—</p>
      <p class="mt-auto text-xs text-muted">{{ t("payroll.widget.empty") }}</p>
    </template>
  </RouterLink>
</template>
