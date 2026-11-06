/**
 * The expenses sheets: a new expense (amount, where the money came from, category, day, what it
 * was for, receipts) and what became of it once sent, and one claim with its receipts and
 * "Cancel the expense" while it waits.
 */
import { CircleCheck, ReceiptText, Send, TriangleAlert, X } from "lucide-react";
import { useState } from "react";

import { baseCurrency } from "../../api/membership";
import { useI18n } from "../../i18n";
import { errorText } from "../../lib/actions";
import { formatMoney } from "../../lib/money";
import { clock, dayKey, dayMonthLong } from "../../lib/time";
import { useDraftGuard } from "../../lib/useDraftGuard";
import { useMember } from "../../state/session";
import { haptic } from "../../telegram";
import { Banner, Button, ChipGroup, DateInput, EmptyState, Field, Input, LoadError, MoneyInput, MoneyText, ScreenSkeleton, Segmented, Select, SheetTitle, cx } from "../../ui";
import type { SheetProps } from "../registry";
import { SheetFacts, SheetMissing } from "../states";
import { useFeatureOpen } from "../useFeatureOpen";
import { useCategories, useClaims, useClaimWallet, useSubmitClaim, type Claim, type ExpenseCategory, type PaidFrom } from "./api";
import {
  canCancel,
  claimDraft,
  comesBack,
  DESCRIPTION_MAX,
  groupCategories,
  heldCash,
  needsReceipt,
  serverProblems,
  underThreshold,
  usualCategories,
  type ClaimProblem,
} from "./lib";
import { ReceiptLinks, StatusBadge, useCancel, useSpentDay } from "./parts";
import { ReceiptsInput } from "./ReceiptsInput";
import { backLabel, paidFromLabel, useExpensesT, type ExpensesKey } from "./text";
import "./expenses.css";

// — a new expense —

export function NewClaimSheet({ close }: SheetProps) {
  const t = useExpensesT();
  const member = useMember();
  const categories = useCategories(member.companyId);
  const [sent, setSent] = useState<Claim | null>(null);

  if (sent) return <ClaimResult claim={sent} close={close} />;
  // A refetch that fails (back from the camera) keeps the form and what is typed in it.
  if (!categories.data) {
    if (categories.isPending) return <ScreenSkeleton variant="detail" delay={150} />;
    return <LoadError compact error={categories.error} onRetry={() => void categories.refetch()} />;
  }
  if (!categories.data.length) {
    return (
      <>
        <SheetTitle>{t("new.title")}</SheetTitle>
        <EmptyState compact icon={ReceiptText} tone="sage" title={t("new.noCategories")} body={t("new.noCategoriesBody")} />
      </>
    );
  }
  return <ClaimForm categories={categories.data} onSent={setSent} />;
}

/** Problems that contradict what is there show at once; missing pieces only after a press of Send. */
const AT_ONCE: ReadonlySet<ClaimProblem> = new Set(["date", "heldOver"]);

