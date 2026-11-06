/** Pieces the expenses page and sheets share: a claim's row and badge, the wallet summary, receipts on file. */
import type { UseQueryResult } from "@tanstack/react-query";
import { Clock3, FileText, Paperclip, ReceiptText, X } from "lucide-react";
import { useState } from "react";

import { useI18n } from "../../i18n";
import { dayMonthYear } from "../../lib/time";
import { useMember } from "../../state/session";
import { useToast } from "../../state/toast";
import { confirm, haptic, openLink } from "../../telegram";
import { Badge, Button, ListCard, ListRow, MoneyText, Skeleton, cx } from "../../ui";
import { EntryRow } from "../EntryRow";
import { useFeedback } from "../states";
import { useCancelClaim, type Claim, type ClaimReceipt, type ClaimWallet } from "./api";
import { canCancel, comesBack, heldCash, isPdf, positive } from "./lib";
import { backLabel, paidFromLabel, statusLabel, statusTone, useExpensesT } from "./text";

/**
 * "5 November", or "5 November 2025" for another year: the day the money was spent. The day is
 * a calendar date (read as itself in any zone); "this year" is the company's, on 1 January too.
 */
export function useSpentDay(): (day: string) => string {
  const { locale } = useI18n();
  const { timeZone } = useMember();
  return (day) => dayMonthYear(day, timeZone, locale, new Date());
}

export function StatusBadge({ claim }: { claim: Pick<Claim, "status" | "status_label"> }) {
  const t = useExpensesT();
  return (
    <Badge tone={statusTone(claim.status)} size="small" icon={claim.status === "submitted" ? Clock3 : undefined}>
      {statusLabel(t, claim)}
    </Badge>
  );
}

/** Take a waiting claim back, after asking; `after` runs once it is cancelled. */
export function useCancel(claim: Claim, after?: () => void): { run: () => Promise<void>; pending: boolean } {
  const t = useExpensesT();
  const member = useMember();
  const cancel = useCancelClaim(member.companyId);
  const feedback = useFeedback();
  const run = async () => {
    if (cancel.isPending || !(await confirm(t("claim.cancelAsk")))) return;
    cancel.mutate(claim.id, {
      onSuccess: () => {
        feedback.ok(t("claim.cancelled"));
        after?.();
      },
      onError: feedback.fail,
    });
  };
  return { run, pending: cancel.isPending };
}

/**
 * One claim in my list: the category and amount, the day and where the money came from, what
 * it was for, a rejection's reason, and its status; while it waits, Cancel under it.
 */
export function ClaimRow({ claim, onOpen }: { claim: Claim; onOpen: () => void }) {
  const t = useExpensesT();
  const day = useSpentDay();
  const cancel = useCancel(claim);
  const closed = claim.status === "cancelled" || claim.status === "rejected";
  const back = comesBack(claim);
  return (
    <div className="exp-claim">
      <EntryRow
        icon={ReceiptText}
        tone={claim.status === "submitted" ? "accent" : closed ? "plain" : "sage"}
        title={claim.category.name}
        aside={<MoneyText amount={claim.amount} currency={claim.currency} className={cx("exp-amount", closed && "exp-struck")} />}
        details={[
          `${day(claim.spent_on)} · ${paidFromLabel(t, claim.paid_from)}`,
          claim.description,
          claim.status === "rejected" && claim.reject_reason && t("claim.reason", { reason: claim.reject_reason }),
          back && backLabel(t, back),
        ]}
        chips={
          <>
            <StatusBadge claim={claim} />
            {claim.receipts.length > 0 && (
              <Badge size="small" icon={Paperclip}>
                {t("claim.receipts", { count: claim.receipts.length })}
              </Badge>
            )}
          </>
        }
        onOpen={onOpen}
      />
      {canCancel(claim) && (
        <div className="exp-claim-actions">
          <Button variant="ghost" icon={X} loading={cancel.pending} onClick={() => void cancel.run()}>
            {t("claim.cancel")}
          </Button>
        </div>
      )}
    </div>
  );
}

/**
 * What is owed to me and the company cash I hold. Held cash shows only for people who hold some
 * (or have an account for it); nothing at all for someone with nothing to show yet.
 */
export function WalletSummary({ wallet, hasClaims }: { wallet: UseQueryResult<ClaimWallet>; hasClaims: boolean }) {
  const t = useExpensesT();
  if (wallet.isPending) return <Skeleton height={92} radius="var(--radius-lg)" />;
  // The list matters more than the sums: a summary that didn't load stays out of the way.
  if (!wallet.data) return null;
  const { currency, held, held_total, owed_to_me } = wallet.data;
  const showHeld = Boolean(heldCash(wallet.data)) || held.length > 0;
  if (!hasClaims && !showHeld && !positive(owed_to_me)) return null;
  // Rows, not tiles side by side: a label wraps on a narrow phone, an amount never breaks.
  return (
    <ListCard className="exp-summary">
      <ListRow title={t("summary.owed")} value={<MoneyText amount={owed_to_me} currency={currency} />} />
      {showHeld && (
        <ListRow
          title={t("summary.held")}
          subtitle={held.length > 1 ? held.map((account) => account.name).join(", ") : undefined}
          value={<MoneyText amount={held_total} currency={currency} />}
        />
      )}
    </ListCard>
  );
}

/**
 * A claim's receipts on file. Their links are signed and run out within minutes, so a tap on a
 * list older than a minute asks for it again and opens the fresh link.
 */
export function ReceiptLinks({ claim, refresh, fetchedAt }: { claim: Claim; refresh: () => Promise<Claim | undefined>; fetchedAt: number }) {
  const t = useExpensesT();
  const toast = useToast();
  const { t: appT } = useI18n();
  const [broken, setBroken] = useState<ReadonlySet<number>>(new Set());
  if (!claim.receipts.length) return <p className="ft-hint">{t("detail.noReceipts")}</p>;

  const open = async (receipt: ClaimReceipt) => {
    haptic();
    let url = receipt.url;
    if (Date.now() - fetchedAt > 60_000) {
      try {
        url = (await refresh())?.receipts.find((item) => item.id === receipt.id)?.url ?? url;
      } catch {
        // The old link may still work; opening it is better than nothing.
      }
    }
    if (!openLink(url)) toast(appT("error.generic"), { tone: "error" });
  };
  const kind = (receipt: ClaimReceipt) =>
    receipt.is_image ? t("receipts.image") : isPdf({ type: receipt.content_type, name: receipt.url.split("?")[0] }) ? t("receipts.pdf") : t("receipts.other");

  return (
    <ul className="exp-tiles">
      {claim.receipts.map((receipt, index) => {
        const thumb = receipt.is_image && !broken.has(receipt.id) ? (receipt.thumb_url ?? receipt.url) : null;
        return (
          <li key={receipt.id} className="exp-tile">
            <button type="button" className="exp-tile-open" aria-label={t("receipts.item", { number: index + 1 })} onClick={() => void open(receipt)}>
              {thumb ? (
                <img className="exp-tile-img" src={thumb} alt="" onError={() => setBroken((before) => new Set(before).add(receipt.id))} />
              ) : (
                <span className="exp-tile-file">
                  <FileText size={24} strokeWidth={2.2} aria-hidden />
                  <span>{kind(receipt)}</span>
                </span>
              )}
            </button>
          </li>
        );
      })}
    </ul>
  );
}
