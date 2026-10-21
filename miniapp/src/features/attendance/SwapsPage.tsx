/**
 * "Swaps": what waits for me (colleagues asking me to cover or swap, open shifts I may take) and
 * my own requests with where they stand. Accepting, declining, taking and cancelling happen in place.
 */
import { CalendarPlus, Check, Inbox, Repeat2, X } from "lucide-react";
import { useState } from "react";

import { useI18n } from "../../i18n";
import { errorText } from "../../lib/actions";
import { useNavigation } from "../../state/navigation";
import { useMember } from "../../state/session";
import { haptic } from "../../telegram";
import { Avatar, Badge, Button, Card, EmptyState, PageHeader, Screen, SectionHead, Segmented, SkeletonList, useToast } from "../../ui";
import { useClaim, useOpenShifts, useSwapAction, useSwaps } from "./api";
import { shiftDay, shiftLine } from "./lib";
import { swapStatusLabel, usePageT } from "./pageText";
import type { OpenShift, Shift, Swap } from "./types";
import "./attendance.css";

type Tab = "forMe" | "mine";

export default function SwapsPage() {
  const t = usePageT();
  const member = useMember();
  const navigation = useNavigation();
  const swaps = useSwaps(member.companyId);
  const open = useOpenShifts(member.companyId);
  const waiting = (swaps.data?.requests.length ?? 0) + (open.data?.filter((shift) => !shift.claimed).length ?? 0);
  const [tab, setTab] = useState<Tab>("forMe");

  const loading = swaps.isPending || (tab === "forMe" && open.isPending);
  const failed = swaps.isError || (tab === "forMe" && open.isError);

  return (
    <Screen variant="detail">
      <PageHeader kicker={t("me.attendance")} title={t("swaps.title")} onBack={navigation.pop} />
      <Segmented
        fit
        role="tablist"
        label={t("swaps.title")}
        value={tab}
        onChange={(next) => {
          haptic.select();
          setTab(next);
        }}
        options={[
          { value: "forMe", label: t("swaps.forMe"), count: waiting || undefined },
          { value: "mine", label: t("swaps.mine") },
        ]}
      />
      {loading ? (
        <SkeletonList count={3} height={150} />
      ) : failed ? (
        <EmptyState
          title={t("ui.failed.title")}
          body={t("ui.failed.body")}
          action={{
            label: t("common.retry"),
            onClick: () => {
              void swaps.refetch();
              void open.refetch();
            },
          }}
        />
      ) : tab === "forMe" ? (
        <ForMe requests={swaps.data?.requests ?? []} openShifts={open.data ?? []} />
      ) : (
        <Mine swaps={swaps.data?.mine ?? []} memberId={member.id} onShifts={() => navigation.push({ feature: "attendance", page: "shifts" })} />
      )}
    </Screen>
  );
}

function useShiftText() {
  const { locale } = useI18n();
  const member = useMember();
  return (shift: Shift) => ({ day: shiftDay(shift, member.timeZone, locale), line: shiftLine(shift) });
}

function ForMe({ requests, openShifts }: { requests: Swap[]; openShifts: OpenShift[] }) {
  const t = usePageT();
  if (!requests.length && !openShifts.length) {
    return <EmptyState icon={Inbox} tone="sage" title={t("forMe.empty")} body={t("forMe.emptyBody")} />;
  }
  return (
    <>
      {requests.length > 0 && (
        <>
          <SectionHead count={requests.length}>{t("swaps.requests")}</SectionHead>
          {requests.map((swap) => (
            <RequestCard key={swap.id} swap={swap} />
          ))}
        </>
      )}
      {openShifts.length > 0 && (
        <>
          <SectionHead count={openShifts.length}>{t("open.title")}</SectionHead>
          {openShifts.map((shift) => (
            <OpenShiftCard key={shift.id} shift={shift} />
          ))}
        </>
      )}
    </>
  );
}

