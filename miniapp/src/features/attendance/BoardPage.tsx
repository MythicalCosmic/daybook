/**
 * "Who's in" for managers in the app (plan §4.9 E `attendance/board/`, needs attendance.view):
 * today's people in the board's states, most urgent first: who came late, who isn't here yet,
 * who didn't come, who is in, and who is off. Each row shows the shift, the check-in and how far
 * from the branch it was. Read-only; corrections stay in the dashboard. Live every minute.
 */
import { CalendarOff, Lock, MapPin } from "lucide-react";

import { can } from "../../api/permissions";
import { useI18n } from "../../i18n";
import { formatDistance } from "../../lib/location";
import { longDate } from "../../lib/time";
import { useNavigation } from "../../state/navigation";
import { useMember } from "../../state/session";
import { Avatar, Badge, EmptyState, ListCard, ListRow, PageHeader, Screen, SectionHead, SkeletonList, Stat, StatGrid } from "../../ui";
import { useBoard } from "./api";
import { minutesBetween, wallClock } from "./lib";
import { codeLabel, usePageT, type PageKey, type PageT } from "./pageText";
import { duration } from "./text";
import type { Board, BoardRow, BoardState } from "./types";
import "./attendance.css";

/** Sections in the order a manager acts on them. */
const ORDER: readonly BoardState[] = ["late", "not_yet", "absent", "in", "off"];

export default function BoardPage() {
  const t = usePageT();
  const { locale } = useI18n();
  const member = useMember();
  const navigation = useNavigation();
  // A link opened without attendance.view says so instead of asking the server for a refusal.
  const allowed = can(member, "attendance.view");
  const board = useBoard(member.companyId, allowed);
  const data = board.data;
  const subtitle = data ? [longDate(new Date(data.now), member.timeZone, locale), data.holiday].filter(Boolean).join(" · ") : undefined;

  return (
    <Screen variant="detail">
      <PageHeader kicker={t("me.attendance")} title={t("board.title")} subtitle={subtitle} onBack={navigation.pop} />
      {!allowed ? (
        <EmptyState icon={Lock} tone="sage" title={t("board.denied")} body={t("board.deniedBody")} />
      ) : board.isPending ? (
        <SkeletonList count={6} />
      ) : board.isError || !data ? (
        <EmptyState title={t("ui.failed.title")} body={t("ui.failed.body")} action={{ label: t("common.retry"), onClick: () => board.refetch() }} />
      ) : !data.people.length ? (
        <EmptyState icon={CalendarOff} tone="sage" title={t("board.empty")} body={t("board.emptyBody")} />
      ) : (
        <BoardBody data={data} />
      )}
    </Screen>
  );
}

function BoardBody({ data }: { data: Board }) {
  const t = usePageT();
  const { totals } = data;
  const present = totals.in + totals.late;
  return (
    <>
      <StatGrid>
        <Stat label={t("board.state.in")} value={String(present)} hint={t("board.here", { present, rostered: totals.rostered })} tone="sage" />
        <Stat label={t("board.state.not_yet")} value={String(totals.not_yet)} tone={totals.not_yet ? "accent" : "plain"} />
        <Stat label={t("board.state.late")} value={String(totals.late)} tone={totals.late ? "accent" : "plain"} />
        <Stat label={t("board.state.absent")} value={String(totals.absent)} tone={totals.absent ? "accent" : "plain"} />
      </StatGrid>
      {ORDER.map((state) => {
        const rows = data.people.filter((row) => row.state === state);
        if (!rows.length) return null;
        return (
          <section key={state} className="att-board-section" aria-label={t(`board.state.${state}` as PageKey)}>
            <SectionHead count={rows.length}>{t(`board.state.${state}` as PageKey)}</SectionHead>
            <ListCard>
              {rows.map((row) => (
                <PersonRow key={row.member.id} row={row} now={data.now} />
              ))}
            </ListCard>
          </section>
        );
      })}
    </>
  );
}

function PersonRow({ row, now }: { row: BoardRow; now: string }) {
  const t = usePageT();
  const { lang } = useI18n();
  const { record, shift } = row;
  const hours = shift && row.state !== "off" ? `${shift.start}–${shift.end}` : "";
  const outside = record?.flags.includes("outside_geofence") ?? false;
  const subtitle = [hours, detail(t, row), row.member.position?.name].filter(Boolean).join(" · ");
  const late = record?.is_late ? record.late_minutes : row.state === "not_yet" && row.reason === "late" && shift ? minutesBetween(shift.starts_at, now) : 0;
  const value = late ? (
    <Badge tone="accent" size="small">
      +{duration(t, late)}
    </Badge>
  ) : record && record.in_distance_m !== null ? (
    <Badge tone={outside ? "accent" : "neutral"} size="small" icon={MapPin}>
      {outside ? t("board.outside", { distance: formatDistance(record.in_distance_m, lang) }) : formatDistance(record.in_distance_m, lang)}
    </Badge>
  ) : undefined;
  return (
    <ListRow
      icon={<Avatar name={row.member.name} src={row.member.photo_url} size="sm" tone={row.state === "absent" || row.state === "late" ? "accent" : row.state === "off" ? "neutral" : "sage"} />}
      title={row.member.name}
      subtitle={subtitle}
      alert={row.state === "absent" || (row.state === "not_yet" && row.reason === "late")}
      value={value}
    />
  );
}

/** What the day looks like for one person, in a few words. */
function detail(t: PageT, row: BoardRow): string {
  const { record, shift } = row;
  switch (row.state) {
    case "in":
    case "late": {
      if (!record?.check_in_at) return "";
      const came = wallClock(record.check_in_at);
      return record.check_out_at ? t("board.inOut", { in: came, out: wallClock(record.check_out_at) }) : t("me.in", { time: came });
    }
    case "not_yet":
      if (!shift) return "";
      return row.reason === "late" ? t("board.startedAt", { time: shift.start }) : t("board.startsAt", { time: shift.start });
    case "absent":
      return t("board.noCheckIn");
    default:
      switch (row.reason) {
        case "leave":
          return codeLabel(t, "leave");
        case "holiday":
          return codeLabel(t, "holiday");
        case "excused":
          return codeLabel(t, "excused");
        case "suspended":
          return t("board.suspended");
        case "day_off":
          return codeLabel(t, "off");
        default:
          return t("board.noShift");
      }
  }
}
