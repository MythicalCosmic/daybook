/**
 * "Attendance" (Me → Attendance, the bot's "📍 Check in / out" button): the check-in card, my
 * month as a calendar with its totals, links to my shifts and swaps, and my fix requests.
 * Tapping a past day opens the fix request for it.
 */
import { CalendarDays, ChevronLeft, ChevronRight, PencilLine, Repeat2 } from "lucide-react";
import { useState } from "react";

import { dayKey, dayMonth, weekdayShort } from "../../lib/time";
import { useNavigation } from "../../state/navigation";
import { useMember } from "../../state/session";
import { useI18n } from "../../i18n";
import { haptic } from "../../telegram";
import { Badge, Card, EmptyState, IconButton, ListCard, ListRow, LoadError, PageHeader, Screen, SectionHead, Skeleton, Stat, StatGrid, cx } from "../../ui";
import { useCorrections, useMonth, useToday } from "./api";
import { CheckInCard } from "./CheckInCard";
import { FIXABLE, monthWeeks, shiftDay, shiftLine, shiftMonth, wallClock, weekOf } from "./lib";
import { codeLabel, hoursText, monthTitle, requestStatusLabel, usePageT } from "./pageText";
import { duration } from "./text";
import type { CellCode, Correction, MyMonth } from "./types";
import "./attendance.css";

const LEGEND: readonly CellCode[] = ["present", "late", "absent", "auto", "leave", "planned"];

export default function AttendancePage() {
  const t = usePageT();
  const { locale } = useI18n();
  const member = useMember();
  const navigation = useNavigation();
  const thisMonth = dayKey(new Date(), member.timeZone).slice(0, 7);
  const [month, setMonth] = useState(thisMonth);
  const today = useToday(member.companyId);
  const sheet = useMonth(member.companyId, month);
  const corrections = useCorrections(member.companyId);

  const day = today.data;
  const waiting = (day?.requests ?? 0) + (day?.open_shifts ?? 0);
  const fix = (params: Record<string, string | number> = {}) =>
    navigation.openSheet({ kind: "feature", feature: "attendance", sheet: "correct", params });

  return (
    <Screen variant="detail">
      <PageHeader kicker={member.company.name} title={t("me.attendance")} onBack={navigation.pop} />

      <CheckInCard />

      <MonthCard
        month={month}
        data={sheet.data}
        loading={sheet.isPending}
        failed={sheet.isError}
        error={sheet.error}
        onRetry={() => sheet.refetch()}
        canGoNext={month < thisMonth}
        onMonth={(next) => {
          haptic.select();
          setMonth(next);
        }}
        onDay={(date, recordId) => fix(recordId ? { record: recordId, date } : { date })}
      />

      {sheet.data && <Totals data={sheet.data} />}

      <ListCard>
        <ListRow
          icon={CalendarDays}
          title={t("link.shifts")}
          subtitle={day?.next_shift ? `${shiftDay(day.next_shift, member.timeZone, locale)} · ${shiftLine(day.next_shift)}` : undefined}
          onClick={() => navigation.push({ feature: "attendance", page: "shifts" })}
        />
        <ListRow icon={Repeat2} title={t("link.swaps")} badge={waiting || null} onClick={() => navigation.push({ feature: "attendance", page: "swaps" })} />
        <ListRow icon={PencilLine} title={t("link.fix")} onClick={() => fix()} />
      </ListCard>

      {corrections.data && corrections.data.length > 0 && (
        <>
          <SectionHead count={corrections.data.length}>{t("corrections.title")}</SectionHead>
          <ListCard>
            {corrections.data.slice(0, 10).map((item) => (
              <CorrectionRow key={item.id} item={item} />
            ))}
          </ListCard>
        </>
      )}
    </Screen>
  );
}

