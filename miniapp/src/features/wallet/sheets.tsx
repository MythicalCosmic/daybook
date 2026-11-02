/**
 * The wallet's sheets: one bonus or fine (with "Dispute it"), the advance request, and one
 * advance with its repayment months (and "Cancel the request" while nobody has decided).
 */
import { CircleCheck, Clock3, HandCoins, Scale, SearchX, Send, X } from "lucide-react";
import { useState, type ReactNode } from "react";

import { useI18n } from "../../i18n";
import { errorText } from "../../lib/actions";
import { formatMoney } from "../../lib/money";
import { dayMonthLong } from "../../lib/time";
import { useDraftGuard } from "../../lib/useDraftGuard";
import { useNavigation } from "../../state/navigation";
import { useMember } from "../../state/session";
import { useToast } from "../../state/toast";
import { confirm, haptic } from "../../telegram";
import { Badge, Button, Card, ChipGroup, EmptyState, Field, Input, LoadError, MoneyInput, MoneyText, ScreenSkeleton, SheetTitle, Textarea, type BadgeTone } from "../../ui";
import type { SheetProps } from "../registry";
import { useAdjustments, useAdvances, useCancelAdvance, useDispute, useRequestAdvance, type Adjustment, type Advance } from "./api";
import { advanceDraft, DISPUTE_MAX, disputePayload, disputeStage, isNegative, REASON_MAX, repaymentMonths, signedAmount } from "./lib";
import { advanceStatus, kindLabel, monthLabel, useWalletT, type WalletKey, type WalletT } from "./text";
import "./wallet.css";

/** A sheet's data hasn't come, didn't come, or the row isn't (or is no longer) there. */
function Missing({ pending, error, onRetry }: { pending: boolean; error: unknown; onRetry: () => void }) {
  const { t } = useI18n();
  if (pending) return <ScreenSkeleton variant="detail" delay={150} />;
  if (error) return <LoadError compact error={error} onRetry={onRetry} />;
  return <EmptyState compact icon={SearchX} tone="sage" title={t("ui.notFound.title")} body={t("ui.notFound.body")} />;
}

/** "Label: value" lines under a sheet's title. */
function Facts({ lines }: { lines: (ReactNode | null | false | undefined)[] }) {
  const shown = lines.filter(Boolean);
  if (!shown.length) return null;
  return (
    <ul className="wal-facts">
      {shown.map((line, index) => (
        <li key={index}>{line}</li>
      ))}
    </ul>
  );
}

/** Feedback after a write: a buzz and a toast. */
function useFeedback() {
  const toast = useToast();
  const { t: appT } = useI18n();
  return {
    ok: (text: string) => {
      haptic.notify("success");
      toast(text, { tone: "success" });
    },
    fail: (error: unknown) => {
      haptic.notify("error");
      toast(errorText(error, appT), { tone: "error" });
    },
  };
}

function sourceLine(t: WalletT, row: Adjustment): string {
  switch (row.source) {
    case "rule":
      return t("source.rule", { name: row.rule?.name ?? "" });
    case "task":
      return t("source.task", { name: row.task?.name ?? "" });
    case "attendance":
      return t("source.attendance");
    case "discipline":
      return t("source.discipline");
    default:
      return row.proposed_by ? t("source.manual", { name: row.proposed_by }) : t("source.manualNobody");
  }
}

const STATUS_TONE: Record<Adjustment["status"], BadgeTone> = { proposed: "accent", approved: "sage", rejected: "neutral", void: "neutral" };

// — a bonus or a fine —

export function AdjustmentSheet({ params }: SheetProps) {
  const t = useWalletT();
  const { locale } = useI18n();
  const member = useMember();
  const navigation = useNavigation();
  const adjustments = useAdjustments(member.companyId);
  const row = adjustments.data?.find((item) => item.id === Number(params.id));
  if (!row) return <Missing pending={adjustments.isPending} error={adjustments.error} onRetry={() => void adjustments.refetch()} />;

  const date = (moment: string) => dayMonthLong(moment, member.timeZone, locale);
  const decided = row.decided_at
    ? row.decided_by
      ? t("adj.decided", { name: row.decided_by, date: date(row.decided_at) })
      : t("adj.decidedOn", { date: date(row.decided_at) })
    : null;
  return (
    <>
      <SheetTitle kicker={monthLabel(row.period, locale)}>{kindLabel(t, row.kind)}</SheetTitle>
      <div className="wal-sheet-amount">
        <MoneyText amount={signedAmount(row)} currency={row.currency} sign="always" tone={row.status === "approved" || row.status === "proposed" ? "auto" : "plain"} size="lg" />
        <Badge tone={STATUS_TONE[row.status]} size="small">
          {t(`status.${row.status}` as WalletKey)}
        </Badge>
      </div>
      <p className="wal-reason">{row.reason}</p>
      <Facts lines={[sourceLine(t, row), decided, row.decision_note && t("adj.note", { text: row.decision_note })]} />
      {row.payslip !== null && (
        <Button
          variant="ghost"
          className="wal-link"
          onClick={() => navigation.push({ feature: "wallet", page: "payslip", params: { id: row.payslip! } })}
        >
          {t("adj.onPayslip", { month: monthLabel(row.period, locale) })}
        </Button>
      )}
      <Dispute row={row} />
    </>
  );
}

