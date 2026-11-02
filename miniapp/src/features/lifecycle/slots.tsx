/** What "My record" puts on Home and Me: a calm card for a record to read, and Me's bubble for it. */
import { Banner } from "../../ui";
import type { MeItemStatus, SlotProps } from "../registry";
import { useFeatureOpen } from "../useFeatureOpen";
import { useRecords } from "./api";
import { toAcknowledge } from "./lib";
import { kindIcon, kindLabel, useRecordT } from "./text";

export function RecordCard({ member }: SlotProps) {
  const t = useRecordT();
  const go = useFeatureOpen("lifecycle");
  const records = useRecords(member.companyId);
  const first = toAcknowledge(records.data)[0];
  if (!first) return null;
  return (
    <Banner
      size="lg"
      iconTone="accent"
      icon={kindIcon(first.kind)}
      title={t("home.title")}
      body={t("home.body", { kind: kindLabel(t, first.kind) })}
      wrap
      onClick={() => go.page("record", { id: first.id })}
    />
  );
}

export function useMeStatus({ member }: SlotProps): MeItemStatus {
  const records = useRecords(member.companyId);
  return { badge: toAcknowledge(records.data).length || null };
}
