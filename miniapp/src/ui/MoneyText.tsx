import { useI18n } from "../i18n";
import { formatMoney, moneyParts, toMinor, type Cents, type Currency } from "../lib/money";
import { cx } from "./cx";

/**
 * An amount from the API ("1250000.00") in the person's language: "1 250 000 so‘m",
 * "1 250 000 сум", "$1,250.00". `hero` sets the number in Caprasimo with a small currency.
 */
export function MoneyText({
  amount,
  currency = "UZS",
  size = "md",
  compact = false,
  sign = "auto",
  cents,
  tone = "plain",
  className,
}: {
  amount: string | null | undefined;
  currency?: Currency | string;
  size?: "md" | "lg" | "hero";
  compact?: boolean;
  sign?: "auto" | "always" | "never";
  cents?: Cents;
  /** "auto" colors gains sage and losses terracotta. */
  tone?: "plain" | "auto";
  className?: string;
}) {
  const { lang } = useI18n();
  if (amount === null || amount === undefined || amount === "") {
    return <span className={cx("ui-money num", className)}>—</span>;
  }
  const minor = toMinor(amount);
  const toneClass = tone === "auto" && minor !== 0n ? (minor < 0n ? "ui-money--loss" : "ui-money--gain") : null;

  if (size === "hero") {
    const parts = moneyParts(amount, currency, lang, { compact, sign, cents });
    const unit = <span className="ui-money-unit">{parts.currency}</span>;
    return (
      <span className={cx("ui-money ui-money--hero", toneClass, className)}>
        {parts.currencyFirst && unit}
        <span className="heading num">{parts.number}</span>
        {!parts.currencyFirst && unit}
      </span>
    );
  }
  return (
    <span className={cx("ui-money num", size === "lg" && "ui-money--lg", toneClass, className)}>
      {formatMoney(amount, currency, lang, { compact, sign, cents })}
    </span>
  );
}
