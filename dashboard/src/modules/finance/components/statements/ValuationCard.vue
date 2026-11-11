<script setup lang="ts">
/**
 * What the business is worth (v12, `valuation/`): two transparent methods side by side on one
 * scale and the range they span, never one magic number. Earnings: the last twelve months' profit
 * before depreciation, loan interest and equipment booked as a cost, times a multiple range the
 * owner may change, plus the cash, less the loans. Net assets: the balance sheet's book value.
 * An estimate from the books, not an appraisal. Hidden for someone who doesn't see every branch.
 */
import { ChevronDown, Settings2 } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import FormField from "@/components/FormField.vue";
import MoneyText from "@/components/MoneyText.vue";
import NumberInput from "@/components/NumberInput.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import UiButton from "@/components/UiButton.vue";
import { toast } from "@/components/useToast";
import { useFormat } from "@/lib/useFormat";

import { useSetMultiples, useValuation } from "../../statements";

const { t } = useI18n();
const fmt = useFormat();
const query = useValuation();
const data = computed(() => query.data.value ?? null);
const method = computed(() => data.value?.earnings_method ?? null);
const showHow = ref(false);
const editing = ref(false);
const low = ref<number | null>(null);
const high = ref<number | null>(null);
watch(
  data,
  (value) => {
    if (!value || editing.value) return;
    low.value = Number(value.multiple_low);
    high.value = Number(value.multiple_high);
  },
  { immediate: true },
);

const single = computed(() => !!data.value && data.value.range.low === data.value.range.high);
/** Bars on one scale from zero to the largest value. */
const scale = computed(() => {
  const d = data.value;
  if (!d) return 1;
  const values = [Number(d.net_assets.value), Number(d.earnings_method.high ?? 0), Number(d.earnings_method.low ?? 0)].map(Math.abs);
  return Math.max(...values, 1);
});
const pct = (value: string | null) => `${Math.max(0, Math.min(100, (Number(value ?? 0) / scale.value) * 100)).toFixed(1)}%`;
const rangeWidth = computed(() => {
  const m = method.value;
  if (!m?.applies) return "0%";
  const width = ((Number(m.high) - Number(m.low)) / scale.value) * 100;
  return `${Math.max(width, 1).toFixed(1)}%`;
});
const multiples = computed(() => (data.value ? t("finance.worth.multiples", { low: fmt.number(Number(data.value.multiple_low), 1), high: fmt.number(Number(data.value.multiple_high), 1) }) : ""));
const isDefault = computed(() => !!data.value && data.value.multiple_low === data.value.default_low && data.value.multiple_high === data.value.default_high);
const reason = computed(() => {
  const m = method.value;
  if (!m || m.applies || !data.value) return "";
  return m.reason === "too_early" ? t("finance.worth.tooEarly", { n: data.value.earnings.days }, data.value.earnings.days) : t("finance.worth.loss");
});
const lines = computed(() => (data.value?.earnings.lines ?? []).filter((line) => line.key === "profit" || Number(line.amount) !== 0));

const save = useSetMultiples();
async function apply(reset = false): Promise<void> {
  const body = reset
    ? { multiple_low: null, multiple_high: null }
    : { multiple_low: low.value === null ? null : low.value.toFixed(1), multiple_high: high.value === null ? null : high.value.toFixed(1) };
  await save.mutateAsync(body);
  editing.value = false;
  toast.success(t("finance.worth.saved"));
}
</script>

