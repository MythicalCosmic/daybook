<script setup lang="ts">
/**
 * The rule builder's preview (plan §6.2 "Rules builder with live preview"): a dry run of the saved
 * rule for a month (`rules/{id}/preview/ {period}`, last month by default): who it would give what
 * and the total, then the people it looked at who get nothing. Nothing is proposed or saved.
 * The server runs the rule as saved, so while the form differs the panel says so; a new rule is
 * saved first (it may stay switched off) and can then be tried on any month.
 */
import { keepPreviousData, useQuery } from "@tanstack/vue-query";
import { ChevronDown, ChevronLeft, ChevronRight, Eye, UsersRound } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import ErrorState from "@/components/ErrorState.vue";
import IconButton from "@/components/IconButton.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { endOfMonth, todayIn } from "@/lib/dates";
import { useFormat } from "@/lib/useFormat";
import { useCompanyId, useCompanyStore } from "@/stores/company";

import { payrollApi, payrollKeys } from "../api";
import { metricUnit, OP_SYMBOLS, periodOf, previewSplit, ruleChanged, shiftPeriod, signedAmount, type RuleDraft } from "../lib";
import type { Rule, RulePreviewRow } from "../types";
import PayAmount from "./PayAmount.vue";

const props = defineProps<{ draft: RuleDraft; rule: Rule | null }>();

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const cid = useCompanyId();
const current = computed(() => periodOf(todayIn(company.timezone)));
const period = ref(shiftPeriod(current.value, -1));

const query = useQuery({
  // The saved rule's last change is in the key: saving runs the preview again.
  queryKey: computed(() => payrollKeys.of(cid.value, "rule-preview", { id: props.rule?.id ?? 0, period: period.value, saved: props.rule?.updated_at ?? "" })),
  queryFn: ({ signal }) => payrollApi.previewRule(cid.value, props.rule!.id, period.value, signal),
  enabled: computed(() => cid.value > 0 && !!props.rule),
  // The last answer stays (dimmed) while another month or the saved change loads, never another rule's.
  placeholderData: (previous, previousQuery) => ((previousQuery?.queryKey[3] as { id?: number } | undefined)?.id === props.rule?.id ? keepPreviousData(previous) : undefined),
  staleTime: 30_000,
});
const result = computed(() => (props.rule ? (query.data.value ?? null) : null));
const waiting = computed(() => query.isFetching.value);
const changed = computed(() => !!props.rule && ruleChanged(props.rule, props.draft));
const split = computed(() => previewSplit(result.value?.rows ?? []));
const running = computed(() => !!result.value && result.value.to < endOfMonth(result.value.period));

const kind = computed(() => props.rule?.kind ?? props.draft.kind);
function valueText(value: string | null): string {
  if (value === null) return "—";
  const unit = metricUnit(props.rule?.metric ?? props.draft.metric);
  if (unit === "percent") return `${fmt.number(value, 1)} %`;
  if (unit === "money") return fmt.money(value, result.value?.currency, { compact: true });
  if (unit === "minutes") return t("payroll.rules.unit.minutes", { n: fmt.number(value, 1) });
  if (unit === "hours") return t("payroll.rules.unit.hours", { n: fmt.number(value, 1) });
  return fmt.number(value, 2);
}
/** "96.4 % · ≥ 95 %", "5 · Counted: 3": the value, then how the amount came out. */
function detail(row: RulePreviewRow): string {
  const parts = [valueText(row.value)];
  if (row.tier !== null && props.rule) parts.push(`${OP_SYMBOLS[props.rule.op]} ${valueText(row.tier)}`);
  if (row.units !== null) parts.push(t("payroll.rules.previewUnits", { n: fmt.number(row.units, 2) }));
  return parts.join(" · ");
}

const LIMIT = 8;
const expanded = ref(false);
const showOthers = ref(false);
const earning = computed(() => (expanded.value ? split.value.earning : split.value.earning.slice(0, LIMIT)));
</script>

