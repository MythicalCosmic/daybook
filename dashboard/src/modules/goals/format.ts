/**
 * How a goal's numbers read: money compact in the base currency ("1,5 mlrd so‘m"), percents with
 * one decimal, counts whole; and the icon of each metric.
 */
import { Building2, ChartLine, Clock3, GraduationCap, Landmark, Percent, ReceiptText, TrendingUp, UserMinus, Users } from "@lucide/vue";
import type { Component } from "vue";

import { useFormat } from "@/lib/useFormat";

import type { MetricKey, Unit } from "./api";

export const METRIC_ICONS: Record<MetricKey, Component> = {
  revenue: TrendingUp,
  gross_profit: ChartLine,
  net_profit: Landmark,
  margin: Percent,
  branches: Building2,
  headcount: Users,
  turnover: UserMinus,
  average_check: ReceiptText,
  late_arrivals: Clock3,
  training: GraduationCap,
};

/** `value(goal, "1500000000.00")` → "1,5 mlrd so‘m" (uz), "12,4 %" for a percent, "3" for a count. */
export function useGoalFormat() {
  const fmt = useFormat();
  return {
    value(goal: { unit: Unit }, value: string | number | null | undefined, options: { full?: boolean } = {}): string {
      if (value === null || value === undefined || value === "") return "—";
      if (goal.unit === "money") return fmt.money(value, undefined, { compact: !options.full });
      if (goal.unit === "percent") return fmt.percent(Number(value), 1);
      return fmt.number(value, 0);
    },
  };
}