<template>
  <section v-if="query.isPending.value || data" class="ui-card p-4" data-valuation>
    <header class="mb-3 flex items-start justify-between gap-3">
      <div class="min-w-0">
        <h3 class="text-sm font-semibold text-fg">{{ t("finance.worth.title") }}</h3>
        <p class="text-xs text-muted">{{ t("finance.worth.subtitle") }}</p>
      </div>
      <UiButton v-if="data?.editable" variant="ghost" size="sm" :icon="Settings2" data-edit @click="editing = !editing">{{ t("finance.worth.change") }}</UiButton>
    </header>
    <SkeletonBlock v-if="query.isPending.value" height="180px" />
    <template v-else-if="data && method">
      <p class="text-xl font-semibold tabular-nums text-fg" data-range>
        <MoneyText :value="data.range.low" compact />
        <template v-if="!single"> – <MoneyText :value="data.range.high" compact /></template>
      </p>
      <p class="mb-4 text-xs text-muted">{{ single ? t("finance.worth.onlyNetAssets") : t("finance.worth.rangeHint") }}</p>

      <div class="mb-4 flex flex-col gap-2.5" aria-hidden="true">
        <div class="grid grid-cols-[96px_minmax(0,1fr)] items-center gap-3">
          <span class="text-xs font-medium text-muted">{{ t("finance.worth.earnings") }}</span>
          <div class="relative h-5 rounded-[4px] bg-surface-2">
            <div v-if="method.applies" class="absolute inset-y-1 rounded-[3px] bg-primary" :style="{ left: pct(method.low), width: rangeWidth }" data-earnings-bar />
            <span v-else class="absolute inset-0 flex items-center px-2 text-xs text-subtle">{{ t("finance.worth.notApplies") }}</span>
          </div>
        </div>
        <div class="grid grid-cols-[96px_minmax(0,1fr)] items-center gap-3">
          <span class="text-xs font-medium text-muted">{{ t("finance.worth.netAssets") }}</span>
          <div class="relative h-5 rounded-[4px] bg-surface-2">
            <div class="absolute inset-y-0 w-1.5 -translate-x-1/2 rounded-full bg-fg" :style="{ left: pct(data.net_assets.value) }" />
          </div>
        </div>
      </div>

      <dl class="grid grid-cols-1 gap-3 text-sm sm:grid-cols-2">
        <div class="rounded-[10px] border border-line p-3">
          <dt class="text-xs font-medium text-muted">{{ t("finance.worth.byEarnings") }}</dt>
          <dd v-if="method.applies" class="mt-0.5 font-semibold tabular-nums text-fg"><MoneyText :value="method.low" compact /> – <MoneyText :value="method.high" compact /></dd>
          <dd v-else class="mt-0.5 text-muted">{{ reason }}</dd>
          <dd class="mt-1 text-xs text-muted">{{ multiples }}<template v-if="isDefault"> · {{ t("finance.worth.default") }}</template></dd>
        </div>
        <div class="rounded-[10px] border border-line p-3">
          <dt class="text-xs font-medium text-muted">{{ t("finance.worth.byNetAssets") }}</dt>
          <dd class="mt-0.5 font-semibold tabular-nums text-fg"><MoneyText :value="data.net_assets.value" compact /></dd>
          <dd class="mt-1 text-xs text-muted">{{ t("finance.worth.netAssetsHint") }}</dd>
        </div>
      </dl>

      <button type="button" class="mt-3 flex items-center gap-1 text-xs font-medium text-muted hover:text-fg" :aria-expanded="showHow" data-how @click="showHow = !showHow">
        <ChevronDown :size="14" :class="['transition-transform', showHow ? 'rotate-180' : '']" aria-hidden="true" />{{ t("finance.worth.how") }}
      </button>
      <div v-if="showHow" class="mt-2 rounded-[10px] bg-surface-2 p-3 text-sm" data-how-body>
        <ul class="flex flex-col gap-1">
          <li v-for="line in lines" :key="line.key" class="flex justify-between gap-3">
            <span class="text-muted">{{ t(`finance.worth.line.${line.key}`) }}</span>
            <span class="tabular-nums text-fg"><MoneyText :value="line.amount" decimals="never" /></span>
          </li>
          <li class="flex justify-between gap-3 border-t border-line pt-1 font-medium">
            <span class="text-fg">{{ t("finance.worth.earningsDays", { n: data.earnings.days }, data.earnings.days) }}</span>
            <span class="tabular-nums text-fg"><MoneyText :value="data.earnings.earnings" decimals="never" /></span>
          </li>
          <li v-if="data.earnings.yearly && data.earnings.days < 365" class="flex justify-between gap-3">
            <span class="text-muted">{{ t("finance.worth.yearly") }}</span>
            <span class="tabular-nums text-fg"><MoneyText :value="data.earnings.yearly" decimals="never" /></span>
          </li>
          <template v-if="method.applies">
            <li class="flex justify-between gap-3">
              <span class="text-muted">{{ t("finance.worth.business", { multiples }) }}</span>
              <span class="tabular-nums text-fg"><MoneyText :value="method.business_low" compact /> – <MoneyText :value="method.business_high" compact /></span>
            </li>
            <li class="flex justify-between gap-3">
              <span class="text-muted">{{ t("finance.worth.plusCash") }}</span>
              <span class="tabular-nums text-fg"><MoneyText :value="method.cash" compact /></span>
            </li>
            <li class="flex justify-between gap-3">
              <span class="text-muted">{{ t("finance.worth.lessDebt") }}</span>
              <span class="tabular-nums text-fg">−<MoneyText :value="method.debt" compact /></span>
            </li>
          </template>
        </ul>
        <p class="mt-2 text-xs text-muted">{{ t("finance.worth.caveat") }}</p>
      </div>

      <div v-if="editing && data.editable" class="mt-3 flex flex-col gap-3 rounded-[10px] border border-line p-3" data-multiples>
        <p class="text-xs text-muted">{{ t("finance.worth.multiplesHint") }}</p>
        <div class="grid grid-cols-2 gap-3">
          <FormField :label="t('finance.worth.low')"><NumberInput v-model="low" :min="0.5" :max="20" :step="0.5" :decimals="1" suffix="×" /></FormField>
          <FormField :label="t('finance.worth.high')"><NumberInput v-model="high" :min="0.5" :max="20" :step="0.5" :decimals="1" suffix="×" /></FormField>
        </div>
        <div class="flex flex-wrap justify-end gap-2">
          <UiButton v-if="!isDefault" variant="ghost" size="sm" :loading="save.isPending.value" @click="apply(true)">{{ t("finance.worth.reset") }}</UiButton>
          <UiButton variant="primary" size="sm" :loading="save.isPending.value" data-save @click="apply()">{{ t("common.save") }}</UiButton>
        </div>
      </div>
    </template>
  </section>
</template>
