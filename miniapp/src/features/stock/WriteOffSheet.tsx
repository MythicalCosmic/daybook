/**
 * "Propose write-off" from the expiry check: all of the series here, the reason and a photo of
 * the packs. The sheet closes at once and the row says "Sending…", then "Write-off proposed";
 * if the server refuses, the row goes back and its reason shows. The head approves it.
 */
import { Trash2 } from "lucide-react";
import { useState } from "react";

import { useDraftGuard } from "../../lib/useDraftGuard";
import { useMember } from "../../state/session";
import { Button, ChipGroup, Field, PhotoInput, SheetTitle } from "../../ui";
import type { SheetProps } from "../registry";
import { SheetMissing, useFeedback } from "../states";
import { useExpiry, useProposeWriteOff, type AppBatch, type WriteOffReason } from "./api";
import { packDate, qtyText } from "./lib";
import { useStockT } from "./text";
import "./stock.css";

/** The reasons the expiry check offers (shortage and internal use are the head's, in the dashboard). */
type ShownReason = Extract<WriteOffReason, "expired" | "damaged" | "quality" | "recall" | "other">;

/** What a batch can be written off for here: expired goods only as expired. */
export function reasonsFor(row: Pick<AppBatch, "days_left" | "status">): ShownReason[] {
  if (row.days_left < 0) return ["expired"];
  if (row.status === "recalled") return ["recall", "quality", "other"];
  return ["damaged", "quality", "other"];
}

export default function WriteOffSheet({ params, close }: SheetProps) {
  const member = useMember();
  const within = Number(params.within) || 90;
  const expiry = useExpiry(member.companyId, within);
  const row = expiry.data?.find((item) => item.id === Number(params.id));
  if (!row) return <SheetMissing pending={expiry.isPending} error={expiry.error} onRetry={() => void expiry.refetch()} />;
  return <Form row={row} close={close} />;
}

function Form({ row, close }: { row: AppBatch; close: () => void }) {
  const t = useStockT();
  const member = useMember();
  const feedback = useFeedback();
  const propose = useProposeWriteOff(member.companyId, { onFailed: feedback.fail, onDone: () => feedback.ok(t("writeoff.done")) });
  const reasons = reasonsFor(row);
  const [reason, setReason] = useState<ShownReason>(reasons[0]);
  const [photo, setPhoto] = useState<File | null>(null);
  useDraftGuard(Boolean(photo));
  const qty = row.units_per_pack ? qtyText(row.quantity, row.units_per_pack, row.part_label ?? "", t) : t("qty.parts", { count: Number(row.quantity) || 0 });

  const submit = () => {
    propose.mutate({ id: row.id, reason, photo });
    close();
  };

  return (
    <>
      <SheetTitle kicker={row.product?.name ?? packDate(row.expires_on)}>{t("writeoff.title")}</SheetTitle>
      <p className="ft-text">{t("writeoff.what", { series: row.series, qty })}</p>
      {reasons.length > 1 && (
        <Field label={t("writeoff.reason")}>
          <ChipGroup
            value={reason}
            onChange={(next) => next && setReason(next)}
            options={reasons.map((value) => ({ value, label: t(`reason.${value}` as const) }))}
            label={t("writeoff.reason")}
          />
        </Field>
      )}
      <Field label={t("writeoff.photo")} hint={t("writeoff.photoHint")} optional>
        <PhotoInput value={photo} onChange={setPhoto} capture="environment" label={t("photo.cta")} />
      </Field>
      <Button variant="primary" size="lg" block icon={Trash2} onClick={submit}>
        {t("writeoff.submit")}
      </Button>
    </>
  );
}
