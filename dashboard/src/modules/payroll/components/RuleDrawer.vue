<script setup lang="ts">
/**
 * The rule builder in a wide side panel synced with `?rule=<id|new>` (a bottom sheet on phones):
 * name and kind; what it measures (task, attendance and sales metrics) and the condition; how it
 * pays: once, per unit after the free ones, or in steps, a fixed amount or a percent, with a cap;
 * which positions; checked daily or monthly; approved automatically or proposed; on or off.
 * The live preview beside it runs the rule as it stands for a month.
 */
import { Gift, Plus, Scale, Trash2 } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import { isApiError } from "@/api/http";
import FormField from "@/components/FormField.vue";
import IconButton from "@/components/IconButton.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import MoneyInput from "@/components/MoneyInput.vue";
import NumberInput from "@/components/NumberInput.vue";
import PositionPicker from "@/components/PositionPicker.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SelectBox from "@/components/SelectBox.vue";
import TextInput from "@/components/TextInput.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import UiButton from "@/components/UiButton.vue";
import UiDrawer from "@/components/UiDrawer.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { closeQueryKey } from "@/lib/useRouteState";
import { useCompanyStore } from "@/stores/company";

import { payrollApi, useRefresh } from "../api";
import { adaptToMetric, allowsPerUnit, emptyRule, METRICS, metricArea, metricUnit, OP_SYMBOLS, percentBase, ruleInput, ruleProblems, ruleToDraft, usesMinTasks, type RuleDraft, type RuleProblem } from "../lib";
import type { Rule, RuleMetric } from "../types";
import RulePreview from "./RulePreview.vue";

const props = defineProps<{ rules: Rule[] }>();

const { t } = useI18n();
const route = useRoute();
const router = useRouter();
const company = useCompanyStore();
const confirm = useConfirm();
const refresh = useRefresh();

const param = computed(() => {
  const raw = route.query.rule;
  const value = Array.isArray(raw) ? raw[0] : raw;
  return value ?? null;
});
const ruleId = computed(() => (param.value && /^\d+$/.test(param.value) ? Number(param.value) : null));
const existing = computed(() => (ruleId.value ? (props.rules.find((rule) => rule.id === ruleId.value) ?? null) : null));
const kindParam = computed(() => (route.query.kind === "bonus" ? "bonus" : "fine"));

const draft = ref<RuleDraft>(emptyRule());
const touched = ref(false);
const saving = ref(false);
const serverErrors = ref<Record<string, string>>({});
/** A refusal that names no field ("Each tier needs its own threshold."), shown above the buttons. */
const formError = ref<string | null>(null);
watch(
  [param, existing],
  () => {
    if (!param.value) return;
    draft.value = existing.value ? ruleToDraft(existing.value) : emptyRule(kindParam.value);
    touched.value = false;
    serverErrors.value = {};
    formError.value = null;
  },
  { immediate: true },
);

const problems = computed(() => ruleProblems(draft.value));
const show = (problem: RuleProblem) => touched.value && problems.value.includes(problem);
const unit = computed(() => metricUnit(draft.value.metric));
const unitSuffix = computed(() => (unit.value === "percent" ? "%" : unit.value === "minutes" ? t("payroll.rules.unit.min") : unit.value === "hours" ? t("payroll.rules.unit.h") : unit.value === "money" ? t("payroll.currency.short") : undefined));

const metricOptions = computed(() =>
  METRICS.map((metric) => ({ value: metric, label: t(`payroll.metric.${metric}`), description: t(`payroll.metricHint.${metric}`), group: t(`payroll.metricArea.${metricArea(metric)}`) })),
);
function setMetric(metric: RuleMetric | null): void {
  if (metric) draft.value = adaptToMetric(draft.value, metric);
}
// "Per unit" makes no sense for a percentage or a ratio: it isn't offered then.
const modeOptions = computed(() =>
  (["once", "per_unit", "tiered"] as const).filter((value) => value !== "per_unit" || allowsPerUnit(draft.value.metric)).map((value) => ({ value, label: t(`payroll.rules.mode.${value}`) })),
);
const opOptions = computed(() => (["gte", "gt", "lte", "lt"] as const).map((value) => ({ value, label: t(`payroll.rules.op.${value}`) })));

