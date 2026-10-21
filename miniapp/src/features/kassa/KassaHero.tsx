import { ArrowRightLeft, ChevronRight, HandCoins, Hourglass, LockKeyhole, ReceiptText, Store } from "lucide-react";

import { can } from "../../api/permissions";
import { useI18n } from "../../i18n";
import { subtractMoney, sumMoney } from "../../lib/money";
import { clock } from "../../lib/time";
import { useNow } from "../../lib/useNow";
import { useNavigation } from "../../state/navigation";
import { Button, Card, CardButton, Dot, Skeleton } from "../../ui";
import type { SlotProps } from "../registry";
import { useKassa } from "./api";
import { duration, minutesBetween, useKassaT, useMoney } from "./lib";
import "./kassa.css";

/**
 * Home's top card for a cashier: "Kassa is closed · Open shift", or the open shift with its
 * three everyday actions. Nothing at all for someone without a till in their branch.
 */
export function KassaHero({ member }: SlotProps) {
  const t = useKassaT();
  const { locale } = useI18n();
  const navigation = useNavigation();
  const kassa = useKassa(member.companyId);
  const now = useNow(60_000);
  const money = useMoney(kassa.data?.settings.currency ?? "UZS");

  if (kassa.isPending) return <Skeleton height={132} radius="var(--radius-md)" />;
  const data = kassa.data;
  if (!data || (!data.shift && !data.registers.length)) return null;
  const openKassa = () => navigation.push({ feature: "kassa", page: "home" });
  const sheet = (name: string) => navigation.openSheet({ kind: "feature", feature: "kassa", sheet: name });
  const shift = data.shift;

  if (!shift) {
    // Owners and managers (who have the dashboard) see the closed till only once they ran one.
    if (!data.recent.length && can(member, "dashboard.access")) return null;
    const branch = data.registers.find((till) => !till.busy)?.branch.name ?? data.registers[0]?.branch.name;
    return (
      <CardButton className="kassa-hero kassa-hero--closed" onClick={openKassa}>
        <span className="circle kassa-hero-icon">
          <Store size={22} strokeWidth={2.4} aria-hidden />
        </span>
        <span className="row-main">
          {branch && <span className="kassa-kicker">{branch}</span>}
          <span className="kassa-hero-title">{t("hero.closedTitle")}</span>
          <span className="row-meta">{t("hero.closedBody")}</span>
        </span>
        <span className="btn btn-primary kassa-hero-cta">{t("hero.open")}</span>
      </CardButton>
    );
  }

  const receiptsMode = data.settings.mode === "receipts";
  const waiting = shift.movements.filter((movement) => movement.kind === "handover" && movement.status === "pending");
  // Net of refunds, like the close will count it.
  const rows = Object.values(shift.receipts_recorded);
  const recorded = subtractMoney(sumMoney(rows.map((row) => row.sales)), sumMoney(rows.map((row) => row.refunds)));
  return (
    <Card tone="sage" className="kassa-hero kassa-hero--open">
      <button type="button" className="kassa-hero-main" onClick={openKassa}>
        <span className="kassa-hero-text">
          <span className="kassa-live">
            <Dot tone="sage" pulse />
            {t("hero.live")} · {shift.code}
          </span>
          <span className="heading kassa-hero-name">{shift.register.name}</span>
          <span className="kassa-hero-meta num">
            {receiptsMode
              ? t("hero.salesSoFar", { amount: money(recorded, { compact: true }) })
              : t("hero.since", { time: clock(shift.opened_at, member.timeZone, locale), duration: duration(t, minutesBetween(shift.opened_at, now)) })}
          </span>
        </span>
        <ChevronRight size={22} strokeWidth={2.5} aria-hidden />
      </button>
      {waiting.length > 0 && (
        <div className="kassa-hero-note">
          <Hourglass size={15} strokeWidth={2.6} aria-hidden />
          <span>{t("hero.waiting", { name: waiting[0].receiver?.name ?? "", amount: money(waiting[0].amount) })}</span>
        </div>
      )}
      <div className="kassa-hero-actions">
        {receiptsMode ? (
          <Button icon={ReceiptText} onClick={() => sheet("sale")} haptic="light">
            {t("action.sale")}
          </Button>
        ) : (
          <Button icon={ArrowRightLeft} onClick={() => sheet("handover")} haptic="light">
            {t("action.handover")}
          </Button>
        )}
        <Button icon={HandCoins} onClick={() => sheet("payout")} haptic="light">
          {t("action.payout")}
        </Button>
        <Button
          variant="primary"
          icon={LockKeyhole}
          onClick={() => navigation.push({ feature: "kassa", page: "close", params: { id: shift.id } })}
          haptic="light"
        >
          {t("hero.close")}
        </Button>
      </div>
    </Card>
  );
}
