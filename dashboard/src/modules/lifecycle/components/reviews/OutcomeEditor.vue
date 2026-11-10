<script setup lang="ts">
/**
 * What follows from a review, as its reviewer picks it: nothing, a raise (a percentage from a
 * day, with the pay now and after for payroll.view), a bonus (an amount on a month's payslip), a
 * promotion (a position from a day, with a raise if any) or an improvement plan (one to three
 * goals with their days). A raise and a bonus need someone who may propose pay; everything waits
 * for the usual approval once published.
 */
import { ArrowRight, Award, Banknote, Gift, Minus, Plus, Target, Trash2, TrendingUp } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import DatePicker from "@/components/DatePicker.vue";
import FormField from "@/components/FormField.vue";
import IconButton from "@/components/IconButton.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import MoneyInput from "@/components/MoneyInput.vue";
import MoneyText from "@/components/MoneyText.vue";
import NumberInput from "@/components/NumberInput.vue";
import PositionPicker from "@/components/PositionPicker.vue";
import RadioCards, { type RadioCardOption } from "@/components/RadioCards.vue";
import TextInput from "@/components/TextInput.vue";
import UiButton from "@/components/UiButton.vue";
import { useCompanyStore } from "@/stores/company";

import { MAX_GOALS, nextFirst, payAfter, type ManagerForm } from "../../reviews/lib";
import { OUTCOMES, type Outcome, type Review } from "../../reviews/types";

const form = defineModel<ManagerForm>({ required: true });
const props = defineProps<{ review: Review; today: string }>();
const emit = defineEmits<{ change: [] }>();

const { t } = useI18n();
const company = useCompanyStore();

const ICONS: Record<Outcome, typeof Minus> = { none: Minus, raise: TrendingUp, bonus: Gift, promotion: Award, improvement_plan: Target };
const payBlocked = computed(() => !props.review.can.pay);
const options = computed<RadioCardOption<Outcome>[]>(() =>
  OUTCOMES.map((value) => ({
    value,
    label: t(`lifecycle.reviews.outcome.${value}`),
    description: t(`lifecycle.reviews.outcomeHint.${value}`),
    icon: ICONS[value],
    disabled: payBlocked.value && (value === "raise" || value === "bonus"),
  })),
);
const outcome = computed<Outcome | null>({
  get: () => form.value.outcome,
  set: (value) => {
    const next = value ?? "none";
    form.value.outcome = next;
    if ((next === "raise" || next === "promotion" || next === "bonus") && !form.value.effective_on) {
      form.value.effective_on = next === "bonus" ? props.today.slice(0, 8) + "01" : nextFirst(props.today);
    }
    if (next === "improvement_plan" && !form.value.goals.length) addGoal();
    emit("change");
  },
});

const percent = computed<number | null>({
  get: () => (form.value.raise_percent ? Number(form.value.raise_percent) : null),
  set: (value) => {
    form.value.raise_percent = value === null ? null : String(value);
    emit("change");
  },
});
const pay = computed(() => props.review.pay);
const after = computed(() => (pay.value ? payAfter(pay.value.amount, form.value.raise_percent, pay.value.rounding_step) : null));
const showsRaise = computed(() => form.value.outcome === "raise" || form.value.outcome === "promotion");

function addGoal(): void {
  if (form.value.goals.length >= MAX_GOALS) return;
  form.value.goals = [...form.value.goals, { title: "", due_on: addMonthsEnd(), target: null, unit: "" }];
  emit("change");
}
function removeGoal(index: number): void {
  form.value.goals = form.value.goals.filter((_, i) => i !== index);
  emit("change");
}
/** A plan's goal is due about three months on by default. */
function addMonthsEnd(): string {
  const [year, month] = props.today.split("-").map(Number) as [number, number];
  const target = new Date(Date.UTC(year, month + 2, 0));
  return target.toISOString().slice(0, 10);
}
const touched = () => emit("change");
</script>

