/**
 * Exact decimal arithmetic for the rare places the client must add money (a payroll grid preview,
 * a cash count, a split). Server totals always win; never parseFloat a sum. Values in and out are
 * the API's decimal strings.
 */
import Decimal from "decimal.js";

import type { Money } from "@/api/types";

const D = Decimal.clone({ precision: 40, rounding: Decimal.ROUND_HALF_UP });

export type DecimalInput = Money | number | Decimal;

export function dec(value: DecimalInput | null | undefined): Decimal {
  if (value === null || value === undefined || value === "") return new D(0);
  return new D(value);
}

/** Two decimal places, half up: "1250000.50". */
export function toMoney(value: DecimalInput): Money {
  return dec(value).toFixed(2, D.ROUND_HALF_UP);
}

export function sum(values: Iterable<DecimalInput | null | undefined>): Money {
  let total = new D(0);
  for (const value of values) total = total.plus(dec(value));
  return toMoney(total);
}

export function add(a: DecimalInput, b: DecimalInput): Money {
  return toMoney(dec(a).plus(dec(b)));
}

export function subtract(a: DecimalInput, b: DecimalInput): Money {
  return toMoney(dec(a).minus(dec(b)));
}

export function multiply(a: DecimalInput, b: DecimalInput): Money {
  return toMoney(dec(a).times(dec(b)));
}

/** Division rounded to cents; null when dividing by zero. */
export function divide(a: DecimalInput, b: DecimalInput): Money | null {
  const divisor = dec(b);
  if (divisor.isZero()) return null;
  return toMoney(dec(a).dividedBy(divisor));
}

export function compare(a: DecimalInput, b: DecimalInput): -1 | 0 | 1 {
  return dec(a).comparedTo(dec(b)) as -1 | 0 | 1;
}

export const isZero = (value: DecimalInput) => dec(value).isZero();
export const isNegative = (value: DecimalInput) => dec(value).isNegative() && !dec(value).isZero();

/** Share of `part` in `whole` as a percentage with `digits` decimals; null when whole is 0. */
export function percent(part: DecimalInput, whole: DecimalInput, digits = 1): number | null {
  const base = dec(whole);
  if (base.isZero()) return null;
  return dec(part).dividedBy(base).times(100).toDecimalPlaces(digits, D.ROUND_HALF_UP).toNumber();
}

/** Change from `previous` to `current` in percent (KPI deltas); null without a base. */
export function changePercent(current: DecimalInput, previous: DecimalInput, digits = 1): number | null {
  const base = dec(previous);
  if (base.isZero()) return null;
  return dec(current).minus(base).dividedBy(base.abs()).times(100).toDecimalPlaces(digits, D.ROUND_HALF_UP).toNumber();
}

/**
 * Converts between currencies with a rate given as "UZS per 1 unit" (the API's Rate):
 * USD → UZS multiplies, UZS → USD divides.
 */
export function convert(amount: DecimalInput, rate: DecimalInput, direction: "to_base" | "from_base"): Money | null {
  return direction === "to_base" ? multiply(amount, rate) : divide(amount, rate);
}