function ClaimForm({ categories, onSent }: { categories: ExpenseCategory[]; onSent: (claim: Claim) => void }) {
  const t = useExpensesT();
  const { lang, t: appT } = useI18n();
  const member = useMember();
  const company = member.companyId;
  const wallet = useClaimWallet(company);
  const claims = useClaims(company);
  const submit = useSubmitClaim(company);
  const today = dayKey(new Date(), member.timeZone);

  const [typing, setTyping] = useState("");
  const [category, setCategory] = useState<number | null>(categories.length === 1 ? categories[0].id : null);
  const [spentOn, setSpentOn] = useState(today);
  const [description, setDescription] = useState("");
  const [paidFrom, setPaidFrom] = useState<PaidFrom>("own_money");
  const [receipts, setReceipts] = useState<File[]>([]);
  const [tried, setTried] = useState(false);
  const [failure, setFailure] = useState<unknown>(null);
  useDraftGuard(Boolean(typing || description.trim() || receipts.length));

  const currency = wallet.data?.currency ?? baseCurrency(member);
  const money = (amount: string) => formatMoney(amount, currency, lang);
  const held = heldCash(wallet.data);
  // Held cash is a choice only while there is some; otherwise the money was my own.
  const from: PaidFrom = held ? paidFrom : "own_money";
  const limit = wallet.data?.receipt_required_over ?? null;
  const threshold = wallet.data?.approval_threshold ?? null;
  // A category switched off since the form opened (the list refetched) is no longer a choice.
  const chosen = category !== null && categories.some((row) => row.id === category) ? category : null;
  const draft = claimDraft({ typing, category: chosen, spentOn, description, paidFrom: from, receipts }, { today, held, receiptRequiredOver: limit });
  const server = serverProblems(failure);
  const shows = (problem: ClaimProblem) => draft.problems.includes(problem) && (tried || AT_ONCE.has(problem));
  // Editing anything after a refusal clears it: the server's words were about what was there.
  const edit =
    <T,>(set: (value: T) => void) =>
    (value: T) => {
      setFailure(null);
      set(value);
    };

  const groups = groupCategories(categories);
  // One-tap chips for the categories I claim most; pointless with a single category.
  const usual = categories.length > 1 ? usualCategories(claims.data, categories) : [];
  const receiptNeeded = needsReceipt(typing, limit);

  const send = () => {
    setTried(true);
    if (submit.isPending) return;
    if (!draft.payload) {
      haptic.notify("warning");
      return;
    }
    setFailure(null);
    submit.mutate(draft.payload, {
      onSuccess: (claim) => {
        haptic.notify("success");
        onSent(claim);
      },
      onError: (error) => {
        haptic.notify("error");
        setFailure(error);
      },
    });
  };

  return (
    <>
      <SheetTitle>{t("new.title")}</SheetTitle>
      <Field
        label={t("new.amount")}
        error={(shows("amount") && t("new.amountMissing")) || server?.fields.amount}
        hint={underThreshold(typing, threshold) && threshold ? t("new.noApproval", { amount: money(threshold) }) : undefined}
      >
        <MoneyInput value={typing} onChange={edit(setTyping)} currency={currency} size="lg" autoFocus />
      </Field>

      {held && (
        <Field
          label={t("new.paidFrom")}
          error={(shows("heldOver") && t("new.heldOver", { amount: money(held) })) || server?.fields.paid_from}
          hint={from === "held_cash" ? t("new.heldHint", { amount: money(held) }) : undefined}
        >
          <Segmented<PaidFrom>
            fit
            value={from}
            onChange={edit(setPaidFrom)}
            label={t("new.paidFrom")}
            options={[
              { value: "own_money", label: t("from.own_money") },
              { value: "held_cash", label: t("from.held_cash") },
            ]}
          />
        </Field>
      )}

      <Field label={t("new.category")} error={(shows("category") && t("new.categoryPick")) || server?.fields.category}>
        {usual.length > 0 && (
          <ChipGroup
            scroll
            value={chosen !== null && usual.some((row) => row.id === chosen) ? String(chosen) : null}
            onChange={(value) => value && edit(setCategory)(Number(value))}
            options={usual.map((row) => ({ value: String(row.id), label: row.name }))}
            label={t("new.categoryUsual")}
          />
        )}
        <Select value={chosen === null ? "" : String(chosen)} onChange={(event) => edit(setCategory)(event.target.value ? Number(event.target.value) : null)}>
          <option value="" disabled>
            {t("new.categoryPick")}
          </option>
          {groups.map(({ parent, children }) =>
            children.length ? (
              <optgroup key={parent.id} label={parent.name}>
                <option value={parent.id}>{parent.name}</option>
                {children.map((child) => (
                  <option key={child.id} value={child.id}>
                    {child.name}
                  </option>
                ))}
              </optgroup>
            ) : (
              <option key={parent.id} value={parent.id}>
                {parent.name}
              </option>
            ),
          )}
        </Select>
      </Field>

      <Field label={t("new.date")} error={(shows("date") && t("new.dateFuture")) || server?.fields.spent_on}>
        <DateInput value={spentOn} onChange={edit(setSpentOn)} label={t("new.date")} max={today} today={today} long />
      </Field>

      <Field label={t("new.description")} optional error={server?.fields.description}>
        <Input
          value={description}
          onChange={(event) => edit(setDescription)(event.target.value)}
          maxLength={DESCRIPTION_MAX}
          placeholder={t("new.descriptionPlaceholder")}
          enterKeyHint="done"
        />
      </Field>

      <Field
        label={t("new.receipts")}
        optional={!receiptNeeded}
        error={(shows("receipt") && limit && t("new.receiptNeeded", { amount: money(limit) })) || server?.fields.receipts}
        hint={receiptNeeded && limit ? t("new.receiptNeeded", { amount: money(limit) }) : t("new.receiptsHint")}
      >
        <ReceiptsInput value={receipts} onChange={edit(setReceipts)} disabled={submit.isPending} />
      </Field>

      {failure !== null && <Banner tone="accent" icon={TriangleAlert} title={server?.message ?? errorText(failure, appT)} />}

      <Button variant="primary" size="lg" block icon={Send} loading={submit.isPending} onClick={send}>
        {t("new.submit")}
      </Button>
    </>
  );
}

