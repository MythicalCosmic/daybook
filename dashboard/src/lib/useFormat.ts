/**
 * Formatting bound to the current language and the company's timezone and currency, so templates
 * can write `fmt.money(row.amount)` or `fmt.relative(item.created_at)`.
 */
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import type { Currency, Language, Money, Range } from "@/api/types";
import { formatDay, formatInstant, formatRange, formatRelative, type DayStyle, type InstantStyle } from "@/lib/dates";
import { formatCount, formatDelta, formatDuration, formatNumber, formatPercent } from "@/lib/format";
import { formatApprox, formatMoney, type MoneyFormatOptions } from "@/lib/money";
import { useCompanyStore } from "@/stores/company";

export function useFormat() {
  const { locale } = useI18n();
  const company = useCompanyStore();
  const lang = computed<Language>(() => (locale.value === "ru" || locale.value === "en" ? locale.value : "uz"));

  return {
    lang,
    money: (value: Money | number | null | undefined, currency?: Currency, options?: MoneyFormatOptions) =>
      formatMoney(value, currency ?? company.currency, lang.value, options),
    approx: (converted: Money | number, currency: Currency) => formatApprox(converted, currency, lang.value),
    number: (value: number | string | null | undefined, decimals = 0) => formatNumber(value, lang.value, decimals),
    percent: (value: number | null | undefined, decimals = 0) => formatPercent(value, lang.value, decimals),
    delta: (value: number | null | undefined, decimals = 1) => formatDelta(value, lang.value, decimals),
    count: formatCount,
    duration: (minutes: number | null | undefined) => formatDuration(minutes, lang.value),
    day: (day: string, style?: DayStyle) => formatDay(day, lang.value, style),
    instant: (iso: string | Date, style?: InstantStyle) => formatInstant(iso, company.timezone, lang.value, style),
    relative: (iso: string | Date, now?: number) => formatRelative(iso, company.timezone, lang.value, now),
    range: (range: Range) => formatRange(range, lang.value),
  };
}
