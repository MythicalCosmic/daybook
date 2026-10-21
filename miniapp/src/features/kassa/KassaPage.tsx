import { ArchiveRestore, ArrowRightLeft, Check, EyeOff, HandCoins, History, KeyRound, LockKeyhole, ReceiptText, Store, Undo2, Vault } from "lucide-react";
import { useState } from "react";

import { useI18n } from "../../i18n";
import { errorText } from "../../lib/actions";
import { amountFromTyping, sumMoney, type DecimalString } from "../../lib/money";
import { clock } from "../../lib/time";
import { useNow } from "../../lib/useNow";
import { useNavigation } from "../../state/navigation";
import { useMember } from "../../state/session";
import { useToast } from "../../state/toast";
import { confirm, haptic } from "../../telegram";
import { BottomBar, Button, Card, countedTotal, cx, EmptyState, MoneyText, PageHeader, Screen, ScreenSkeleton, SectionHead, type NoteCounts } from "../../ui";
import type { PageProps } from "../registry";
import { isDenied, useKassa, useOpenShift, useVoidSale, type Kassa, type ShiftDetail } from "./api";
import { duration, minutesBetween, useKassaT, useMoney } from "./lib";
import { CashCount, Denied, ErrorScreen, MovementRow, ShiftRow } from "./parts";
import { ReceivedList } from "./Received";

const LAST_TILL = "daybook.kassa.till";

function lastTill(): number | null {
  try {
    return Number(localStorage.getItem(LAST_TILL)) || null;
  } catch {
    return null;
  }
}

/**
 * The Kassa screen: open a shift (pick the till, count the float), or run the open one
 * (payouts, handovers, the safe, receipts in receipts mode) and go close it.
 */
export default function KassaPage(_: PageProps) {
  const member = useMember();
  const kassa = useKassa(member.companyId);
  if (kassa.isPending) {
    return (
      <Screen variant="detail">
        <ScreenSkeleton variant="detail" delay={150} />
      </Screen>
    );
  }
  if (kassa.isError) {
    return <Screen variant="detail">{isDenied(kassa.error) ? <Denied /> : <ErrorScreen error={kassa.error} retry={() => kassa.refetch()} />}</Screen>;
  }
  return kassa.data.shift ? <ShiftNow kassa={kassa.data} shift={kassa.data.shift} /> : <OpenShift kassa={kassa.data} />;
}

function OpenShift({ kassa }: { kassa: Kassa }) {
  const t = useKassaT();
  const { t: appT } = useI18n();
  const member = useMember();
  const navigation = useNavigation();
  const toast = useToast();
  const currency = kassa.settings.currency;
  const money = useMoney(currency);
  const free = kassa.registers.filter((till) => !till.busy);
  const [tillId, setTillId] = useState<number | null>(() => {
    const remembered = lastTill();
    if (free.some((till) => till.id === remembered)) return remembered;
    return free.length === 1 ? free[0].id : null;
  });
  const [counts, setCounts] = useState<NoteCounts>({});
  const [typed, setTyped] = useState<string | null>(null);
  const open = useOpenShift(member.companyId);
  const amount: DecimalString = typed !== null ? (amountFromTyping(typed) ?? "0") : countedTotal(counts);

  const submit = () => {
    if (!tillId) return;
    open.mutate(
      { register_id: tillId, opening_count: typed === null ? counts : undefined, opening_float: amount },
      {
        onSuccess: () => {
          try {
            localStorage.setItem(LAST_TILL, String(tillId));
          } catch {
            // Only a convenience.
          }
          haptic.notify("success");
          toast(t("open.done"), { tone: "success" });
        },
        onError: (error) => {
          haptic.notify("error");
          toast(errorText(error, appT), { tone: "error" });
        },
      },
    );
  };

  if (!kassa.registers.length) {
    return (
      <Screen variant="detail">
        <PageHeader kicker={t("kassa")} title={t("open.title")} onBack={navigation.pop} />
        <ReceivedList />
        <EmptyState icon={Store} title={t("open.noTills.title")} body={t("open.noTills.body")} />
      </Screen>
    );
  }

  return (
    <>
      <Screen variant="detail">
        <PageHeader kicker={t("kassa")} title={t("open.title")} subtitle={t("open.subtitle")} onBack={navigation.pop} />
        <ReceivedList />
        <SectionHead size="small">{t("open.till")}</SectionHead>
        <div className="kassa-tills" role="radiogroup" aria-label={t("open.till")}>
          {kassa.registers.map((till) => {
            const selected = till.id === tillId;
            return (
              <button
                key={till.id}
                type="button"
                role="radio"
                aria-checked={selected}
                disabled={Boolean(till.busy)}
                className={cx("kassa-till", selected && "is-selected")}
                onClick={() => {
                  haptic.select();
                  setTillId(till.id);
                }}
              >
                <span className="circle kassa-till-icon">
                  <Store size={19} strokeWidth={2.4} aria-hidden />
                </span>
                <span className="row-main">
                  <span className="row-title">{till.name}</span>
                  <span className="row-meta">{till.busy ? t("open.busy", { name: till.busy.cashier, code: till.busy.code }) : till.branch.name}</span>
                </span>
                <span className="kassa-radio" aria-hidden>
                  {selected && <Check size={15} strokeWidth={3.2} />}
                </span>
              </button>
            );
          })}
        </div>
        <SectionHead size="small">{t("open.float")}</SectionHead>
        <p className="kassa-help">{t("open.floatHint")}</p>
        <CashCount counts={counts} onCounts={setCounts} typed={typed} onTyped={setTyped} currency={currency} label={t("open.float")} />
        {kassa.recent.length > 0 && (
          <>
            <SectionHead size="small" action={{ label: t("now.history"), onClick: () => navigation.push({ feature: "kassa", page: "history" }) }}>
              {t("open.recent")}
            </SectionHead>
            {kassa.recent.slice(0, 3).map((shift) => (
              <ShiftRow key={shift.id} shift={shift} currency={currency} />
            ))}
          </>
        )}
      </Screen>
      <BottomBar
        primary={{
          text: tillId ? t("open.submit", { amount: money(amount) }) : t("open.pick"),
          onClick: submit,
          disabled: !tillId,
          loading: open.isPending,
          icon: KeyRound,
          shine: Boolean(tillId),
        }}
      />
    </>
  );
}

