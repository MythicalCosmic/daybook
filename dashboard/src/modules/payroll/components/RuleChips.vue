<script setup lang="ts">
/**
 * A rule at a glance, as chips rather than a sentence (three languages, no grammar to bend):
 * what it measures and the condition, what it pays or takes (a fixed amount, a share, per unit
 * after the free ones, or steps), the cap, how often it is checked and for whom.
 */
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import { compare } from "@/lib/decimal";
import { useFormat } from "@/lib/useFormat";

import { hasAmount, metricUnit, OP_SYMBOLS } from "../lib";
import type { Rule } from "../types";

const props = defineProps<{ rule: Pick<Rule, "kind" | "metric" | "mode" | "op" | "threshold" | "free_units" | "tiers" | "amount_type" | "amount" | "cap" | "min_tasks" | "positions" | "evaluate" | "auto_approve"> }>();

const { t } = useI18n();
const fmt = useFormat();

const unitText = (value: string | number) => {
  const unit = metricUnit(props.rule.metric);
  if (unit === "percent") return fmt.percent(Number(value), 1);
  if (unit === "money") return fmt.money(String(value));
  if (unit === "minutes") return t("payroll.rules.unit.minutes", { n: fmt.number(value, 1) });
  if (unit === "hours") return t("payroll.rules.unit.hours", { n: fmt.number(value, 1) });
  return fmt.number(value, 2);
};
const sign = computed(() => (props.rule.kind === "bonus" ? "+" : "−"));

const chips = computed(() => {
  const r = props.rule;
  const list: Array<{ key: string; text: string; tone?: "kind" | "muted" }> = [];
  list.push({ key: "metric", text: t(`payroll.metric.${r.metric}`) });
  // Amounts hidden: the server leaves out the amount, the cap and the tiers; the chip says so.
  const hidden = !("amount" in r) && !("tiers" in r);
  const money = (value: string | null | undefined) => (hasAmount(value) ? `${sign.value}${fmt.money(value)}` : t("payroll.hidden"));
  if (r.mode === "tiered") {
    for (const tier of [...(r.tiers ?? [])].sort((a, b) => compare(a.threshold, b.threshold))) {
      list.push({ key: `tier-${tier.threshold}`, text: `${OP_SYMBOLS[r.op]} ${unitText(tier.threshold)}: ${money(tier.amount)}`, tone: "kind" });
    }
    if (hidden) list.push({ key: "hidden", text: t("payroll.hidden"), tone: "muted" });
  } else {
    // "≥ 0" holds for everyone: no condition worth a chip.
    const always = r.op === "gte" && r.threshold !== null && compare(r.threshold, "0") <= 0;
    if (r.threshold !== null && r.mode === "once" && !always) list.push({ key: "when", text: `${OP_SYMBOLS[r.op]} ${unitText(r.threshold)}` });
    const free = Number(r.free_units) || 0;
    if (r.mode === "per_unit") {
      list.push({ key: "each", text: `${money(r.amount)} ${t("payroll.rules.each")}`, tone: hidden ? "muted" : "kind" });
      if (free) list.push({ key: "free", text: t("payroll.rules.freeUnits", { n: fmt.number(r.free_units, 2) }, free) });
    } else if (r.amount_type === "percent") {
      const share = hasAmount(r.amount) ? `${sign.value}${fmt.percent(Number(r.amount), 2)}` : t("payroll.hidden");
      list.push({ key: "share", text: `${share} ${r.metric === "sales.net" ? t("payroll.rules.ofSales") : t("payroll.rules.ofBase")}`, tone: hidden ? "muted" : "kind" });
    } else {
      list.push({ key: "amount", text: money(r.amount), tone: hidden ? "muted" : "kind" });
    }
  }
  if (hasAmount(r.cap)) list.push({ key: "cap", text: t("payroll.rules.capChip", { amount: fmt.money(r.cap) }) });
  if (r.metric.startsWith("tasks.") && r.min_tasks) list.push({ key: "min", text: t("payroll.rules.minTasksChip", { n: r.min_tasks }, r.min_tasks), tone: "muted" });
  list.push({ key: "evaluate", text: t(`payroll.rules.evaluate.${r.evaluate}`), tone: "muted" });
  list.push({ key: "who", text: r.positions.length ? r.positions.map((p) => p.name).join(", ") : t("payroll.rules.everyone"), tone: "muted" });
  if (r.auto_approve) list.push({ key: "auto", text: t("payroll.rules.autoApproveChip"), tone: "muted" });
  return list;
});
</script>

<template>
  <ul class="flex flex-wrap gap-1.5">
    <li
      v-for="chip in chips"
      :key="chip.key"
      :class="[
        'rounded-full px-2.5 py-1 text-xs font-semibold tabular-nums',
        chip.tone === 'kind' ? (rule.kind === 'bonus' ? 'bg-success-soft text-success' : 'bg-danger-soft text-danger') : chip.tone === 'muted' ? 'bg-surface-2 text-muted' : 'bg-surface-2 text-fg',
      ]"
    >
      {{ chip.text }}
    </li>
  </ul>
</template>
