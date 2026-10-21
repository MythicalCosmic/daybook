import { CircleAlert, Hourglass, Image as ImageIcon, MessageSquareText, ShieldCheck, Store } from "lucide-react";

import { useI18n } from "../../i18n";
import { compareMoney, isZero, subtractMoney, sumMoney } from "../../lib/money";
import { clock, dayMonth, weekdayLong } from "../../lib/time";
import { useNavigation } from "../../state/navigation";
import { useMember } from "../../state/session";
import { openLink } from "../../telegram";
import { Banner, Card, CardTitle, PageHeader, Screen, ScreenSkeleton, SectionHead } from "../../ui";
import type { PageProps } from "../registry";
import { isDenied, useKassa, useShift, type ShiftDetail } from "./api";
import { useKassaT, useMoney } from "./lib";
import { Denied, ErrorScreen, Line, Lines, MovementRow, ShiftBadge } from "./parts";

/** One of my shifts: how it ended (once checked), the sales, the cash, the moves and photos. */
export default function ShiftPage({ params }: PageProps) {
  const member = useMember();
  const shift = useShift(member.companyId, Number(params.id));
  const kassa = useKassa(member.companyId);
  if (shift.isPending) {
    return (
      <Screen variant="detail">
        <ScreenSkeleton variant="detail" delay={150} />
      </Screen>
    );
  }
  if (shift.isError) {
    return <Screen variant="detail">{isDenied(shift.error) ? <Denied /> : <ErrorScreen error={shift.error} retry={() => shift.refetch()} />}</Screen>;
  }
  return <Detail shift={shift.data} currency={kassa.data?.settings.currency ?? "UZS"} />;
}

function Detail({ shift, currency }: { shift: ShiftDetail; currency: string }) {
  const t = useKassaT();
  const { locale } = useI18n();
  const { timeZone } = useMember();
  const navigation = useNavigation();
  const money = useMoney(currency);
  const day = new Date(`${shift.business_day}T12:00:00Z`);
  const hours = shift.closed_at
    ? `${clock(shift.opened_at, timeZone, locale)}–${clock(shift.closed_at, timeZone, locale)}`
    : t("time.since", { time: clock(shift.opened_at, timeZone, locale) });
  const net = sumMoney(shift.payments.map((line) => subtractMoney(line.sales, line.refunds)));
  const photos = [
    { key: "z", label: t("close.zPhoto"), url: shift.photos.z_photo },
    { key: "terminal", label: t("close.terminalPhoto"), url: shift.photos.terminal_photo },
  ].filter((photo) => photo.url);

  return (
    <Screen variant="detail">
      <PageHeader
        kicker={`${shift.branch.name} · ${shift.register.name}`}
        title={shift.code}
        subtitle={
          <span className="num">
            {weekdayLong(day, "UTC", locale)}, {dayMonth(day, "UTC", locale)} · {hours}
          </span>
        }
        actions={<ShiftBadge shift={shift} currency={currency} />}
        onBack={navigation.pop}
      />
      <Outcome shift={shift} money={money} />
      <Card>
        <CardTitle>{t("shift.sales")}</CardTitle>
        <Lines>
          {shift.payments
            .filter((line) => !isZero(line.sales) || !isZero(line.refunds))
            .map((line) => (
              <Line key={line.method.id} label={line.method.name}>
                {money(subtractMoney(line.sales, line.refunds))}
              </Line>
            ))}
          <Line label={t("close.net")} strong>
            {money(net)}
          </Line>
          <Line label={t("shift.receiptsCount")}>{shift.receipts}</Line>
          {shift.z_number && <Line label={t("shift.zNumber")}>№ {shift.z_number}</Line>}
        </Lines>
      </Card>
      <Card>
        <CardTitle>{t("shift.cash")}</CardTitle>
        <Lines>
          <Line label={t("shift.float")}>{money(shift.opening_float)}</Line>
          {Object.entries(shift.moved).map(([kind, amount]) => (
            <Line key={kind} label={t(`moved.${kind}` as Parameters<typeof t>[0])}>
              {kind === "from_safe" || kind === "deposit" ? "+" : "−"}
              {money(amount)}
            </Line>
          ))}
          {shift.counted_cash !== null && (
            <Line label={t("shift.counted")} strong>
              {money(shift.counted_cash)}
            </Line>
          )}
          {shift.expected_cash !== null && <Line label={t("shift.expected")}>{money(shift.expected_cash)}</Line>}
        </Lines>
      </Card>
      {shift.movements.length > 0 && (
        <>
          <SectionHead count={shift.movements.length}>{t("now.movements")}</SectionHead>
          {shift.movements.map((movement) => (
            <MovementRow key={movement.id} movement={movement} currency={currency} />
          ))}
        </>
      )}
      {photos.length > 0 && (
        <>
          <SectionHead>{t("shift.photos")}</SectionHead>
          <div className="kassa-gallery">
            {photos.map((photo) => (
              <button key={photo.key} type="button" className="kassa-gallery-item" onClick={() => openLink(photo.url!)}>
                <img src={photo.url!} alt="" loading="lazy" />
                <span>
                  <ImageIcon size={14} strokeWidth={2.6} aria-hidden />
                  {photo.label}
                </span>
              </button>
            ))}
          </div>
        </>
      )}
      {shift.cashier_note && <Banner icon={MessageSquareText} title={t("shift.yourNote")} body={shift.cashier_note} />}
    </Screen>
  );
}

/** The verdict: open, waiting for a check, questioned, or checked with its difference. */
function Outcome({ shift, money }: { shift: ShiftDetail; money: (amount: string | null) => string }) {
  const t = useKassaT();
  const { locale } = useI18n();
  const { timeZone } = useMember();
  const navigation = useNavigation();
  if (shift.status === "open") {
    return (
      <Banner
        tone="sage"
        size="lg"
        icon={Store}
        title={t("shift.openTitle")}
        body={t("shift.openBody")}
        onClick={() => navigation.push({ feature: "kassa", page: "home" })}
      />
    );
  }
  if (shift.status === "disputed") {
    return <Banner tone="accent" icon={CircleAlert} title={t("shift.disputedTitle")} body={shift.note || t("shift.disputedBody")} />;
  }
  const difference = shift.difference;
  if (difference === null) return <Banner icon={Hourglass} title={t("shift.waitingTitle")} body={t("shift.waitingBody")} />;
  const checked =
    shift.status === "verified" && shift.verified_by
      ? t("shift.checkedBy", { name: shift.verified_by.name, date: shift.verified_at ? dayMonth(shift.verified_at, timeZone, locale) : "" })
      : t("shift.notChecked");
  const body = [checked, shift.note].filter(Boolean).join(" · ");
  if (isZero(difference)) return <Banner tone="sage" icon={ShieldCheck} title={t("result.exact")} body={body} />;
  const short = compareMoney(difference, "0") < 0;
  return (
    <Banner
      tone={short ? "accent" : "plain"}
      icon={CircleAlert}
      title={short ? t("result.short", { amount: money(difference.replace(/^-/, "")) }) : t("result.over", { amount: money(difference) })}
      body={body}
    />
  );
}
