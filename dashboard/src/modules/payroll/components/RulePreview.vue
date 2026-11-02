<script setup lang="ts">
/**
 * The rule builder's live preview (plan §6.2 "Rules builder with live preview"): a dry run of the
 * rule as it stands in the form, for a month (last month by default): who would get what and the
 * total, from the server (`rules/{id}/preview/`, `rules/preview/` for a new one). It follows the
 * form a moment after typing stops; nothing is proposed or saved.
 */
import { keepPreviousData, useQuery } from "@tanstack/vue-query";
import { refDebounced } from "@vueuse/core";
import { ChevronLeft, ChevronRight, Eye, UsersRound } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import ErrorState from "@/components/ErrorState.vue";
import IconButton from "@/components/IconButton.vue";
import MoneyText from "@/components/MoneyText.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { todayIn } from "@/lib/dates";
import { useFormat } from "@/lib/useFormat";
import { useCompanyId, useCompanyStore } from "@/stores/company";

import { payrollApi, payrollKeys } from "../api";
import { metricUnit, periodOf, previewBody, ruleProblems, shiftPeriod, signedAmount, type RuleDraft } from "../lib";

const props = defineProps<{ draft: RuleDraft; ruleId: number | null }>();

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const cid = useCompanyId();
const current = computed(() => periodOf(todayIn(company.timezone)));
const period = ref(shiftPeriod(current.value, -1));

const valid = computed(() => ruleProblems(props.draft).length === 0);
const body = computed(() => JSON.stringify(previewBody(props.draft, period.value)));
const settled = refDebounced(body, 450);
const query = useQuery({
  queryKey: computed(() => payrollKeys.of(cid.value, "rule-preview", { id: props.ruleId, body: settled.value })),
  queryFn: ({ signal }) => payrollApi.previewRule(cid.value, props.ruleId, JSON.parse(settled.value) as Record<string, unknown>, signal),
  enabled: computed(() => cid.value > 0 && valid.value),
  placeholderData: keepPreviousData,
  staleTime: 30_000,
});
const result = computed(() => (valid.value ? (query.data.value ?? null) : null));
const waiting = computed(() => valid.value && (query.isFetching.value || body.value !== settled.value));

function valueText(value: string | null): string {
  if (value === null) return "—";
  const unit = metricUnit(props.draft.metric);
  if (unit === "percent") return `${fmt.number(value, 1)} %`;
  if (unit === "money") return fmt.money(value, undefined, { compact: true });
  if (unit === "minutes") return t("payroll.rules.unit.minutes", { n: fmt.number(value, 1) });
  if (unit === "hours") return t("payroll.rules.unit.hours", { n: fmt.number(value, 1) });
  return fmt.number(value, 2);
}
const LIMIT = 8;
const expanded = ref(false);
const rows = computed(() => (expanded.value ? (result.value?.rows ?? []) : (result.value?.rows ?? []).slice(0, LIMIT)));
</script>

<template>
  <section class="flex flex-col gap-3 rounded-[12px] border border-line bg-surface-2/50 p-3.5" :aria-busy="waiting || undefined" data-testid="rule-preview">
    <header class="flex flex-col gap-2">
      <div class="flex items-center gap-2">
        <Eye :size="16" class="shrink-0 text-subtle" />
        <h3 class="min-w-0 flex-1 truncate text-sm font-semibold text-fg">{{ t("payroll.rules.preview") }}</h3>
      </div>
      <div class="flex items-center justify-between rounded-[10px] border border-line bg-surface px-1 py-0.5">
        <IconButton :icon="ChevronLeft" size="sm" :label="t('payroll.period.previous')" @click="period = shiftPeriod(period, -1)" />
        <span class="text-sm font-medium tabular-nums text-fg" data-testid="preview-month">{{ fmt.day(period, "monthYear") }}</span>
        <IconButton :icon="ChevronRight" size="sm" :label="t('payroll.period.next')" :disabled="period >= current" @click="period = shiftPeriod(period, 1)" />
      </div>
    </header>

    <p v-if="!valid" class="rounded-[10px] bg-surface px-3 py-3 text-sm text-muted" data-testid="preview-incomplete">{{ t("payroll.rules.previewIncomplete") }}</p>
    <ErrorState v-else-if="query.isError.value && !result" compact :error="query.error.value" :retry="() => query.refetch()" />
    <div v-else-if="!result" class="flex flex-col gap-2">
      <SkeletonBlock v-for="n in 4" :key="n" height="36px" radius="8px" />
    </div>
    <template v-else>
      <div :class="['flex items-baseline justify-between gap-3 rounded-[10px] bg-surface px-3 py-2.5 transition-opacity', waiting && 'opacity-60']">
        <span class="inline-flex items-center gap-1.5 text-sm text-muted"><UsersRound :size="14" />{{ t("payroll.rules.previewPeople", { n: result.rows.length }, result.rows.length) }}</span>
        <span class="text-base font-semibold tabular-nums" data-testid="preview-total"><MoneyText :value="signedAmount({ kind: draft.kind, amount: result.total })" :currency="result.currency" :sign="draft.kind === 'bonus' ? 'always' : 'auto'" colored /></span>
      </div>
      <p v-if="!result.rows.length" class="px-1 text-sm text-muted">{{ t("payroll.rules.previewNobody", { month: fmt.day(period, "monthYear") }) }}</p>
      <ul v-else :class="['flex flex-col divide-y divide-line rounded-[10px] border border-line bg-surface transition-opacity', waiting && 'opacity-60']">
        <li v-for="row in rows" :key="row.member.id" class="flex min-h-11 items-center gap-2.5 px-3 py-1.5">
          <UserAvatar :name="row.member.name" :src="row.member.photo_url" :size="24" />
          <div class="min-w-0 flex-1">
            <p class="truncate text-sm font-medium text-fg">{{ row.member.name }}</p>
            <p class="truncate text-xs text-muted">{{ row.detail || valueText(row.value) }}</p>
          </div>
          <span class="shrink-0 text-sm font-semibold tabular-nums"><MoneyText :value="signedAmount({ kind: draft.kind, amount: row.amount })" :currency="result.currency" :sign="draft.kind === 'bonus' ? 'always' : 'auto'" colored /></span>
        </li>
      </ul>
      <button v-if="result.rows.length > LIMIT" type="button" class="self-start text-sm font-semibold text-accent-fg hover:underline" @click="expanded = !expanded">
        {{ expanded ? t("payroll.warnings.less") : t("payroll.warnings.more", { n: result.rows.length - LIMIT }, result.rows.length - LIMIT) }}
      </button>
      <p v-if="result.checked" class="text-xs text-subtle">{{ t("payroll.rules.previewChecked", { n: result.checked }, result.checked) }}</p>
    </template>
  </section>
</template>
