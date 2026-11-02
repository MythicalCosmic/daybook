<script setup lang="ts">
/**
 * A rule at a glance, as chips rather than a sentence (three languages, no grammar to bend):
 * what it measures and the condition, what it pays or takes (a fixed amount, a share, per unit
 * after the free ones, or steps), the cap, how often it is checked and for whom.
 */
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import { useFormat } from "@/lib/useFormat";
import { compare } from "@/lib/decimal";

import { metricUnit } from "../lib";
import type { Rule } from "../types";

const props = defineProps<{ rule: Pick<Rule, "kind" | "metric" | "mode" | "op" | "threshold" | "free_units" | "tiers" | "amount_type" | "amount" | "cap" | "min_tasks" | "positions" | "evaluate" | "auto_approve"> }>();

const { t } = useI18n();
const fmt = useFormat();

const OPS = { gte: "≥", gt: ">", lte: "≤", lt: "<" } as const;
const unitText = (value: string | number) => {
  const unit = metricUnit(props.rule.metric);
  if (unit === "percent") return `${fmt.number(value, 1)} %`;
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
  if (r.mode === "tiered") {
    for (const tier of [...r.tiers].sort((a, b) => compare(a.from, b.from))) {
      list.push({ key: `tier-${tier.from}`, text: `${OPS.gte} ${unitText(tier.from)}: ${sign.value}${fmt.money(tier.amount)}`, tone: "kind" });
    }
  } else {
    if (r.threshold !== null && r.mode === "once") list.push({ key: "when", text: `${OPS[r.op]} ${unitText(r.threshold)}` });
    if (r.mode === "per_unit") {
      list.push({ key: "each", text: `${sign.value}${fmt.money(r.amount ?? "0")} ${t("payroll.rules.each")}`, tone: "kind" });
      if (r.free_units) list.push({ key: "free", text: t("payroll.rules.freeUnits", { n: r.free_units }, r.free_units) });
    } else if (r.amount_type === "percent") {
      list.push({ key: "share", text: `${sign.value}${fmt.number(r.amount ?? 0, 2)} % ${r.metric === "sales.net" ? t("payroll.rules.ofSales") : t("payroll.rules.ofBase")}`, tone: "kind" });
    } else {
      list.push({ key: "amount", text: `${sign.value}${fmt.money(r.amount ?? "0")}`, tone: "kind" });
    }
  }
  if (r.cap) list.push({ key: "cap", text: t("payroll.rules.capChip", { amount: fmt.money(r.cap) }) });
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