function addTier(): void {
  draft.value.tiers.push({ threshold: null, amount: null });
}

async function save(): Promise<void> {
  touched.value = true;
  serverErrors.value = {};
  formError.value = null;
  if (problems.value.length || saving.value) return;
  saving.value = true;
  try {
    const input = ruleInput(draft.value);
    const saved = existing.value ? await payrollApi.updateRule(company.currentId ?? 0, existing.value.id, input, true) : await payrollApi.createRule(company.currentId ?? 0, input, true);
    toast.success(existing.value ? t("payroll.rules.saved") : t("payroll.rules.created"));
    refresh();
    if (!existing.value) void router.replace({ query: { ...route.query, rule: String(saved.id), kind: undefined } });
  } catch (error) {
    if (isApiError(error) && Object.keys(error.fieldErrors).length) {
      serverErrors.value = Object.fromEntries(Object.entries(error.fieldErrors).map(([field, messages]) => [field, messages[0] ?? ""]));
      // A field the form doesn't show (tiers, positions) still gets said.
      const shown = ["name", "metric", "threshold", "amount", "cap"];
      const other = Object.entries(serverErrors.value).find(([field]) => !shown.includes(field));
      if (other) formError.value = other[1];
    } else {
      formError.value = isApiError(error) ? (error.detail ?? t("common.error.generic")) : t("common.error.generic");
    }
  } finally {
    saving.value = false;
  }
}

async function remove(): Promise<void> {
  const rule = existing.value;
  if (!rule) return;
  const answer = await confirm({
    title: t("payroll.rules.deleteTitle", { name: rule.name }),
    message: t("payroll.rules.deleteBody"),
    confirmLabel: t("common.delete"),
    tone: "danger",
    icon: Trash2,
    onConfirm: () => payrollApi.deleteRule(company.currentId ?? 0, rule.id),
  });
  if (answer) {
    toast.success(t("payroll.rules.deleted"));
    refresh();
    closeQueryKey(router, "rule");
  }
}
const title = computed(() => (existing.value ? existing.value.name : t(`payroll.rules.newTitle.${draft.value.kind}`)));
</script>