function MonthCard({
  month,
  data,
  loading,
  failed,
  error,
  onRetry,
  canGoNext,
  onMonth,
  onDay,
}: {
  month: string;
  data: MyMonth | undefined;
  loading: boolean;
  failed: boolean;
  error: unknown;
  onRetry: () => void;
  canGoNext: boolean;
  onMonth: (month: string) => void;
  onDay: (date: string, recordId: number | null) => void;
}) {
  const t = usePageT();
  const { locale } = useI18n();
  const weeks = monthWeeks(month);
  const header = weekOf(`${month}-01`);
  const shown = data && data.month === month ? data : undefined;

  return (
    <Card className="att-month">
      <div className="att-month-head">
        <span className="att-month-title">{monthTitle(t, month)}</span>
        <IconButton icon={ChevronLeft} label={t("month.prev")} size={36} variant="ghost" onClick={() => onMonth(shiftMonth(month, -1))} />
        <IconButton icon={ChevronRight} label={t("month.next")} size={36} variant="ghost" disabled={!canGoNext} onClick={() => onMonth(shiftMonth(month, 1))} />
      </div>
      {failed && !shown ? (
        // The app's own failure block: its icon and Try again, not the "all done" check mark.
        <LoadError compact error={error} onRetry={onRetry} />
      ) : (
        <div className="att-cal" role="group" aria-label={monthTitle(t, month)} aria-busy={loading && !shown}>
          {header.map((key) => (
            <span key={key} className="att-cal-weekday" aria-hidden>
              {weekdayShort(`${key}T12:00:00Z`, "UTC", locale)}
            </span>
          ))}
          {weeks.flat().map((date, index) => {
            if (!date) return <span key={`pad-${index}`} />;
            if (!shown) return <Skeleton key={date} height="auto" radius={12} className="att-cal-day" />;
            const cell = shown.cells[date];
            const code: CellCode = shown.holidays[date] && (!cell || cell.code === "off") ? "holiday" : (cell?.code ?? "off");
            const past = date < shown.today || (date === shown.today && code !== "planned");
            const tappable = past && FIXABLE.has(code) && (code !== "off" || date < shown.today);
            const label = t("month.day", { day: dayMonth(`${date}T12:00:00Z`, "UTC", locale), status: codeLabel(t, code) });
            const classes = cx("att-cal-day", `att-cal-day--${code}`, date === shown.today && "att-cal-day--today");
            const number = Number(date.slice(8));
            return tappable ? (
              <button key={date} type="button" className={classes} aria-label={label} title={label} onClick={() => onDay(date, cell?.record_id ?? null)}>
                {number}
              </button>
            ) : (
              <span key={date} className={classes} title={label}>
                {number}
              </span>
            );
          })}
        </div>
      )}
      <div className="att-legend" aria-hidden>
        {LEGEND.map((code) => (
          <span key={code} className="att-legend-item">
            <span className={cx("att-legend-swatch", `att-cal-day--${code}`)} />
            {codeLabel(t, code)}
          </span>
        ))}
      </div>
      <p className="att-hint">{t("month.hint")}</p>
    </Card>
  );
}

function Totals({ data }: { data: MyMonth }) {
  const t = usePageT();
  const totals = data.totals;
  const worked = totals.worked_minutes ?? 0;
  const overtime = totals.overtime_minutes ?? totals.approved_overtime_minutes ?? 0;
  const attended = totals.attended_days ?? 0;
  const scheduled = totals.scheduled_days ?? 0;
  if (!worked && !attended && !scheduled && !(totals.absent_days ?? 0)) {
    return <EmptyState compact icon={CalendarDays} tone="sage" title={t("month.empty")} />;
  }
  return (
    <StatGrid>
      <Stat label={t("stat.worked")} value={hoursText(t, worked)} hint={overtime ? t("stat.overtime", { time: duration(t, overtime) }) : undefined} tone="sage" />
      <Stat label={t("stat.days")} value={scheduled ? `${attended} / ${scheduled}` : String(attended)} />
      <Stat
        label={t("stat.late")}
        value={String(totals.late_arrivals ?? 0)}
        hint={totals.late_minutes ? t("stat.lateTotal", { time: duration(t, totals.late_minutes) }) : undefined}
        tone={totals.late_arrivals ? "accent" : "plain"}
      />
      <Stat label={t("stat.absent")} value={String(totals.absent_days ?? 0)} tone={totals.absent_days ? "accent" : "plain"} />
    </StatGrid>
  );
}

function CorrectionRow({ item }: { item: Correction }) {
  const t = usePageT();
  const { locale } = useI18n();
  // Both times as "09:00–18:22"; one alone says which it is ("Left at 18:22").
  const times =
    item.check_in_at && item.check_out_at
      ? `${wallClock(item.check_in_at)}–${wallClock(item.check_out_at)}`
      : item.check_in_at
        ? `${t("fix.in")} ${wallClock(item.check_in_at)}`
        : item.check_out_at
          ? `${t("fix.out")} ${wallClock(item.check_out_at)}`
          : "";
  const tone = item.status === "approved" ? "sage" : item.status === "rejected" ? "neutral" : "accent";
  return (
    <ListRow
      title={`${weekdayShort(`${item.date}T12:00:00Z`, "UTC", locale)}, ${dayMonth(`${item.date}T12:00:00Z`, "UTC", locale)}`}
      subtitle={[times, item.decision_note || item.reason].filter(Boolean).join(" · ")}
      value={
        <Badge tone={tone} size="small">
          {requestStatusLabel(t, item.status)}
        </Badge>
      }
    />
  );
}
