/**
 * What attendance puts on Home and Me: the check-in card as Home's hero, a banner while swap
 * requests or open shifts wait, and the Me row's status. They share the `today/` query.
 */
import { Repeat2 } from "lucide-react";

import { useI18n } from "../../i18n";
import { useNavigation } from "../../state/navigation";
import { Banner } from "../../ui";
import type { MeItemStatus, SlotProps } from "../registry";
import { useBoard, useToday } from "./api";
import { CheckInCard } from "./CheckInCard";
import { wallClock } from "./lib";
import { useT } from "./text";
import { weekdayShort } from "../../lib/time";

export function HeroSlot(_: SlotProps) {
  const navigation = useNavigation();
  return <CheckInCard onOpen={() => navigation.push({ feature: "attendance", page: "home" })} />;
}

export function WaitingSlot({ member }: SlotProps) {
  const t = useT();
  const navigation = useNavigation();
  const today = useToday(member.companyId);
  const day = today.data;
  if (!day || day.requests + day.open_shifts === 0) return null;
  return (
    <Banner
      size="lg"
      tone="sage"
      icon={Repeat2}
      title={day.requests ? t("home.requests", { count: day.requests }) : t("home.openShifts", { count: day.open_shifts })}
      body={day.requests ? t("home.requestsBody") : t("home.openShiftsBody")}
      onClick={() => navigation.push({ feature: "attendance", page: "swaps" })}
    />
  );
}

/** Me → Who's in (managers): "3 of 4" people on shift are here. */
export function useBoardStatus({ member }: SlotProps): MeItemStatus {
  const t = useT();
  const board = useBoard(member.companyId);
  const totals = board.data?.totals;
  if (!totals || !totals.rostered) return {};
  return { value: t("me.boardValue", { present: totals.in + totals.late, rostered: totals.rostered }) };
}

/** Me → Attendance: "In since 08:57" while checked in, else the next shift; a bubble for requests. */
export function useMeStatus({ member }: SlotProps): MeItemStatus {
  const t = useT();
  const { locale } = useI18n();
  const today = useToday(member.companyId);
  const day = today.data;
  if (!day) return {};
  const badge = day.requests || null;
  if (day.state === "in" && day.record?.check_in_at) return { value: t("me.in", { time: wallClock(day.record.check_in_at) }), badge };
  const next = day.state === "due" || day.state === "late" || day.state === "upcoming" ? day.shift : day.next_shift;
  if (!next) return { badge };
  return { value: `${weekdayShort(next.starts_at, member.timeZone, locale)} ${next.start}`, badge };
}
