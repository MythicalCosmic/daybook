<script setup lang="ts">
/**
 * A payslip's lines (plan §6.2: H's own `PayslipLines`): what was earned, what was taken off and
 * the rounding, each with the server's label and how it was worked out ("24 × 200 000 so‘m"),
 * then gross, deductions and net exactly as the server computed them. Manual lines on a draft
 * can be removed here (the drawer adds them).
 */
import { Minus, Plus, Trash2 } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import type { Currency, Money } from "@/api/types";
import IconButton from "@/components/IconButton.vue";
import MoneyText from "@/components/MoneyText.vue";
import { useFormat } from "@/lib/useFormat";

import { isManualLine, lineGroups, lineHow, lineNote, quantityText } from "../lib";
import type { PayslipLine } from "../types";
import PayAmount from "./PayAmount.vue";

const props = withDefaults(
  defineProps<{
    lines: PayslipLine[];
    currency: Currency;
    gross?: Money | null;
    deductions?: Money | null;
    net?: Money | null;
    /** Manual lines may be removed (the run is a draft and the viewer manages payroll). */
    editable?: boolean;
    removing?: number | null;
  }>(),
  { gross: undefined, deductions: undefined, net: undefined, editable: false, removing: null },
);
const emit = defineEmits<{ remove: [line: PayslipLine] }>();

const { t, te } = useI18n();
const fmt = useFormat();
const groups = computed(() => lineGroups(props.lines));
// Rounding belongs with the totals (between what is taken and the net), not as its own section.
const sections = computed(() =>
  [
    { id: "earnings", title: t("payroll.lines.earned"), icon: Plus, tone: "text-success", lines: groups.value.earnings },
    { id: "deductions", title: t("payroll.lines.takenOff"), icon: Minus, tone: "text-danger", lines: groups.value.deductions },
  ].filter((section) => section.lines.length),
);

function how(line: PayslipLine): string | null {
  const parts = lineHow(line);
  if (!parts) return null;
  return `${quantityText(parts.quantity, fmt.lang.value)} × ${fmt.money(parts.rate, props.currency)}`;
}

const kindLabel = (line: PayslipLine) => (te(`payroll.lineKind.${line.kind}`) ? t(`payroll.lineKind.${line.kind}`) : null);
/** Where a final payslip's leave payout and in-full advance come from. */
function note(line: PayslipLine): string | null {
  const found = lineNote(line);
  return found ? t(found.key, found.values) : null;
}
</script>

<template>
  <div class="flex flex-col gap-4" data-testid="payslip-lines">
    <p v-if="!lines.length" class="rounded-[10px] bg-surface-2 px-3 py-3 text-sm text-muted">{{ t("payroll.lines.none") }}</p>
    <section v-for="section in sections" :key="section.id" class="flex flex-col gap-1.5">
      <h3 class="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-[0.04em] text-muted">
        <component :is="section.icon" v-if="section.icon" :size="13" :class="section.tone" aria-hidden="true" />{{ section.title }}
      </h3>
      <ul class="flex flex-col divide-y divide-line rounded-[12px] border border-line">
        <li v-for="line in section.lines" :key="line.id" class="flex min-h-12 items-start gap-3 px-3 py-2.5" :data-line-kind="line.kind">
          <div class="min-w-0 flex-1">
            <p class="text-sm font-medium leading-5 text-fg">{{ line.label || kindLabel(line) }}</p>
            <p v-if="how(line)" class="mt-0.5 text-xs leading-4 tabular-nums text-muted">{{ how(line) }}</p>
            <p v-if="note(line)" class="mt-0.5 text-xs leading-4 text-muted" data-testid="line-note">{{ note(line) }}</p>
          </div>
          <span class="shrink-0 pt-px text-sm font-semibold tabular-nums"><MoneyText :value="line.amount" :currency="currency" colored /></span>
          <IconButton
            v-if="editable && isManualLine(line)"
            :icon="Trash2"
            size="sm"
            :label="t('payroll.lines.remove', { label: line.label })"
            :loading="removing === line.id"
            class="-my-1 -mr-1.5"
            @click="emit('remove', line)"
          />
        </li>
      </ul>
    </section>

    <dl v-if="net !== undefined" class="flex flex-col gap-1.5 rounded-[12px] bg-surface-2 px-3 py-3 text-sm">
      <div class="flex items-baseline justify-between gap-4">
        <dt class="text-muted">{{ t("payroll.totals.gross") }}</dt>
        <dd class="font-medium tabular-nums text-fg"><PayAmount :value="gross" :currency="currency" /></dd>
      </div>
      <div class="flex items-baseline justify-between gap-4">
        <dt class="text-muted">{{ t("payroll.totals.deductions") }}</dt>
        <dd class="font-medium tabular-nums text-fg"><PayAmount :value="deductions" :currency="currency" /></dd>
      </div>
      <div v-for="line in groups.other" :key="line.id" class="flex items-baseline justify-between gap-4" :data-line-kind="line.kind">
        <dt class="text-muted">{{ line.label || kindLabel(line) }}</dt>
        <dd class="font-medium tabular-nums text-fg"><MoneyText :value="line.amount" :currency="currency" /></dd>
      </div>
      <div class="mt-0.5 flex items-baseline justify-between gap-4 border-t border-line pt-2">
        <dt class="text-base font-semibold text-fg">{{ t("payroll.totals.net") }}</dt>
        <dd class="text-base font-semibold tabular-nums text-fg" data-testid="payslip-net"><PayAmount :value="net" :currency="currency" /></dd>
      </div>
    </dl>
  </div>
</template>
