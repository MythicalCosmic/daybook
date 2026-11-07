/** Pieces the stock screens share: badges, money, packs-and-parts input, shaped skeletons. */
import { Ban, FileText, ShieldAlert, Snowflake } from "lucide-react";
import { useEffect, useState } from "react";

import { baseCurrency } from "../../api/membership";
import { useI18n } from "../../i18n";
import { formatMoney } from "../../lib/money";
import { useMember } from "../../state/session";
import { Badge, Skeleton, Stepper, useDelay } from "../../ui";
import type { BatchStatus, ControlClass, StorageKind } from "./api";
import { isCold, isControlled, packDate, partsOf, splitParts } from "./lib";
import { type StockT, useStockT } from "./text";

/** `value` once typing pauses for `ms`, so each key press doesn't ask the server. */
export function useSettled(value: string, ms: number): string {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    if (ms <= 0) {
      setSettled(value);
      return;
    }
    const timer = window.setTimeout(() => setSettled(value), ms);
    return () => window.clearTimeout(timer);
  }, [value, ms]);
  return ms <= 0 ? value : settled;
}

/** Money in the company's base currency, in the person's language. */
export function useMoney(): (amount: string | null | undefined) => string {
  const member = useMember();
  const { lang } = useI18n();
  const currency = baseCurrency(member);
  return (amount) => formatMoney(amount, currency, lang);
}

/** Prescription only, cold chain, controlled: what the pharmacist must see before anything else. */
export function ProductBadges({ rx, storage, control }: { rx: boolean; storage: StorageKind; control: ControlClass }) {
  const t = useStockT();
  if (!rx && !isCold(storage) && !isControlled(control)) return null;
  return (
    <span className="stk-badges">
      {rx && (
        <Badge tone="accent" size="small" icon={FileText}>
          {t("badge.rx")}
        </Badge>
      )}
      {isCold(storage) && (
        <Badge tone="sage" size="small" icon={Snowflake}>
          {t(storage === "frozen" ? "badge.frozen" : "badge.cold")}
        </Badge>
      )}
      {isControlled(control) && (
        <Badge tone="accent" size="small" icon={ShieldAlert}>
          {t("badge.controlled")}
        </Badge>
      )}
    </span>
  );
}

/** A batch that can't be sold: expired, in quarantine or recalled. */
export function BatchState({ expired, status }: { expired: boolean; status: BatchStatus }) {
  const t = useStockT();
  if (expired)
    return (
      <Badge tone="accent" size="small" icon={Ban}>
        {t("badge.expired")}
      </Badge>
    );
  if (status === "quarantine") return <Badge size="small">{t("badge.quarantine")}</Badge>;
  if (status === "recalled")
    return (
      <Badge tone="accent" size="small">
        {t("badge.recalled")}
      </Badge>
    );
  return null;
}

/** "expires 31.12.2026 · 45 days left", or "expired 30.09.2026". */
export function expiryLine(t: StockT, day: string, daysLeft: number): string {
  if (daysLeft < 0) return t("product.expiredOn", { day: packDate(day) });
  return `${t("product.expires", { day: packDate(day) })} · ${t("product.daysLeft", { count: daysLeft })}`;
}

const FORMS = [
  "tablet",
  "capsule",
  "syrup",
  "suspension",
  "solution",
  "injection",
  "powder",
  "ointment",
  "cream",
  "gel",
  "eye_drops",
  "ear_drops",
  "nasal",
  "spray",
  "suppository",
  "patch",
  "other",
] as const;

/** "Kapsula · 500 mg": the catalogue's dosage form in words, and the strength. */
export function formLine(t: StockT, form: string | undefined, strength: string | undefined): string {
  const known = (FORMS as readonly string[]).includes(form ?? "") ? t(`form.${form as (typeof FORMS)[number]}`) : "";
  return [known, (strength ?? "").trim()].filter(Boolean).join(" · ");
}

/** What a part is called: the catalogue's word ("blister", "ampula"), else "part". */
export function partWord(t: StockT, label: string): string {
  return label.trim() || t("part.generic");
}

/**
 * A quantity typed as people count it: whole packs, and the loose parts when a pack has more
 * than one. `value` and `max` are in parts.
 */
export function QtyInput({
  value,
  onChange,
  unitsPerPack,
  partLabel,
  max,
  label,
}: {
  value: number;
  onChange: (parts: number) => void;
  unitsPerPack: number;
  partLabel: string;
  max?: number;
  label: string;
}) {
  const t = useStockT();
  const per = Math.max(1, Math.floor(unitsPerPack || 1));
  const { packs, parts } = splitParts(value, per);
  const limit = max ?? 99_999;
  const set = (nextPacks: number, nextParts: number) => onChange(Math.min(limit, Math.max(0, partsOf(nextPacks, nextParts, per))));
  return (
    <div className="stk-qty-input" role="group" aria-label={label}>
      <span className="stk-qty-field">
        <span className="stk-qty-label">{t("transfer.packs")}</span>
        <Stepper size="sm" editable value={packs} min={0} max={Math.floor(limit / per)} onChange={(next) => set(next, parts)} label={`${label}: ${t("transfer.packs")}`} />
      </span>
      {per > 1 && (
        <span className="stk-qty-field">
          <span className="stk-qty-label">{t("transfer.loose", { label: partWord(t, partLabel) })}</span>
          <Stepper size="sm" editable value={parts} min={0} max={per - 1} onChange={(next) => set(packs, next)} label={`${label}: ${partWord(t, partLabel)}`} />
        </span>
      )}
    </div>
  );
}

/** Rows shaped like the lookup's results: a title with a price, two lines, the badges. */
export function RowsSkeleton({ rows = 4, delay = 150 }: { rows?: number; delay?: number }) {
  const ready = useDelay(delay);
  if (!ready) return null;
  return (
    <div className="stk-list" aria-hidden>
      {Array.from({ length: rows }, (_, index) => (
        <div key={index} className="stk-skel-row">
          <span className="stk-skel-head">
            <Skeleton height={16} width="58%" radius={8} />
            <Skeleton height={16} width="22%" radius={8} />
          </span>
          <Skeleton height={13} width="44%" radius={7} />
          <Skeleton height={13} width="66%" radius={7} />
        </div>
      ))}
    </div>
  );
}

/** A product page loading: the badges, the price card, a list of batches. */
export function ProductSkeleton() {
  const ready = useDelay(150);
  if (!ready) return null;
  return (
    <div className="stk-stack" aria-hidden>
      <span className="stk-skel-head">
        <Skeleton height={22} width="28%" radius={11} />
        <Skeleton height={22} width="24%" radius={11} />
      </span>
      <Skeleton height={132} />
      <Skeleton height={18} width="40%" radius={8} />
      <Skeleton height={150} />
    </div>
  );
}

/** The expiry check loading: the group switch, then cards with their two buttons. */
export function ExpirySkeleton() {
  const ready = useDelay(150);
  if (!ready) return null;
  return (
    <div className="stk-stack" aria-hidden>
      <Skeleton height={44} radius={22} />
      {Array.from({ length: 3 }, (_, index) => (
        <div key={index} className="stk-skel-card">
          <Skeleton height={16} width="62%" radius={8} />
          <Skeleton height={13} width="48%" radius={7} />
          <span className="stk-skel-head">
            <Skeleton height={40} width="56%" radius={20} />
            <Skeleton height={40} width="38%" radius={20} />
          </span>
        </div>
      ))}
    </div>
  );
}