<template>
  <div class="flex flex-col gap-4" data-outcome>
    <RadioCards v-model="outcome" :options="options" :columns="1" />
    <InlineAlert v-if="payBlocked" tone="neutral" size="sm" :description="t('lifecycle.reviews.outcomePayLocked')" />

    <div v-if="form.outcome !== 'none'" class="flex flex-col gap-3 rounded-[14px] border border-line bg-surface-2/40 p-4 dark:bg-surface-3/30">
      <template v-if="form.outcome === 'promotion'">
        <FormField :label="t('lifecycle.reviews.promoteTo')" required>
          <PositionPicker v-model="form.promotion_position" :clearable="false" @update:model-value="touched" />
        </FormField>
      </template>

      <div v-if="showsRaise" class="grid gap-3 sm:grid-cols-2">
        <FormField :label="form.outcome === 'promotion' ? t('lifecycle.reviews.raiseWith') : t('lifecycle.reviews.raisePercent')" :required="form.outcome === 'raise'" :optional="form.outcome === 'promotion'">
          <NumberInput v-model="percent" :min="0.5" :max="50" :step="0.5" :decimals="2" suffix="%" :disabled="payBlocked" />
        </FormField>
        <FormField :label="t('lifecycle.reviews.from')" required>
          <DatePicker v-model="form.effective_on" :min="today" format="medium" @update:model-value="touched" />
        </FormField>
      </div>

      <div v-if="showsRaise && pay && after" class="flex flex-wrap items-center gap-2 rounded-[12px] bg-surface px-3 py-2.5 text-sm" data-pay-after>
        <Banknote :size="16" class="text-muted" aria-hidden="true" />
        <span class="text-muted">{{ t("lifecycle.reviews.payNow") }}</span>
        <MoneyText class="font-medium tabular-nums text-fg" :value="pay.amount" :currency="pay.currency" />
        <ArrowRight :size="14" class="text-subtle" aria-hidden="true" />
        <MoneyText class="font-semibold tabular-nums text-success" :value="after" :currency="pay.currency" />
        <span class="text-xs text-muted">{{ t(`lifecycle.payType.${pay.pay_type}`) }}</span>
      </div>
      <p v-else-if="showsRaise && !pay && percent" class="text-xs text-muted">{{ t("lifecycle.reviews.payHidden") }}</p>

      <div v-if="form.outcome === 'bonus'" class="grid gap-3 sm:grid-cols-2">
        <FormField :label="t('lifecycle.reviews.bonusAmount')" required>
          <MoneyInput v-model="form.bonus_amount" :currencies="[review.bonus_currency ?? company.currency]" @update:model-value="touched" />
        </FormField>
        <FormField :label="t('lifecycle.reviews.bonusMonth')" :hint="t('lifecycle.reviews.bonusMonthHint')">
          <DatePicker v-model="form.effective_on" :min="today.slice(0, 8) + '01'" format="medium" @update:model-value="touched" />
        </FormField>
      </div>

      <template v-if="form.outcome === 'improvement_plan'">
        <p class="text-sm text-muted">{{ t("lifecycle.reviews.planHint") }}</p>
        <ol class="flex flex-col gap-2.5" data-goals>
          <li v-for="(goal, index) in form.goals" :key="index" class="rounded-[12px] border border-line bg-surface p-3">
            <div class="flex items-start gap-2">
              <span class="mt-2 grid size-6 shrink-0 place-items-center rounded-full bg-warning-soft text-xs font-semibold text-warning">{{ index + 1 }}</span>
              <div class="grid min-w-0 flex-1 gap-2">
                <TextInput v-model="goal.title" :maxlength="200" :placeholder="t('lifecycle.reviews.goalPlaceholder')" :aria-label="t('lifecycle.reviews.goalTitle')" @update:model-value="touched" />
                <div class="grid gap-2 sm:grid-cols-[1fr_7rem_6rem]">
                  <DatePicker v-model="goal.due_on" :min="today" format="medium" :aria-label="t('lifecycle.reviews.goalDue')" @update:model-value="touched" />
                  <TextInput v-model="goal.target" inputmode="decimal" :placeholder="t('lifecycle.reviews.goalTarget')" :aria-label="t('lifecycle.reviews.goalTarget')" @update:model-value="touched" />
                  <TextInput v-model="goal.unit" :maxlength="30" :placeholder="t('lifecycle.reviews.goalUnit')" :aria-label="t('lifecycle.reviews.goalUnit')" @update:model-value="touched" />
                </div>
              </div>
              <IconButton :icon="Trash2" size="sm" :label="t('lifecycle.reviews.goalRemove')" @click="removeGoal(index)" />
            </div>
          </li>
        </ol>
        <UiButton v-if="form.goals.length < MAX_GOALS" size="sm" variant="ghost" :icon="Plus" class="self-start" @click="addGoal">{{ t("lifecycle.reviews.goalAdd") }}</UiButton>
      </template>

      <p class="text-xs text-muted">{{ t(`lifecycle.reviews.approvalNote.${form.outcome}`) }}</p>
    </div>
  </div>
</template>