<template>
  <section class="flex flex-col gap-3 rounded-[12px] border border-line bg-surface-2/50 p-3.5" :aria-busy="waiting || undefined" data-testid="rule-preview">
    <header class="flex flex-col gap-2">
      <div class="flex items-center gap-2">
        <Eye :size="16" class="shrink-0 text-subtle" />
        <h3 class="min-w-0 flex-1 truncate text-sm font-semibold text-fg">{{ t("payroll.rules.preview") }}</h3>
      </div>
      <div v-if="rule" class="flex items-center justify-between rounded-[10px] border border-line bg-surface px-1 py-0.5">
        <IconButton :icon="ChevronLeft" size="sm" :label="t('payroll.period.previous')" @click="period = shiftPeriod(period, -1)" />
        <span class="text-sm font-medium tabular-nums text-fg" data-testid="preview-month">{{ fmt.day(period, "monthYear") }}</span>
        <IconButton :icon="ChevronRight" size="sm" :label="t('payroll.period.next')" :disabled="period >= current" @click="period = shiftPeriod(period, 1)" />
      </div>
    </header>

    <p v-if="!rule" class="rounded-[10px] bg-surface px-3 py-3 text-sm text-muted" data-testid="preview-save-first">{{ t("payroll.rules.previewSaveFirst") }}</p>
    <template v-else>
      <InlineAlert v-if="changed" tone="info" size="sm" data-testid="preview-saved-only">{{ t("payroll.rules.previewSavedOnly") }}</InlineAlert>
      <ErrorState v-if="query.isError.value && !result" compact :error="query.error.value" :retry="() => query.refetch()" />
      <div v-else-if="!result" class="flex flex-col gap-2">
        <SkeletonBlock v-for="n in 4" :key="n" height="36px" radius="8px" />
      </div>
      <template v-else>
        <div :class="['flex flex-col gap-0.5 rounded-[10px] bg-surface px-3 py-2.5 transition-opacity', waiting && 'opacity-60']">
          <div class="flex items-baseline justify-between gap-3">
            <span class="inline-flex items-center gap-1.5 text-sm text-muted">
              <UsersRound :size="14" />{{ split.hidden ? t("payroll.rules.previewPeople", { n: result.rows.length }, result.rows.length) : t("payroll.rules.previewPeople", { n: split.earning.length }, split.earning.length) }}
            </span>
            <span class="text-base font-semibold tabular-nums" data-testid="preview-total">
              <PayAmount :value="result.total === undefined ? undefined : signedAmount({ kind, amount: result.total })" :currency="result.currency" :sign="kind === 'bonus' ? 'always' : 'auto'" colored />
            </span>
          </div>
          <p v-if="running" class="text-xs text-subtle">{{ t("payroll.rules.previewSoFar", { range: fmt.range({ from: result.period, to: result.to }) }) }}</p>
        </div>

        <p v-if="!split.earning.length" class="px-1 text-sm text-muted" data-testid="preview-nobody">{{ t("payroll.rules.previewNobody", { month: fmt.day(period, "monthYear") }) }}</p>
        <ul v-else :class="['flex flex-col divide-y divide-line rounded-[10px] border border-line bg-surface transition-opacity', waiting && 'opacity-60']" data-testid="preview-rows">
          <li v-for="row in earning" :key="row.member.id" class="flex min-h-11 items-center gap-2.5 px-3 py-1.5">
            <UserAvatar :name="row.member.name" :src="row.member.photo_url" :size="24" />
            <div class="min-w-0 flex-1">
              <p class="truncate text-sm font-medium text-fg">{{ row.member.name }}</p>
              <p class="truncate text-xs text-muted">{{ detail(row) }}</p>
            </div>
            <span class="shrink-0 whitespace-nowrap text-sm font-semibold tabular-nums">
              <PayAmount :value="row.amount === undefined ? undefined : signedAmount({ kind, amount: row.amount ?? '0' })" :currency="result.currency" :sign="kind === 'bonus' ? 'always' : 'auto'" colored />
            </span>
          </li>
        </ul>
        <button v-if="split.earning.length > LIMIT" type="button" class="self-start text-sm font-semibold text-accent-fg hover:underline" @click="expanded = !expanded">
          {{ expanded ? t("payroll.warnings.less") : t("payroll.warnings.more", { n: split.earning.length - LIMIT }, split.earning.length - LIMIT) }}
        </button>

        <!-- The people it looked at and gives nothing: folded, with their numbers. -->
        <div v-if="split.others.length" class="flex flex-col gap-1.5">
          <button type="button" class="inline-flex items-center gap-1 self-start text-sm font-medium text-muted hover:text-fg" :aria-expanded="showOthers" data-testid="preview-others" @click="showOthers = !showOthers">
            <ChevronDown :size="14" :class="['transition-transform', showOthers && 'rotate-180']" />{{ t("payroll.rules.previewOthers", { n: split.others.length }) }}
          </button>
          <ul v-if="showOthers" class="flex flex-col divide-y divide-line rounded-[10px] border border-line bg-surface">
            <li v-for="row in split.others" :key="row.member.id" class="flex min-h-10 items-center gap-2.5 px-3 py-1">
              <UserAvatar :name="row.member.name" :src="row.member.photo_url" :size="22" />
              <p class="min-w-0 flex-1 truncate text-sm text-fg">{{ row.member.name }}</p>
              <span class="shrink-0 text-xs tabular-nums text-muted">{{ valueText(row.value) }}</span>
            </li>
          </ul>
        </div>
      </template>
    </template>
  </section>
</template>
