/**
 * Ask to fix a day (`params.record` and/or `params.date`; the notification about an automatic
 * check-out opens it with the record): the times I really came and left and what happened. The
 * manager decides; the change is audited on their side.
 */
import { Send } from "lucide-react";
import { useState } from "react";

import { useI18n } from "../../i18n";
import { errorText } from "../../lib/actions";
import { addDays, dayKey, dayMonth, weekdayShort } from "../../lib/time";
import { useMember } from "../../state/session";
import { haptic } from "../../telegram";
import { Button, EmptyState, Field, Input, SheetTitle, SkeletonList, Textarea, useToast } from "../../ui";
import type { SheetProps } from "../registry";
import { useRecord, useRequestCorrection } from "./api";
import { wallClock } from "./lib";
import { usePageT, type PageT } from "./pageText";
import { duration } from "./text";
import type { AttendanceRecord } from "./types";
import "./attendance.css";

export default function CorrectSheet({ params, close }: SheetProps) {
  const t = usePageT();
  const member = useMember();
  const recordId = params.record !== undefined && Number.isFinite(Number(params.record)) ? Number(params.record) : null;
  const record = useRecord(member.companyId, recordId);
  if (recordId !== null && record.isPending) return <SkeletonList count={3} height={56} />;
  if (recordId !== null && record.isError) return <EmptyState compact title={t("ui.notFound.title")} body={t("ui.notFound.body")} />;
  const date = record.data?.date ?? (typeof params.date === "string" ? params.date : null);
  return <CorrectForm record={record.data ?? null} initialDate={date} close={close} />;
}

/** The record as it stands: "09:12–18:00 · 8 h 48 min", or its status. */
function currentText(record: AttendanceRecord, t: PageT): string {
  if (!record.check_in_at) return t(`code.${record.status === "excused" ? "excused" : "absent"}`);
  const out = record.check_out_at ? wallClock(record.check_out_at) : "…";
  const span = `${wallClock(record.check_in_at)}–${out}`;
  return record.worked_minutes ? `${span} · ${duration(t, record.worked_minutes)}` : span;
}

function CorrectForm({ record, initialDate, close }: { record: AttendanceRecord | null; initialDate: string | null; close: () => void }) {
  const t = usePageT();
  const { locale } = useI18n();
  const member = useMember();
  const toast = useToast();
  const request = useRequestCorrection(member.companyId);
  const today = dayKey(new Date(), member.timeZone);
  const [date, setDate] = useState(initialDate ?? addDays(today, -1));
  const [arrived, setArrived] = useState(record?.check_in_at ? wallClock(record.check_in_at) : "");
  const [left, setLeft] = useState(record?.check_out_at ? wallClock(record.check_out_at) : "");
  const [reason, setReason] = useState("");
  const valid = Boolean(date) && date <= today && reason.trim().length > 0 && Boolean(arrived || left);

  const submit = () => {
    if (!valid || request.isPending) return;
    // Leaving "earlier" than arriving means the shift ran past midnight.
    const outDay = arrived && left && left < arrived ? addDays(date, 1) : date;
    request.mutate(
      {
        date,
        record_id: record?.id ?? null,
        check_in_at: arrived ? `${date}T${arrived}` : null,
        check_out_at: left ? `${outDay}T${left}` : null,
        reason: reason.trim(),
      },
      {
        onSuccess: () => {
          haptic.notify("success");
          close();
          toast(t("fix.sentToast"));
        },
        onError: (error) => {
          haptic.notify("error");
          toast(errorText(error, t));
        },
      },
    );
  };

  const kicker = date ? `${weekdayShort(`${date}T12:00:00Z`, "UTC", locale)}, ${dayMonth(`${date}T12:00:00Z`, "UTC", locale)}` : undefined;
  return (
    <div className="att-sheet">
      <SheetTitle kicker={kicker}>{t("link.fix")}</SheetTitle>
      {record ? (
        <p className="att-hint num">{t("fix.now", { value: currentText(record, t) })}</p>
      ) : (
        <Field label={t("fix.day")}>
          <Input type="date" num max={today} value={date} onChange={(event) => setDate(event.target.value)} />
        </Field>
      )}
      <div className="att-times">
        <Field label={t("fix.in")}>
          <Input type="time" num value={arrived} onChange={(event) => setArrived(event.target.value)} />
        </Field>
        <Field label={t("fix.out")}>
          <Input type="time" num value={left} onChange={(event) => setLeft(event.target.value)} />
        </Field>
      </div>
      <Field label={t("fix.reason")}>
        <Textarea value={reason} maxLength={300} placeholder={t("fix.reasonPlaceholder")} onChange={(event) => setReason(event.target.value)} />
      </Field>
      <p className="att-hint">{t("fix.note")}</p>
      <Button variant="primary" size="lg" block icon={Send} disabled={!valid} loading={request.isPending} onClick={submit}>
        {t("fix.send")}
      </Button>
    </div>
  );
}
