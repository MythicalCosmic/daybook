/** Writing my explanation to a record: once, in my own words; the person who gave it reads it. */
import { Send } from "lucide-react";
import { useState } from "react";

import { useDraftGuard } from "../../lib/useDraftGuard";
import { useMember } from "../../state/session";
import { Button, Field, SheetTitle, Textarea } from "../../ui";
import type { SheetProps } from "../registry";
import { SheetMissing, useFeedback } from "../states";
import { useExplain, useRecords } from "./api";
import { canExplain, EXPLAIN_MAX, explainPayload } from "./lib";
import { kindLabel, useRecordT } from "./text";
import "./lifecycle.css";

export default function ExplainSheet({ params, close }: SheetProps) {
  const t = useRecordT();
  const member = useMember();
  const records = useRecords(member.companyId);
  const explain = useExplain(member.companyId);
  const feedback = useFeedback();
  const [text, setText] = useState("");
  useDraftGuard(Boolean(text.trim()));
  const record = records.data?.find((row) => row.id === Number(params.id));
  if (!record || !canExplain(record)) return <SheetMissing pending={records.isPending} error={records.error} onRetry={() => void records.refetch()} />;

  const payload = explainPayload(text);
  const left = EXPLAIN_MAX - text.trim().length;
  const send = () => {
    if (!payload || explain.isPending) return;
    explain.mutate(
      { id: record.id, ...payload },
      {
        onSuccess: () => {
          feedback.ok(t("explain.sent"));
          close();
        },
        onError: feedback.fail,
      },
    );
  };
  return (
    <>
      <SheetTitle kicker={kindLabel(t, record.kind)}>{t("explain.title")}</SheetTitle>
      <Field label={t("explain.label")} hint={left < 200 ? t("explain.left", { count: Math.max(0, left) }) : t("explain.hint")}>
        <Textarea value={text} onChange={(event) => setText(event.target.value)} rows={6} maxLength={EXPLAIN_MAX} placeholder={t("explain.placeholder")} autoFocus />
      </Field>
      <Button variant="primary" size="lg" block icon={Send} disabled={!payload} loading={explain.isPending} onClick={send}>
        {t("explain.send")}
      </Button>
    </>
  );
}