/** What became of the expense: waiting for someone's approval, or recorded at once. */
function ClaimResult({ claim, close }: { claim: Claim; close: () => void }) {
  const t = useExpensesT();
  const go = useFeatureOpen("expenses");
  const waiting = claim.status === "submitted";
  const back = comesBack(claim);
  const after = waiting ? t("result.sentBody") : claim.paid_from === "held_cash" ? t("result.fromHeld") : back ? backLabel(t, back) : null;
  return (
    <div className="exp-result" role="status">
      <span className={cx("circle exp-result-icon", waiting ? "exp-result-icon--wait" : "exp-result-icon--done")}>
        {waiting ? <Send size={28} strokeWidth={2.4} aria-hidden /> : <CircleCheck size={30} strokeWidth={2.4} aria-hidden />}
      </span>
      <div className="heading title-sm">{t(waiting ? "result.sent" : "result.recorded")}</div>
      <p className="exp-result-line">
        <MoneyText amount={claim.amount} currency={claim.currency} className="exp-result-amount" />
        <span> · {claim.category.name}</span>
      </p>
      {after && <p className="ft-hint">{after}</p>}
      <Button variant="primary" size="lg" block onClick={close} className="exp-result-done">
        {t("result.done")}
      </Button>
      <Button variant="ghost" block onClick={() => go.page("list")}>
        {t("me.expenses")}
      </Button>
    </div>
  );
}

// — one claim —

export function ClaimSheet({ params, close }: SheetProps) {
  const member = useMember();
  const claims = useClaims(member.companyId);
  const claim = claims.data?.find((row) => row.id === Number(params.id));
  if (!claim) return <SheetMissing pending={claims.isPending} error={claims.error} onRetry={() => void claims.refetch()} />;
  const refresh = async () => (await claims.refetch()).data?.find((row) => row.id === claim.id);
  return <ClaimDetails claim={claim} close={close} refresh={refresh} fetchedAt={claims.dataUpdatedAt} />;
}

function ClaimDetails({ claim, close, refresh, fetchedAt }: { claim: Claim; close: () => void; refresh: () => Promise<Claim | undefined>; fetchedAt: number }) {
  const t = useExpensesT();
  const { locale } = useI18n();
  const member = useMember();
  const day = useSpentDay();
  const cancel = useCancel(claim, close);
  const moment = (at: string) => `${dayMonthLong(at, member.timeZone, locale)}, ${clock(at, member.timeZone, locale)}`;
  const back = comesBack(claim);
  const decided = (() => {
    if (!claim.decided_at || claim.status === "submitted" || claim.status === "cancelled") return null;
    const date = dayMonthLong(claim.decided_at, member.timeZone, locale);
    if (!claim.decided_by) return claim.status === "rejected" ? t("detail.decidedOn", { date }) : t("detail.auto");
    const key: ExpensesKey = claim.status === "rejected" ? "detail.rejected" : "detail.approved";
    return t(key, { name: claim.decided_by.name, date });
  })();
  return (
    <>
      <SheetTitle kicker={claim.category.name}>
        <MoneyText amount={claim.amount} currency={claim.currency} />
      </SheetTitle>
      <div className="exp-sheet-status">
        <StatusBadge claim={claim} />
        {back && <span className="ft-hint">{backLabel(t, back)}</span>}
      </div>
      {claim.description && <p className="ft-text">{claim.description}</p>}
      {claim.status === "rejected" && claim.reject_reason && <Banner icon={TriangleAlert} title={t("claim.reason", { reason: claim.reject_reason })} />}
      <SheetFacts
        lines={[
          t("detail.date", { date: day(claim.spent_on) }),
          paidFromLabel(t, claim.paid_from),
          claim.branch && t("detail.branch", { name: claim.branch.name }),
          t("detail.sent", { date: moment(claim.created_at) }),
          decided,
        ]}
      />
      <div className="exp-label">{t("detail.receipts")}</div>
      <ReceiptLinks claim={claim} refresh={refresh} fetchedAt={fetchedAt} />
      {canCancel(claim) && (
        <Button variant="secondary" block icon={X} loading={cancel.pending} onClick={() => void cancel.run()}>
          {t("detail.cancel")}
        </Button>
      )}
    </>
  );
}