function ShiftNow({ kassa, shift }: { kassa: Kassa; shift: ShiftDetail }) {
  const t = useKassaT();
  const { locale } = useI18n();
  const member = useMember();
  const navigation = useNavigation();
  const now = useNow();
  const currency = kassa.settings.currency;
  const money = useMoney(currency);
  const receiptsMode = kassa.settings.mode === "receipts";
  const sheet = (name: string, params?: Record<string, string>) => navigation.openSheet({ kind: "feature", feature: "kassa", sheet: name, params });
  const since = t("now.since", { time: clock(shift.opened_at, member.timeZone, locale), duration: duration(t, minutesBetween(shift.opened_at, now)) });

  const actions = [
    { id: "payout", icon: HandCoins, label: t("action.payout"), hint: t("action.payoutHint"), open: () => sheet("payout") },
    { id: "handover", icon: ArrowRightLeft, label: t("action.handover"), hint: t("action.handoverHint"), open: () => sheet("handover") },
    { id: "to_safe", icon: Vault, label: t("action.toSafe"), hint: t("action.toSafeHint"), open: () => sheet("safe", { direction: "to_safe" }) },
    { id: "from_safe", icon: ArchiveRestore, label: t("action.fromSafe"), hint: t("action.fromSafeHint"), open: () => sheet("safe", { direction: "from_safe" }) },
  ];

  return (
    <>
      <Screen variant="detail">
        <PageHeader
          kicker={`${shift.branch.name} · ${shift.register.name}`}
          title={t("now.title", { code: shift.code })}
          subtitle={<span className="num">{since}</span>}
          onBack={navigation.pop}
        />
        <ReceivedList />
        {receiptsMode ? (
          <SalesSoFar kassa={kassa} shift={shift} />
        ) : (
          <Card className="kassa-blind">
            <span className="circle kassa-blind-icon">
              <EyeOff size={19} strokeWidth={2.4} aria-hidden />
            </span>
            <span className="kassa-blind-text">
              <span className="kassa-blind-title">{t("now.blindTitle")}</span>
              <span className="kassa-blind-body">{t("now.blindBody")}</span>
              <span className="kassa-blind-float num">{t("now.float", { amount: money(shift.opening_float) })}</span>
            </span>
          </Card>
        )}
        <div className="kassa-actions">
          {receiptsMode && (
            <button type="button" className="kassa-action kassa-action--wide" onClick={() => sheet("sale")}>
              <span className="circle kassa-action-icon">
                <ReceiptText size={22} strokeWidth={2.4} aria-hidden />
              </span>
              <span className="kassa-action-text">
                <span className="kassa-action-label">{t("action.sale")}</span>
                <span className="kassa-action-hint">{t("action.saleHint")}</span>
              </span>
            </button>
          )}
          {actions.map((action) => (
            <button key={action.id} type="button" className="kassa-action" onClick={action.open}>
              <span className="circle kassa-action-icon">
                <action.icon size={20} strokeWidth={2.4} aria-hidden />
              </span>
              <span className="kassa-action-label">{action.label}</span>
              <span className="kassa-action-hint">{action.hint}</span>
            </button>
          ))}
        </div>
        <SectionHead count={shift.movements.length}>{t("now.movements")}</SectionHead>
        {shift.movements.length ? (
          shift.movements.map((movement) => <MovementRow key={movement.id} movement={movement} currency={currency} />)
        ) : (
          <p className="kassa-help">{t("now.noMovements")}</p>
        )}
        {receiptsMode && <Entries shift={shift} currency={currency} />}
        <Button className="kassa-history-link" icon={History} onClick={() => navigation.push({ feature: "kassa", page: "history" })}>
          {t("now.history")}
        </Button>
      </Screen>
      <BottomBar
        primary={{
          text: t("now.close"),
          icon: LockKeyhole,
          onClick: () => navigation.push({ feature: "kassa", page: "close", params: { id: shift.id } }),
        }}
      />
    </>
  );
}

