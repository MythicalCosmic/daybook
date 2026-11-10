<script setup lang="ts">
/**
 * Prepare a dividend round (or change a draft one): the period (last quarter by default), the
 * amount the server suggests (the period's net profit less rounds already made for it, at most
 * what is safe to take out today) and how it splits by the partners' shares on the period's last
 * day, live as the amount changes.
 */
import { Sparkles } from "@lucide/vue";
import { computed, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { isApiError } from "@/api/http";
import DatePicker from "@/components/DatePicker.vue";
import FormField from "@/components/FormField.vue";
import MoneyInput from "@/components/MoneyInput.vue";
import MoneyText from "@/components/MoneyText.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import TextInput from "@/components/TextInput.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { lastQuarter, ownerMoneyApi, splitByShares, useDividendSuggestion, useOwnerMoneyWrite, type Dividend } from "../../ownerMoney";

const open = defineModel<boolean>("open", { default: false });
const props = defineProps<{ today: string; dividend?: Dividend | null }>();

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
type Preset = "quarter" | "year" | "lastYear" | "custom";
const preset = ref<Preset>("quarter");
const form = reactive({ from: null as string | null, to: null as string | null, amount: null as string | null, note: "" });
const error = ref<string | null>(null);
const editing = computed(() => !!props.dividend);
const touched = ref(false);

function presetRange(value: Preset): { from: string; to: string } | null {
  const year = Number(props.today.slice(0, 4));
  if (value === "quarter") return lastQuarter(props.today);
  if (value === "year") return { from: `${year}-01-01`, to: props.today };
  if (value === "lastYear") return { from: `${year - 1}-01-01`, to: `${year - 1}-12-31` };
  return form.from && form.to ? { from: form.from, to: form.to } : null;
}

watch(
  open,
  (isOpen) => {
    if (!isOpen) return;
    error.value = null;
    touched.value = false;
    if (props.dividend) {
      Object.assign(form, { from: props.dividend.period_start, to: props.dividend.period_end, amount: props.dividend.amount, note: props.dividend.note });
      preset.value = "custom";
      return;
    }
    preset.value = "quarter";
    const range = lastQuarter(props.today);
    Object.assign(form, { from: range.from, to: range.to, amount: null, note: "" });
  },
  { immediate: true },
);
watch(preset, (value) => {
  if (value === "custom" || editing.value) return;
  const range = presetRange(value);
  if (range) Object.assign(form, range);
  touched.value = false;
});

const range = computed(() => (form.from && form.to && form.from <= form.to ? { from: form.from, to: form.to } : null));
const suggestion = useDividendSuggestion(range, () => open.value);
watch(
  () => suggestion.data.value,
  (data) => {
    if (data && !touched.value && !editing.value) form.amount = Number(data.amount) > 0 ? data.amount : null;
  },
);
const split = computed(() => {
  const data = suggestion.data.value;
  if (!data || !form.amount) return [];
  const parts = splitByShares(Number(form.amount), data.split.map((row) => Number(row.share)));
  return data.split.map((row, index) => ({ ...row, part: parts[index] ?? 0 }));
});

const create = useOwnerMoneyWrite(ownerMoneyApi.createDividend);
const update = useOwnerMoneyWrite((cid: number, input: { id: number; amount: string; note: string }) => ownerMoneyApi.updateDividend(cid, input.id, { amount: input.amount, note: input.note }));
const saving = computed(() => create.isPending.value || update.isPending.value);

async function save(): Promise<void> {
  error.value = null;
  if (!range.value) {
    error.value = t("finance.dividends.pickPeriod");
    return;
  }
  if (!form.amount || Number(form.amount) <= 0) {
    error.value = t("finance.quick.errAmount");
    return;
  }
  try {
    if (props.dividend) await update.mutateAsync({ id: props.dividend.id, amount: form.amount, note: form.note });
    else await create.mutateAsync({ period_start: range.value.from, period_end: range.value.to, amount: form.amount, note: form.note });
    toast.success(editing.value ? t("finance.dividends.updated") : t("finance.dividends.created"));
    open.value = false;
  } catch (failure) {
    if (!isApiError(failure)) throw failure;
    error.value = failure.detail ?? Object.values(failure.fieldErrors)[0]?.[0] ?? t("finance.myMoney.failed");
  }
}
</script>

<template>
  <UiDialog v-model:open="open" :title="editing ? t('finance.dividends.editTitle') : t('finance.dividends.newTitle')" :description="t('finance.dividends.dialogDescription')" size="lg">
    <div class="flex flex-col gap-4">
      <FormField v-if="!editing" :label="t('finance.dividends.period')">
        <SegmentedControl
          v-model="preset"
          block
          :options="[
            { value: 'quarter', label: t('finance.dividends.lastQuarter') },
            { value: 'year', label: t('finance.dividends.thisYear') },
            { value: 'lastYear', label: t('finance.dividends.lastYear') },
            { value: 'custom', label: t('finance.dividends.custom') },
          ]"
        />
      </FormField>
      <div v-if="preset === 'custom' && !editing" class="grid gap-3 sm:grid-cols-2">
        <FormField :label="t('finance.dividends.from')"><DatePicker v-model="form.from" :max="today" /></FormField>
        <FormField :label="t('finance.dividends.to')"><DatePicker v-model="form.to" :min="form.from" /></FormField>
      </div>
      <p v-else-if="range" class="text-sm text-muted" data-period>{{ fmt.day(range.from, "medium") }} – {{ fmt.day(range.to, "medium") }}</p>

      <div class="rounded-[12px] border border-line bg-surface-2/50 p-3 dark:bg-surface-3/30" data-suggestion>
        <p class="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-subtle"><Sparkles :size="13" aria-hidden="true" />{{ t("finance.dividends.suggestionTitle") }}</p>
        <div v-if="suggestion.isPending.value && range" class="grid grid-cols-3 gap-3"><SkeletonBlock v-for="n in 3" :key="n" height="40px" /></div>
        <dl v-else-if="suggestion.data.value" class="grid grid-cols-3 gap-3">
          <div>
            <dt class="text-xs text-muted">{{ t("finance.dividends.profit") }}</dt>
            <dd class="text-sm font-semibold tabular-nums" :class="Number(suggestion.data.value.profit) < 0 ? 'text-danger' : 'text-fg'"><MoneyText :value="suggestion.data.value.profit" compact /></dd>
          </div>
          <div>
            <dt class="text-xs text-muted">{{ t("finance.dividends.safeNow") }}</dt>
            <dd class="text-sm font-semibold tabular-nums text-fg"><MoneyText :value="suggestion.data.value.safe" compact /></dd>
          </div>
          <div>
            <dt class="text-xs text-muted">{{ t("finance.dividends.suggested") }}</dt>
            <dd class="text-sm font-semibold tabular-nums text-success"><MoneyText :value="suggestion.data.value.amount" compact /></dd>
          </div>
        </dl>
        <p v-if="suggestion.data.value" class="mt-2 text-xs text-muted">
          {{ suggestion.data.value.limited_by === "safe" ? t("finance.dividends.limitedBySafe") : t("finance.dividends.limitedByProfit") }}
          <template v-if="Number(suggestion.data.value.already) > 0"> {{ t("finance.dividends.already", { amount: fmt.money(suggestion.data.value.already, undefined, { compact: true }) }) }}</template>
        </p>
      </div>

      <FormField :label="t('finance.dividends.amount')" required>
        <MoneyInput v-model="form.amount" :currencies="[company.currency]" data-amount @update:model-value="touched = true" />
      </FormField>

      <div v-if="split.length" class="rounded-[12px] border border-line" data-split>
        <p class="border-b border-line px-3 py-2 text-xs font-semibold text-muted">{{ t("finance.dividends.splitTitle") }}</p>
        <ul class="divide-y divide-line">
          <li v-for="row in split" :key="row.partner_id" class="flex items-center gap-3 px-3 py-2 text-sm">
            <span class="min-w-0 flex-1 truncate font-medium text-fg">{{ row.name }}</span>
            <span class="text-xs tabular-nums text-muted">{{ fmt.number(row.share, 2) }}%</span>
            <span class="w-32 text-right font-semibold tabular-nums text-fg"><MoneyText :value="row.part" /></span>
          </li>
        </ul>
      </div>
      <p v-else-if="suggestion.data.value && !suggestion.data.value.split.length" class="text-sm text-warning">{{ t("finance.dividends.noPartners") }}</p>

      <FormField :label="t('finance.myMoney.note')" optional>
        <TextInput v-model="form.note" :maxlength="300" :placeholder="t('finance.dividends.notePlaceholder')" />
      </FormField>
      <p v-if="error" class="rounded-[8px] bg-danger-soft px-3 py-2 text-sm text-danger" role="alert">{{ error }}</p>
    </div>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="primary" :loading="saving" data-save @click="save">{{ editing ? t("common.save") : t("finance.dividends.create") }}</UiButton>
    </template>
  </UiDialog>
</template>