/** A fine's dispute: what was sent and the answer, the form to send one, or why it can't be. */
function Dispute({ row }: { row: Adjustment }) {
  const t = useWalletT();
  const { locale } = useI18n();
  const member = useMember();
  const dispute = useDispute(member.companyId);
  const feedback = useFeedback();
  const [writing, setWriting] = useState(false);
  const [text, setText] = useState("");
  useDraftGuard(writing && Boolean(text.trim()));
  const stage = disputeStage(row);
  const date = (moment: string) => dayMonthLong(moment, member.timeZone, locale);

  if (stage === "waiting" || stage === "answered") {
    return (
      <Card tone="outline" className="wal-dispute">
        <div className="wal-dispute-head">{t("dispute.yours", { date: date(row.disputed_at!) })}</div>
        <p className="wal-dispute-text">{row.dispute_text}</p>
        {stage === "answered" ? (
          <>
            <div className="wal-dispute-head">{t("dispute.answer", { date: date(row.dispute_answered_at!) })}</div>
            <p className="wal-dispute-text">{row.dispute_answer}</p>
          </>
        ) : (
          <Badge tone="accent" size="small" icon={Clock3}>
            {t("dispute.waiting")}
          </Badge>
        )}
      </Card>
    );
  }
  if (stage === "none") {
    // A fine that stands on a closed month: say why there is no button.
    return isNegative(row.kind) && row.locked && (row.status === "approved" || row.status === "proposed") ? <p className="wal-hint">{t("dispute.locked")}</p> : null;
  }
  if (!writing) {
    return (
      <Button variant="secondary" block icon={Scale} onClick={() => setWriting(true)}>
        {t("dispute.button")}
      </Button>
    );
  }
  const payload = disputePayload(text);
  const left = DISPUTE_MAX - text.trim().length;
  const send = () => {
    if (!payload || dispute.isPending) return;
    dispute.mutate(
      { id: row.id, ...payload },
      {
        onSuccess: () => {
          feedback.ok(t("dispute.sent"));
          setWriting(false);
          setText("");
        },
        onError: feedback.fail,
      },
    );
  };
  return (
    <>
      <Field label={t("dispute.label")} hint={left < 100 ? t("dispute.left", { count: Math.max(0, left) }) : t("dispute.hint")}>
        <Textarea value={text} onChange={(event) => setText(event.target.value)} rows={4} maxLength={DISPUTE_MAX} placeholder={t("dispute.placeholder")} autoFocus />
      </Field>
      <Button variant="primary" size="lg" block icon={Send} disabled={!payload} loading={dispute.isPending} onClick={send}>
        {t("dispute.send")}
      </Button>
    </>
  );
}

// — asking for an advance —

const INSTALLMENT_CHOICES = [1, 2, 3] as const;

export function AdvanceRequestSheet({ close }: SheetProps) {
  const t = useWalletT();
  const { lang } = useI18n();
  const member = useMember();
  const advances = useAdvances(member.companyId);
  const request = useRequestAdvance(member.companyId);
  const feedback = useFeedback();
  const [typing, setTyping] = useState("");
  const [installments, setInstallments] = useState(1);
  const [reason, setReason] = useState("");
  useDraftGuard(Boolean(typing || reason.trim()));

  if (!advances.data) return <Missing pending={advances.isPending} error={advances.error} onRetry={() => void advances.refetch()} />;
  const { cap } = advances.data;
  const money = (amount: string) => formatMoney(amount, cap.currency, lang);
  const draft = advanceDraft({ typing, installments, reason }, cap);
  if ("problem" in draft && draft.problem === "noRoom") {
    return (
      <>
        <SheetTitle>{t("request.title")}</SheetTitle>
        <EmptyState compact icon={HandCoins} tone="sage" title={t("advances.noRoom")} body={t("advances.limit", { percent: cap.percent })} />
      </>
    );
  }
  const payload = "payload" in draft ? draft.payload : null;
  const submit = () => {
    if (!payload || request.isPending) return;
    request.mutate(payload, {
      onSuccess: () => {
        feedback.ok(t("request.sent"));
        close();
      },
      onError: feedback.fail,
    });
  };
  return (
    <>
      <SheetTitle kicker={t("request.upTo", { amount: money(cap.available) })}>{t("request.title")}</SheetTitle>
      <Field label={t("request.amount")} error={"problem" in draft && draft.problem === "overCap" ? t("request.overCap", { amount: money(cap.available) }) : undefined}>
        <MoneyInput value={typing} onChange={setTyping} currency={cap.currency} size="lg" autoFocus />
      </Field>
      <Field label={t("request.installments")} hint={installments > 1 ? t("request.installmentsHint") : undefined}>
        <ChipGroup
          options={INSTALLMENT_CHOICES.map((count) => ({ value: String(count), label: t("request.months", { count }) }))}
          value={String(installments)}
          onChange={(value) => value && setInstallments(Number(value))}
          label={t("request.installments")}
        />
      </Field>
      <Field label={t("request.reason")} optional>
        <Input value={reason} onChange={(event) => setReason(event.target.value)} maxLength={REASON_MAX} placeholder={t("request.reasonPlaceholder")} />
      </Field>
      <Button variant="primary" size="lg" block icon={HandCoins} disabled={!payload} loading={request.isPending} onClick={submit}>
        {payload ? t("request.submit", { amount: money(payload.amount) }) : t("request.title")}
      </Button>
    </>
  );
}

