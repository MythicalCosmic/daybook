/** Pieces the Kassa pages and sheets share. */
import { ChevronRight, Keyboard, KeyRound, ListOrdered, Lock, RotateCw, Store, TriangleAlert } from "lucide-react";
import type { ReactNode } from "react";

import { useI18n } from "../../i18n";
import { errorText } from "../../lib/actions";
import { clock, weekdayShort } from "../../lib/time";
import { useNavigation } from "../../state/navigation";
import { useMember } from "../../state/session";
import { openLink } from "../../telegram";
import { Badge, Button, cx, DenominationCounter, EmptyState, NumberPad, type NoteCounts } from "../../ui";
import type { Movement, Shift } from "./api";
import { leavesTill, MOVEMENT_ICON, movementMeta, movementTitle, shiftLook, useKassaT, useMoney } from "./lib";

/**
 * Count cash note by note (the float, the blind count), or type the total when a counting
 * machine did the work. `typed` is null while counting notes.
 */
export function CashCount({
  counts,
  onCounts,
  typed,
  onTyped,
  currency,
  label,
}: {
  counts: NoteCounts;
  onCounts: (counts: NoteCounts) => void;
  typed: string | null;
  onTyped: (typed: string | null) => void;
  currency: string;
  label: ReactNode;
}) {
  const t = useKassaT();
  const typing = typed !== null;
  return (
    <div className="kassa-count">
      {typing ? (
        <NumberPad value={typed} onChange={onTyped} currency={currency} label={label} />
      ) : (
        <DenominationCounter counts={counts} onChange={onCounts} currency={currency} stickyTotal />
      )}
      <Button variant="ghost" icon={typing ? ListOrdered : Keyboard} className="kassa-count-switch" onClick={() => onTyped(typing ? null : "")}>
        {typing ? t("count.byNotes") : t("count.typeTotal")}
      </Button>
    </div>
  );
}

/** One payout, handover or safe move: icon, what, when and where it stands, amount. */
export function MovementRow({ movement, currency }: { movement: Movement; currency: string }) {
  const t = useKassaT();
  const { locale } = useI18n();
  const { timeZone } = useMember();
  const money = useMoney(currency);
  const Icon = MOVEMENT_ICON[movement.kind];
  const meta = movementMeta(movement, t, timeZone, locale);
  const voided = movement.status === "void";
  return (
    <div className={cx("row row--static kassa-move", voided && "kassa-move--void")}>
      <span className={cx("circle ui-row-icon", movement.status === "pending" || movement.status === "declined" ? "ui-row-icon--accent" : "ui-row-icon--sage")}>
        <Icon size={19} strokeWidth={2.4} aria-hidden />
      </span>
      <span className="row-main">
        <span className="kassa-move-top">
          <span className="row-title">{movementTitle(movement, t)}</span>
          <span className="kassa-move-amount num">
            {leavesTill(movement.kind) ? "−" : "+"}
            {money(movement.amount, { sign: "never" })}
          </span>
        </span>
        <span className={cx("row-meta row-meta--wrap", meta.alert && "row-meta--alert")}>{meta.text}</span>
      </span>
      {movement.photo && (
        <button type="button" className="kassa-thumb" aria-label={t("move.photo")} onClick={() => openLink(movement.photo!)}>
          <img src={movement.photo} alt="" loading="lazy" />
        </button>
      )}
    </div>
  );
}

/** The cashier's view of a shift's state, as a pill. */
export function ShiftBadge({ shift, currency }: { shift: Shift; currency: string }) {
  const t = useKassaT();
  const money = useMoney(currency);
  const look = shiftLook(shift, t, (amount) => money(amount));
  return (
    <Badge tone={look.tone} size="small">
      {look.label}
    </Badge>
  );
}

/** A shift in a list: the day, the till, the sales and how it ended. */
export function ShiftRow({ shift, currency }: { shift: Shift; currency: string }) {
  const { locale } = useI18n();
  const { timeZone } = useMember();
  const navigation = useNavigation();
  const money = useMoney(currency);
  const day = new Date(`${shift.business_day}T12:00:00Z`);
  return (
    <button type="button" className="row kassa-shift-row" onClick={() => navigation.push({ feature: "kassa", page: "shift", params: { id: shift.id } })}>
      <span className="kassa-day" aria-hidden>
        <span className="kassa-day-num num">{day.getUTCDate()}</span>
        <span className="kassa-day-week">{weekdayShort(day, "UTC", locale)}</span>
      </span>
      <span className="row-main">
        <span className="row-title num">
          {shift.code} · {shift.register.name}
        </span>
        <span className="row-meta num">
          {money(shift.net, { compact: true })}
          {shift.closed_at ? ` · ${clock(shift.opened_at, timeZone, locale)}–${clock(shift.closed_at, timeZone, locale)}` : ""}
        </span>
      </span>
      <ShiftBadge shift={shift} currency={currency} />
      <ChevronRight className="ui-row-chevron" size={19} strokeWidth={2.5} aria-hidden />
    </button>
  );
}

/** Label/value lines inside a card. */
export function Lines({ children, className }: { children: ReactNode; className?: string }) {
  return <dl className={cx("kassa-lines", className)}>{children}</dl>;
}

export function Line({ label, children, strong = false, tone }: { label: ReactNode; children: ReactNode; strong?: boolean; tone?: "accent" | "sage" }) {
  return (
    <div className={cx("kassa-line", strong && "kassa-line--strong", tone && `kassa-line--${tone}`)}>
      <dt>{label}</dt>
      <dd className="num">{children}</dd>
    </div>
  );
}

/** A payout or handover asked for without an open shift. */
export function NoShift({ onDone }: { onDone: () => void }) {
  const t = useKassaT();
  const navigation = useNavigation();
  return (
    <EmptyState
      compact
      icon={KeyRound}
      title={t("noShift.title")}
      body={t("noShift.body")}
      action={{
        label: t("noShift.open"),
        icon: Store,
        onClick: () => {
          onDone();
          navigation.push({ feature: "kassa", page: "home" });
        },
      }}
    />
  );
}

/** The till isn't this person's (no permission, or the module went off). */
export function Denied({ compact = false }: { compact?: boolean }) {
  const t = useKassaT();
  return <EmptyState compact={compact} icon={Lock} tone="sage" title={t("denied.title")} body={t("denied.body")} />;
}

/** Something failed to load: say so and offer a retry. */
export function ErrorScreen({ error, retry, compact = false }: { error: unknown; retry: () => void; compact?: boolean }) {
  const t = useKassaT();
  const { t: appT } = useI18n();
  return (
    <EmptyState
      compact={compact}
      icon={TriangleAlert}
      title={t("error.title")}
      body={errorText(error, appT)}
      action={{ label: appT("common.retry"), icon: RotateCw, onClick: retry }}
    />
  );
}
