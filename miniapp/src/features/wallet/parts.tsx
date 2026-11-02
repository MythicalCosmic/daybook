/** Rows and cards the wallet's pages share: a bonus or fine, a payslip, an advance, a bonus rule. */
import { BadgeMinus, BadgePlus, ChevronRight, CircleMinus, FileText, Gift, HandCoins } from "lucide-react";
import type { ReactNode } from "react";

import { useI18n } from "../../i18n";
import { compareMoney, formatMoney, isZero } from "../../lib/money";
import { dayMonthLong } from "../../lib/time";
import { useMember } from "../../state/session";
import { Badge, Button, Card, ListRow, MoneyText, ProgressBar, cx, type BadgeTone } from "../../ui";
import { renderIcon } from "../../ui/icon";
import type { Adjustment, Advance, AdvanceCap, PayslipRow, Progress } from "./api";
import { isNegative, payslipState, progressView, signedAmount, type PayslipState } from "./lib";
import { advanceStatus, captionText, kindLabel, metricText, monthLabel, payslipStateLabel, useWalletT, type WalletKey } from "./text";

const KIND_ICON = { bonus: Gift, allowance: BadgePlus, fine: BadgeMinus, deduction: CircleMinus } as const;

/** An amount with a small badge under it, at the right of a row. */
function AmountStack({ children, badge }: { children: ReactNode; badge?: ReactNode }) {
  return (
    <span className="wal-amount">
      {children}
      {badge}
    </span>
  );
}

/**
 * A bonus or a fine: the kind and the amount on one line, the reason under them across the whole
 * row (reasons are long: "Savdo bonusi, 1%: Sof savdo 112 710 000 so‘m"), and where it stands.
 */
export function AdjustmentRow({ row, onOpen }: { row: Adjustment; onOpen: () => void }) {
  const t = useWalletT();
  const gone = row.status === "rejected" || row.status === "void";
  const status: { tone: BadgeTone; text: string } | null = row.dispute_open
    ? { tone: "accent", text: t("status.disputed") }
    : row.status === "approved"
      ? null
      : { tone: row.status === "proposed" ? "accent" : "neutral", text: t(`status.${row.status}` as WalletKey) };
  const tone = isNegative(row.kind) ? "accent" : "sage";
  return (
    <button type="button" className="row wal-row wal-entry" onClick={onOpen}>
      <span className={cx("circle ui-row-icon", `ui-row-icon--${tone}`)}>{renderIcon(KIND_ICON[row.kind], 19)}</span>
      <span className="row-main">
        <span className="wal-entry-head">
          <span className="row-title">{kindLabel(t, row.kind)}</span>
          <MoneyText amount={signedAmount(row)} currency={row.currency} sign="always" tone={gone ? "plain" : "auto"} className={cx("wal-entry-amount", gone && "wal-struck")} />
        </span>
        <span className="row-meta">{row.reason}</span>
        {status && (
          <Badge tone={status.tone} size="small" className="wal-entry-badge">
            {status.text}
          </Badge>
        )}
      </span>
      <ChevronRight className="ui-row-chevron" size={19} strokeWidth={2.5} aria-hidden />
    </button>
  );
}

const STATE_TONE: Record<PayslipState, BadgeTone> = { new: "accent", unpaid: "neutral", confirm: "accent", received: "sage" };

/** A payslip in a list: the month, net pay and where it stands. */
export function PayslipListRow({ row, onOpen }: { row: PayslipRow; onOpen: () => void }) {
  const t = useWalletT();
  const { locale } = useI18n();
  const member = useMember();
  const state = payslipState(row);
  return (
    <ListRow
      variant="card"
      icon={FileText}
      tone={state === "received" ? "sage" : "accent"}
      title={monthLabel(row.period, locale)}
      subtitle={row.paid_at ? t("payslip.paidOn", { date: dayMonthLong(row.paid_at, member.timeZone, locale) }) : t("payslip.notPaid")}
      value={
        <AmountStack badge={<Badge tone={STATE_TONE[state]} size="small">{payslipStateLabel(t, state)}</Badge>}>
          <MoneyText amount={row.net} currency={row.currency} />
        </AmountStack>
      }
      onClick={onOpen}
      className="wal-row"
    />
  );
}

/** An advance: the amount, where it stands and what is left to pay back. */
export function AdvanceRow({ advance, onOpen }: { advance: Advance; onOpen: () => void }) {
  const t = useWalletT();
  const { lang } = useI18n();
  const details = [advanceStatus(t, advance.status)];
  if (advance.status === "paid" && advance.left) details.push(t("advance.left", { amount: formatMoney(advance.left, advance.currency, lang) }));
  else if (advance.status === "requested" || advance.status === "approved") details.push(t("advance.over", { count: advance.installments }));
  const closed = advance.status === "rejected" || advance.status === "cancelled";
  return (
    <ListRow
      variant="card"
      icon={HandCoins}
      tone={closed ? "plain" : "sage"}
      title={<MoneyText amount={advance.amount} currency={advance.currency} className={cx(closed && "wal-struck")} />}
      subtitle={details.join(" · ")}
      onClick={onOpen}
      className="wal-row"
    />
  );
}

/** How much more the person may ask for now, and the button that asks. */
export function CapCard({ cap, onAsk }: { cap: AdvanceCap; onAsk: () => void }) {
  const t = useWalletT();
  const { lang } = useI18n();
  const room = compareMoney(cap.available, "0") > 0;
  return (
    <Card className="wal-cap">
      <span className="wal-label">{t("advances.available")}</span>
      <MoneyText amount={cap.available} currency={cap.currency} size="lg" />
      <span className="wal-hint">
        {t("advances.limit", { percent: cap.percent })}
        {!isZero(cap.used) && ` · ${t("advances.used", { amount: formatMoney(cap.used, cap.currency, lang) })}`}
      </span>
      {room ? (
        <Button variant="secondary" block icon={HandCoins} onClick={onAsk} className="wal-cap-button">
          {t("plus.advance")}
        </Button>
      ) : (
        <span className="wal-hint">{t("advances.noRoom")}</span>
      )}
    </Card>
  );
}

/** One bonus rule: what it pays now, the bar to the next step, and the line under it. */
export function RuleCard({ row, currency }: { row: Progress; currency: string }) {
  const t = useWalletT();
  const { lang } = useI18n();
  const view = progressView(row);
  const label = t(`metric.${row.metric}` as WalletKey);
  const value = metricText(t, view.unit, view.value, lang, currency);
  const caption = captionText(t, view.caption, view.unit, lang, currency);
  return (
    <Card className="wal-rule">
      <div className="wal-rule-head">
        <span className="wal-rule-name">{view.name}</span>
        {view.earned && <MoneyText amount={view.earned} currency={currency} sign="always" tone="auto" className="wal-rule-earned" />}
      </div>
      {view.bar ? (
        <ProgressBar value={view.bar.value} total={view.bar.total} tone={view.good ? "sage" : "accent"} label={label} valueLabel={value} caption={caption} size="sm" />
      ) : (
        // The bar's own head and caption, without a bar: a rule that pays while a number stays low.
        <div className="ui-bar-block">
          <div className="ui-bar-head">
            <span>{label}</span>
            <span className="num">{value}</span>
          </div>
          <div className={cx("ui-bar-caption", view.good && "wal-good")}>{caption}</div>
        </div>
      )}
    </Card>
  );
}