/** Receipts mode: what the receipts entered so far add up to, per payment method. */
function SalesSoFar({ kassa, shift }: { kassa: Kassa; shift: ShiftDetail }) {
  const t = useKassaT();
  const currency = kassa.settings.currency;
  const rows = kassa.methods
    .map((method) => ({ method, totals: shift.receipts_recorded[String(method.id)] }))
    .filter((row) => row.totals && (row.totals.sales !== "0.00" || row.totals.refunds !== "0.00"));
  const net = sumMoney(rows.map((row) => sumMoney([row.totals!.sales, `-${row.totals!.refunds}`])));
  const count = rows.reduce((total, row) => total + (row.totals?.receipts ?? 0), 0);
  return (
    <Card className="kassa-sofar">
      <span className="kassa-kicker">{t("now.salesSoFar")}</span>
      <MoneyText amount={net} currency={currency} size="hero" />
      <span className="kassa-sofar-count">{t("now.receipts", { count })}</span>
      {rows.length > 0 && (
        <div className="kassa-sofar-methods">
          {rows.map((row) => (
            <span key={row.method.id} className="kassa-sofar-method">
              <span>{row.method.name}</span>
              <MoneyText amount={sumMoney([row.totals!.sales, `-${row.totals!.refunds}`])} currency={currency} compact />
            </span>
          ))}
        </div>
      )}
    </Card>
  );
}

function Entries({ shift, currency }: { shift: ShiftDetail; currency: string }) {
  const t = useKassaT();
  const { t: appT, locale } = useI18n();
  const member = useMember();
  const toast = useToast();
  const money = useMoney(currency);
  const voidSale = useVoidSale(member.companyId);
  const [busy, setBusy] = useState<number | null>(null);

  const ask = async (id: number, amount: string) => {
    if (!(await confirm(t("now.voidAsk", { amount: money(amount) })))) return;
    setBusy(id);
    voidSale.mutate(
      { id, reason: t("now.voidReason") },
      {
        onSuccess: () => toast(t("now.voided")),
        onError: (error) => toast(errorText(error, appT), { tone: "error" }),
        onSettled: () => setBusy(null),
      },
    );
  };

  return (
    <>
      <SectionHead count={shift.entries.filter((entry) => !entry.voided_at).length}>{t("now.entries")}</SectionHead>
      {shift.entries.length ? (
        <div className="card list-card">
          {shift.entries.map((entry) => (
            <div key={entry.id} className={cx("list-item list-item--two-line kassa-entry", entry.voided_at && "kassa-entry--void")}>
              <span className="list-item-text">
                <span className="num">
                  {entry.kind === "refund" ? "−" : ""}
                  {money(entry.total)}
                </span>
                <span className="list-item-sub num">
                  {clock(entry.sold_at, member.timeZone, locale)} · {entry.methods.map((method) => method.name).join(", ")}
                  {entry.number ? ` · №${entry.number}` : ""}
                </span>
              </span>
              {entry.voided_at ? (
                <span className="kassa-entry-void">{t("move.voided")}</span>
              ) : (
                <button type="button" className="btn btn-ghost kassa-entry-undo" disabled={busy === entry.id} onClick={() => void ask(entry.id, entry.total)}>
                  <Undo2 size={16} strokeWidth={2.6} aria-hidden />
                  <span>{t("now.void")}</span>
                </button>
              )}
            </div>
          ))}
        </div>
      ) : (
        <p className="kassa-help">{t("now.noEntries")}</p>
      )}
    </>
  );
}
