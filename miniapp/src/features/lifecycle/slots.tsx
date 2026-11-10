/**
 * What the lifecycle feature puts on Home and Me: a calm card for a record to read, and Me's
 * bubble for it; while my last day is agreed, a card with that day, and the day on Me's row.
 */
import { CalendarClock } from "lucide-react";

import { useI18n } from "../../i18n";
import { capitalise, dayMonth, dayMonthLong, weekdayLong } from "../../lib/time";
import { Banner } from "../../ui";
import type { MeItemStatus, SlotProps } from "../registry";
import { useFeatureOpen } from "../useFeatureOpen";
import { useLeaving, useRecords } from "./api";
import { leavingStage, toAcknowledge } from "./lib";
import { keepTogether, kindIcon, kindLabel, useRecordT } from "./text";

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

/** "Your last working day: Friday, 20 November", while it is agreed. */
export function LeavingCard({ member }: SlotProps) {
  const t = useRecordT();
  const { locale } = useI18n();
  const go = useFeatureOpen("lifecycle");
  const leaving = useLeaving(member.companyId);
  const current = leaving.data?.current;
  if (!leaving.data || leavingStage(leaving.data) !== "agreed" || !current?.last_day) return null;
  const day = keepTogether(capitalise(`${weekdayLong(current.last_day, "UTC", locale)}, ${dayMonthLong(current.last_day, "UTC", locale)}`));
  return (
    <Banner
      size="lg"
      icon={CalendarClock}
      title={t("home.leaving", { date: day })}
      body={t("home.leavingBody")}
      wrap
      onClick={() => go.page("leaving")}
    />
  );
}

/** Me's row: the agreed day ("20-noy"), or "Waiting" while the manager hasn't answered. */
export function useLeavingStatus({ member }: SlotProps): MeItemStatus {
  const t = useRecordT();
  const { locale } = useI18n();
  const leaving = useLeaving(member.companyId);
  if (!leaving.data) return {};
  const stage = leavingStage(leaving.data);
  const day = leaving.data.current?.last_day;
  if (stage === "agreed" && day) return { value: dayMonth(day, "UTC", locale) };
  if (stage === "requested") return { value: t("me.leavingWaiting") };
  return {};
}