function RequestCard({ swap }: { swap: Swap }) {
  const t = usePageT();
  const member = useMember();
  const toast = useToast();
  const text = useShiftText();
  const action = useSwapAction(member.companyId);
  const [busy, setBusy] = useState<"accept" | "decline" | null>(null);

  const answer = (verb: "accept" | "decline") => {
    setBusy(verb);
    action.mutate(
      { id: swap.id, verb },
      {
        onSuccess: (result) => {
          haptic.notify(verb === "accept" ? "success" : "warning");
          toast(verb === "decline" ? t("swap.declinedToast") : result.status === "approved" ? t("swap.approvedToast") : t("swap.acceptedToast"));
        },
        onError: (error) => {
          haptic.notify("error");
          toast(errorText(error, t));
        },
        onSettled: () => setBusy(null),
      },
    );
  };

  const theirs = text(swap.shift);
  const mine = swap.other_shift ? text(swap.other_shift) : null;
  return (
    <Card className="att-swap">
      <div className="att-swap-head">
        <Avatar name={swap.requested_by.name} size="md" />
        <span className="att-swap-title">{t(swap.kind === "swap" ? "swap.swapAsk" : "swap.coverAsk", { name: swap.requested_by.name })}</span>
      </div>
      <ul className="att-swap-lines">
        <li>{t("swap.theirShift", theirs)}</li>
        {mine && <li>{t("swap.yourShift", mine)}</li>}
      </ul>
      {swap.note && <p className="att-swap-note">{swap.note}</p>}
      <div className="att-swap-actions">
        <Button variant="primary" icon={Check} loading={busy === "accept"} disabled={busy !== null} onClick={() => answer("accept")}>
          {t("swap.accept")}
        </Button>
        <Button icon={X} loading={busy === "decline"} disabled={busy !== null} onClick={() => answer("decline")}>
          {t("swap.decline")}
        </Button>
      </div>
    </Card>
  );
}

function OpenShiftCard({ shift }: { shift: OpenShift }) {
  const t = usePageT();
  const member = useMember();
  const toast = useToast();
  const text = useShiftText();
  const claim = useClaim(member.companyId);
  const { day, line } = text(shift);
  return (
    <Card className="att-swap">
      <div className="att-swap-head">
        <span className="att-swap-title">{day}</span>
        {shift.claimed && (
          <Badge tone="sage" size="small">
            {t("open.claimed")}
          </Badge>
        )}
      </div>
      <ul className="att-swap-lines">
        <li>{line}</li>
        {shift.position && <li>{shift.position.name}</li>}
      </ul>
      {shift.note && <p className="att-swap-note">{shift.note}</p>}
      {!shift.claimed && (
        <Button
          variant="primary"
          block
          icon={CalendarPlus}
          loading={claim.isPending}
          onClick={() =>
            claim.mutate(shift.id, {
              onSuccess: (result) => {
                haptic.notify("success");
                toast(result.status === "approved" ? t("swap.approvedToast") : t("open.claimedToast"));
              },
              onError: (error) => {
                haptic.notify("error");
                toast(errorText(error, t));
              },
            })
          }
        >
          {t("open.claim")}
        </Button>
      )}
    </Card>
  );
}

function Mine({ swaps, memberId, onShifts }: { swaps: Swap[]; memberId: number; onShifts: () => void }) {
  const t = usePageT();
  if (!swaps.length) {
    return <EmptyState icon={Repeat2} tone="sage" title={t("mine.empty")} body={t("mine.emptyBody")} action={{ label: t("link.shifts"), onClick: onShifts }} />;
  }
  return (
    <>
      {swaps.map((swap) => (
        <MineCard key={swap.id} swap={swap} mine={swap.requested_by.id === memberId} />
      ))}
    </>
  );
}

function MineCard({ swap, mine }: { swap: Swap; mine: boolean }) {
  const t = usePageT();
  const member = useMember();
  const toast = useToast();
  const text = useShiftText();
  const action = useSwapAction(member.companyId);
  const titleKey = swap.kind === "claim" ? "mine.claim" : swap.kind === "swap" ? "mine.swap" : "mine.cover";
  // A claim is my own: whoever "accepted" it is me.
  const who =
    swap.kind === "claim"
      ? null
      : swap.accepted_by
        ? t("mine.acceptedBy", { name: swap.accepted_by.name })
        : swap.target
        ? t("mine.to", { name: swap.target.name })
        : t("mine.anyone");
  const live = swap.status === "requested" || swap.status === "accepted";
  const tone = swap.status === "approved" ? "sage" : live ? "accent" : "neutral";
  return (
    <Card className="att-swap">
      <div className="att-swap-head">
        <span className="att-swap-title">{t(titleKey, text(swap.shift))}</span>
      </div>
      {(swap.other_shift || who || swap.decision_note) && (
        <ul className="att-swap-lines">
          {swap.other_shift && <li>{t("swap.theirShift", text(swap.other_shift))}</li>}
          {who && <li>{who}</li>}
          {swap.decision_note && <li>{swap.decision_note}</li>}
        </ul>
      )}
      <div className="att-swap-head">
        <Badge tone={tone} size="small">
          {swapStatusLabel(t, swap.status)}
        </Badge>
        <span className="att-spacer" />
        {mine && live && (
          <Button
            variant="ghost"
            loading={action.isPending}
            onClick={() =>
              action.mutate(
                { id: swap.id, verb: "cancel" },
                {
                  onSuccess: () => toast(t("swap.cancelledToast")),
                  onError: (error) => toast(errorText(error, t)),
                },
              )
            }
          >
            {t("swap.cancel")}
          </Button>
        )}
      </div>
    </Card>
  );
}