// — one advance —

const ADVANCE_TONE: Record<Advance["status"], BadgeTone> = {
  requested: "accent",
  approved: "accent",
  paid: "sage",
  repaid: "sage",
  rejected: "neutral",
  cancelled: "neutral",
};

export function AdvanceSheet({ params, close }: SheetProps) {
  const t = useWalletT();
  const { lang, locale } = useI18n();
  const member = useMember();
  const advances = useAdvances(member.companyId);
  const cancel = useCancelAdvance(member.companyId);
  const feedback = useFeedback();
  const advance = advances.data?.advances.find((item) => item.id === Number(params.id));
  if (!advance) return <Missing pending={advances.isPending} error={advances.error} onRetry={() => void advances.refetch()} />;

  const date = (moment: string) => dayMonthLong(moment, member.timeZone, locale);
  const money = (amount: string) => formatMoney(amount, advance.currency, lang);
  const showSchedule = advance.status === "paid" || advance.status === "repaid";
  const takeBack = async () => {
    if (cancel.isPending || !(await confirm(t("advance.cancelAsk")))) return;
    cancel.mutate(advance.id, {
      onSuccess: () => {
        feedback.ok(t("advance.cancelled"));
        close();
      },
      onError: feedback.fail,
    });
  };
  return (
    <>
      <SheetTitle kicker={t("advance.title")}>
        <MoneyText amount={advance.amount} currency={advance.currency} />
      </SheetTitle>
      <div className="wal-sheet-amount">
        <Badge tone={ADVANCE_TONE[advance.status]} size="small">
          {advanceStatus(t, advance.status)}
        </Badge>
        {advance.status === "paid" && advance.left && <span className="wal-hint">{t("advance.left", { amount: money(advance.left) })}</span>}
      </div>
      {advance.reason && <p className="wal-reason">{advance.reason}</p>}
      <Facts
        lines={[
          t("advance.askedOn", { date: date(advance.created_at) }),
          advance.decided_by && t("advance.decided", { name: advance.decided_by }),
          advance.decision_note && t("adj.note", { text: advance.decision_note }),
          advance.paid_at && t("advance.paidOn", { date: date(advance.paid_at) }),
          !showSchedule && t("advance.over", { count: advance.installments }),
        ]}
      />
      {showSchedule && (
        <>
          <div className="wal-label">{t("advance.schedule")}</div>
          <ul className="wal-schedule">
            {repaymentMonths(advance).map((month) => (
              <li key={month.period} className={month.done ? "wal-schedule-done" : undefined}>
                <span className="wal-schedule-icon" aria-hidden>
                  {month.done ? <CircleCheck size={18} strokeWidth={2.4} /> : <Clock3 size={18} strokeWidth={2.4} />}
                </span>
                <span className="wal-schedule-month">{monthLabel(month.period, locale)}</span>
                <span className="wal-schedule-value">
                  {month.repayment?.amount ? (
                    <MoneyText amount={`-${month.repayment.amount}`} currency={advance.currency} />
                  ) : (
                    t(month.done ? "advance.monthTaken" : "advance.monthComing")
                  )}
                  {month.repayment && <small>{t(month.repayment.how === "money" ? "advance.monthMoney" : "advance.monthTaken")}</small>}
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
      {advance.status === "requested" && (
        <Button variant="secondary" block icon={X} loading={cancel.isPending} onClick={() => void takeBack()}>
          {t("advance.cancel")}
        </Button>
      )}
    </>
  );
}