<template>
  <UiDrawer query-key="rule" size="xl" :title="title">
    <template #default>
      <div class="grid gap-5 p-5 lg:grid-cols-[minmax(0,1fr)_300px]">
        <div class="flex min-w-0 flex-col gap-5">
          <div class="grid gap-4 sm:grid-cols-[1fr_auto]">
            <FormField :label="t('payroll.rules.name')" :error="show('name') ? t('payroll.rules.errName') : serverErrors.name" required>
              <TextInput v-model="draft.name" :maxlength="120" :placeholder="t(`payroll.rules.namePlaceholder.${draft.kind}`)" :invalid="show('name')" />
            </FormField>
            <FormField :label="t('payroll.rules.kind')">
              <SegmentedControl
                v-model="draft.kind"
                block
                :options="[
                  { value: 'bonus', label: t('payroll.adjustmentKind.bonus'), icon: Gift },
                  { value: 'fine', label: t('payroll.adjustmentKind.fine'), icon: Scale },
                ]"
              />
            </FormField>
          </div>

          <section class="flex flex-col gap-4 rounded-[12px] border border-line p-4">
            <h3 class="text-sm font-semibold text-fg">{{ t("payroll.rules.when") }}</h3>
            <FormField :label="t('payroll.rules.metric')" :error="serverErrors.metric">
              <SelectBox :model-value="draft.metric" :options="metricOptions" @update:model-value="setMetric" />
            </FormField>
            <p class="-mt-2 text-xs text-muted">{{ t(`payroll.metricHint.${draft.metric}`) }}</p>
            <!-- Tiers take the condition too: "≥" picks the highest tier reached, "≤" the lowest. -->
            <div class="grid gap-4 sm:grid-cols-2">
              <FormField :label="t('payroll.rules.condition')" :hint="draft.mode === 'tiered' ? t('payroll.rules.conditionTiers') : undefined" :class="draft.mode === 'tiered' && 'sm:col-span-2'">
                <SelectBox v-model="draft.op" :options="opOptions" :class="draft.mode === 'tiered' && 'sm:max-w-[calc(50%-0.5rem)]'" />
              </FormField>
              <!-- Per unit: a threshold only narrows who counts ("from the 3rd"); empty counts everyone. -->
              <FormField
                v-if="draft.mode !== 'tiered'"
                :label="t('payroll.rules.threshold')"
                :error="show('threshold') ? t('payroll.rules.errThreshold') : serverErrors.threshold"
                :required="draft.mode === 'once'"
                :optional="draft.mode === 'per_unit'"
              >
                <NumberInput v-model="draft.threshold" :min="0" :max="unit === 'percent' ? 100 : undefined" :decimals="unit === 'count' ? 0 : 2" :suffix="unitSuffix" :invalid="show('threshold')" />
              </FormField>
            </div>
            <div class="grid gap-4 sm:grid-cols-2">
              <FormField v-if="usesMinTasks(draft.metric)" :label="t('payroll.rules.minTasks')" :hint="t('payroll.rules.minTasksHint')">
                <NumberInput v-model="draft.min_tasks" :min="0" :max="500" />
              </FormField>
              <FormField :label="t('payroll.rules.evaluateLabel')" :hint="t(`payroll.rules.evaluateHint.${draft.evaluate}`)">
                <SegmentedControl
                  v-model="draft.evaluate"
                  block
                  :options="[
                    { value: 'monthly', label: t('payroll.rules.evaluate.monthly') },
                    { value: 'daily', label: t('payroll.rules.evaluate.daily') },
                  ]"
                />
              </FormField>
            </div>
          </section>

          <section class="flex flex-col gap-4 rounded-[12px] border border-line p-4">
            <h3 class="text-sm font-semibold text-fg">{{ draft.kind === "bonus" ? t("payroll.rules.howMuchBonus") : t("payroll.rules.howMuchFine") }}</h3>
            <div class="flex flex-col gap-1.5">
              <SegmentedControl v-model="draft.mode" block :options="modeOptions" :aria-label="t('payroll.rules.modeLabel')" />
              <p class="text-xs text-muted">{{ t(`payroll.rules.modeHint.${draft.mode}`) }}</p>
            </div>

            <template v-if="draft.mode === 'tiered'">
              <div class="flex flex-col gap-2" data-testid="tiers">
                <div v-for="(tier, index) in draft.tiers" :key="index" class="grid grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)_auto] items-end gap-2">
                  <FormField :label="index === 0 ? t('payroll.rules.tierFrom') : undefined">
                    <NumberInput v-model="tier.threshold" :min="0" :max="unit === 'percent' ? 100 : undefined" :decimals="unit === 'count' ? 0 : 2" :suffix="unitSuffix" :prefix="OP_SYMBOLS[draft.op]" />
                  </FormField>
                  <FormField :label="index === 0 ? t('payroll.rules.tierAmount') : undefined">
                    <MoneyInput v-model="tier.amount" :currencies="[company.currency]" />
                  </FormField>
                  <IconButton :icon="Trash2" :label="t('payroll.rules.removeTier')" class="mb-0.5" @click="draft.tiers.splice(index, 1)" />
                </div>
                <button type="button" class="inline-flex w-fit items-center gap-1 text-sm font-semibold text-accent-fg hover:underline" data-testid="add-tier" @click="addTier">
                  <Plus :size="14" />{{ t("payroll.rules.addTier") }}
                </button>
                <p v-if="show('tiers')" class="text-sm text-danger">{{ t("payroll.rules.errTiers") }}</p>
              </div>
            </template>
            <template v-else>
              <SegmentedControl
                v-if="draft.mode === 'once'"
                v-model="draft.amount_type"
                block
                size="sm"
                :options="[
                  { value: 'fixed', label: t('payroll.rules.fixed') },
                  { value: 'percent', label: percentBase(draft.metric) === 'sales' ? t('payroll.rules.percentSales') : t('payroll.rules.percentBase') },
                ]"
              />
              <div class="grid gap-4 sm:grid-cols-2">
                <FormField v-if="draft.mode === 'per_unit'" :label="t('payroll.rules.freeUnitsLabel')" :hint="t('payroll.rules.freeUnitsHint')">
                  <NumberInput v-model="draft.free_units" :min="0" :max="1000" />
                </FormField>
                <FormField
                  v-if="draft.amount_type === 'percent' && draft.mode === 'once'"
                  :label="t('payroll.rules.percent')"
                  :error="show('percent') ? t('payroll.rules.errPercent') : serverErrors.amount"
                  required
                >
                  <NumberInput v-model="draft.percent" :min="0" :max="100" :decimals="2" :step="0.5" suffix="%" :invalid="show('percent')" />
                </FormField>
                <FormField v-else :label="draft.mode === 'per_unit' ? t('payroll.rules.amountEach') : t('payroll.field.amount')" :error="show('amount') ? t('payroll.rules.errAmount') : serverErrors.amount" required>
                  <MoneyInput v-model="draft.amount" :currencies="[company.currency]" :invalid="show('amount')" />
                </FormField>
              </div>
            </template>
            <FormField v-if="draft.mode !== 'once' || draft.amount_type === 'percent'" :label="t('payroll.rules.cap')" optional :hint="t('payroll.rules.capHint')" :error="serverErrors.cap">
              <MoneyInput v-model="draft.cap" :currencies="[company.currency]" />
            </FormField>
          </section>

          <section class="flex flex-col gap-4 rounded-[12px] border border-line p-4">
            <h3 class="text-sm font-semibold text-fg">{{ t("payroll.rules.who") }}</h3>
            <FormField :label="t('payroll.rules.positions')" :hint="t('payroll.rules.positionsHint')">
              <PositionPicker v-model="draft.positions" multiple :placeholder="t('payroll.rules.everyone')" />
            </FormField>
            <div class="flex flex-col divide-y divide-line rounded-[10px] border border-line">
              <ToggleSwitch v-model="draft.auto_approve" layout="row" class="px-3.5 py-3" :label="t('payroll.rules.autoApprove')" :description="t('payroll.rules.autoApproveHint')" />
              <ToggleSwitch v-model="draft.is_active" layout="row" class="px-3.5 py-3" :label="t('payroll.rules.active')" :description="t('payroll.rules.activeHint')" />
            </div>
          </section>
        </div>
        <aside class="min-w-0 lg:sticky lg:top-0 lg:self-start">
          <RulePreview :draft="draft" :rule="existing" />
        </aside>
      </div>
    </template>
    <template #footer>
      <div class="flex w-full flex-col gap-2">
        <InlineAlert v-if="formError" tone="danger" size="sm" data-testid="rule-error">{{ formError }}</InlineAlert>
        <div class="flex w-full items-center gap-2">
          <UiButton v-if="existing" variant="ghost" size="sm" :icon="Trash2" class="text-danger" @click="remove">{{ t("common.delete") }}</UiButton>
          <span class="flex-1" />
          <UiButton variant="ghost" size="sm" @click="closeQueryKey(router, 'rule')">{{ t("common.close") }}</UiButton>
          <UiButton variant="primary" size="sm" :loading="saving" data-testid="save-rule" @click="save">{{ existing ? t("common.save") : t("payroll.rules.create") }}</UiButton>
        </div>
      </div>
    </template>
  </UiDrawer>
</template>
