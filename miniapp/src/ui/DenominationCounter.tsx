import { Banknote } from "lucide-react";

import { useI18n } from "../i18n";
import { formatMoney, groupDigits, multiplyMoney, sumMoney, type Currency } from "../lib/money";
import { cx } from "./cx";
import { MoneyText } from "./MoneyText";
import { Stepper } from "./Stepper";

/** Uzbek banknotes in circulation, largest first. */
export const UZS_NOTES = ["200000", "100000", "50000", "20000", "10000", "5000", "2000", "1000"] as const;

export type NoteCounts = Partial<Record<string, number>>;

/** The display total of counted notes (exact, in integer arithmetic). */
export function countedTotal(counts: NoteCounts): string {
  return sumMoney(Object.entries(counts).map(([note, count]) => multiplyMoney(note, count ?? 0)));
}

export function countedNotes(counts: NoteCounts): number {
  return Object.values(counts).reduce<number>((total, count) => total + (count ?? 0), 0);
}

/**
 * Count cash by banknote: a stepper per note (type or hold to count fast), the subtotal on each
 * line and a running total at the bottom. Used for the opening float and the blind count.
 */
export function DenominationCounter({
  counts,
  onChange,
  notes = UZS_NOTES,
  currency = "UZS",
  stickyTotal = false,
}: {
  counts: NoteCounts;
  onChange: (counts: NoteCounts) => void;
  notes?: readonly string[];
  currency?: Currency | string;
  /** Keep the total pinned to the bottom of the scrolling screen while counting. */
  stickyTotal?: boolean;
}) {
  const { t, lang } = useI18n();
  const total = countedTotal(counts);
  const pieces = countedNotes(counts);
  return (
    <div className={cx("ui-denoms", stickyTotal && "ui-denoms--sticky")}>
      {notes.map((note, index) => {
        const count = counts[note] ?? 0;
        return (
          <div key={note} className={cx("ui-denom", count > 0 && "ui-denom--counted")}>
            <span className={cx("ui-note", index < 3 ? "ui-note--sage" : "ui-note--sand")}>
              <Banknote size={16} strokeWidth={2.4} aria-hidden />
              <span className="num">{groupDigits(note, lang)}</span>
            </span>
            <Stepper value={count} onChange={(next) => onChange({ ...counts, [note]: next })} editable size="sm" label={groupDigits(note, lang)} />
            {/* Short and without the currency: the total below names it, and phones are narrow. */}
            <span className="ui-denom-sum num">{count > 0 ? formatMoney(multiplyMoney(note, count), currency, lang, { compact: true, bare: true }) : "—"}</span>
          </div>
        );
      })}
      <div className="ui-denoms-total" aria-live="polite">
        <span className="ui-denoms-total-label">
          <span>{t("ui.denominations.total")}</span>
          <span className="muted num">{t("ui.denominations.notes", { count: pieces })}</span>
        </span>
        <MoneyText amount={total} currency={currency} size="hero" />
      </div>
    </div>
  );
}
