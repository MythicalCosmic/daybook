import { CalendarCheck2, ChevronLeft, ChevronRight } from "lucide-react";
import { useMemo, useState } from "react";

import { useI18n } from "../../i18n";
import { useFeatureT } from "../../i18n/feature";
import { addDays, dayKey, dayMonth, weekdayShort } from "../../lib/time";
import { useNavigation } from "../../state/navigation";
import { useMember } from "../../state/session";
import { haptic } from "../../telegram";
import { Badge, Card, EmptyState, ListRow, LoadError, PageHeader, Screen, ScreenSkeleton, SectionHead, cx } from "../../ui";
import { eventIdOf, useCalendar, type CalendarEntry } from "./api";
import "./agenda.css";
import { byDay, colorClass, dayName, mondayOf, timeLabel, weekDays } from "./lib";
import { messages } from "./messages";

/** My calendar: a week strip with what each day holds, and the next two weeks as a list. */
export function CalendarHome() {
  const t = useFeatureT(messages);
  const { locale } = useI18n();
  const member = useMember();
  const navigation = useNavigation();
  const today = dayKey(new Date(), member.timeZone);
  const [monday, setMonday] = useState(() => mondayOf(today));
  const [selected, setSelected] = useState(today);
  const days = weekDays(monday);
  const week = useCalendar(member.companyId, monday, days[6]!);
  const upcoming = useCalendar(member.companyId, today, addDays(today, 13));

  const labels = useMemo(() => Object.fromEntries((week.data?.sources ?? []).map((source) => [source.key, source.label])), [week.data]);
  const mine = useMemo(() => new Set([...(week.data?.mine ?? []), ...(upcoming.data?.mine ?? [])]), [week.data, upcoming.data]);
  const answers = useMemo(() => ({ ...(week.data?.answers ?? {}), ...(upcoming.data?.answers ?? {}) }), [week.data, upcoming.data]);
  const weekByDay = useMemo(() => byDay(week.data?.items ?? [], days, member.timeZone), [week.data, days, member.timeZone]);
  const upcomingDays = Array.from({ length: 14 }, (_, i) => addDays(today, i));
  const nextByDay = useMemo(() => byDay(upcoming.data?.items ?? [], upcomingDays, member.timeZone), [upcoming.data, today, member.timeZone]);
  const words = { today: t("today"), tomorrow: t("tomorrow") };

  const open = (item: CalendarEntry) => {
    const id = eventIdOf(item);
    if (!id) return;
    haptic.select();
    navigation.push({ feature: "agenda", page: "event", params: { id } });
  };
  // Only an answer still due (or a "can't come") needs a mark; events the person comes to stay quiet.
  const answerBadge = (id: string) => {
    const answer = answers[id];
    if (answer === "pending") return <Badge tone="accent" size="small">{t("answer.ask")}</Badge>;
    if (answer === "declined") return <Badge size="small">{t("answer.declined")}</Badge>;
    if (!answer && mine.has(id)) return <Badge tone="accent" size="small">{t("mine")}</Badge>;
    return undefined;
  };
  const row = (item: CalendarEntry, day: string) => (
    <ListRow
      key={`${day}-${item.id}`}
      variant="card"
      icon={<span className={cx("agm-bar", colorClass(item.color))} />}
      title={item.title}
      subtitle={[timeLabel(item, member.timeZone, locale, t("allDay")), eventIdOf(item) ? item.subtitle : labels[item.source]].filter(Boolean).join(" · ")}
      value={answerBadge(item.id)}
      chevron={eventIdOf(item) !== null}
      onClick={eventIdOf(item) ? () => open(item) : undefined}
    />
  );

  const shift = (weeks: number) => {
    haptic.select();
    const next = addDays(monday, weeks * 7);
    setMonday(next);
    setSelected(weeks === 0 ? today : next);
  };

  const dayItems = weekByDay.get(selected) ?? [];
  // The selected day is listed above, so "Coming up" doesn't repeat it.
  const nextDays = upcomingDays.filter((day) => day !== selected && (nextByDay.get(day) ?? []).length > 0);

  return (
    <Screen variant="detail">
      <PageHeader kicker={member.company.name} title={t("title")} onBack={navigation.pop} />
      <Card padding="flush">
        <div className="agm-week">
          <button type="button" className="agm-week-nav" aria-label={t("week.prev")} onClick={() => shift(-1)}>
            <ChevronLeft size={20} strokeWidth={2.5} aria-hidden />
          </button>
          {days.map((day) => {
            const items = weekByDay.get(day) ?? [];
            return (
              <button
                key={day}
                type="button"
                className={cx("agm-day", day === today && "agm-day--today")}
                aria-pressed={day === selected}
                aria-label={`${dayName(day, today, member.timeZone, locale, words)} ${dayMonth(`${day}T12:00:00Z`, member.timeZone, locale)}`}
                onClick={() => {
                  haptic.select();
                  setSelected(day);
                }}
              >
                <span className="agm-day-name">{weekdayShort(`${day}T12:00:00Z`, member.timeZone, locale)}</span>
                <span className="agm-day-num">{Number(day.slice(8))}</span>
                <span className="agm-dots" aria-hidden>
                  {items.slice(0, 3).map((item) => (
                    <span key={item.id} className={cx("agm-dot", colorClass(item.color))} />
                  ))}
                </span>
              </button>
            );
          })}
          <button type="button" className="agm-week-nav" aria-label={t("week.next")} onClick={() => shift(1)}>
            <ChevronRight size={20} strokeWidth={2.5} aria-hidden />
          </button>
        </div>
      </Card>

      <SectionHead
        size="small"
        action={monday !== mondayOf(today) || selected !== today ? { label: t("today"), onClick: () => shift(0) } : undefined}
      >
        {dayName(selected, today, member.timeZone, locale, words)} · {dayMonth(`${selected}T12:00:00Z`, member.timeZone, locale)}
      </SectionHead>
      {!week.data ? (
        week.isError ? (
          <LoadError compact error={week.error} onRetry={() => void week.refetch()} />
        ) : (
          <ScreenSkeleton variant="list" delay={150} rows={2} />
        )
      ) : dayItems.length === 0 ? (
        <p className="agm-hint">{t("day.empty")}</p>
      ) : (
        dayItems.map((item) => row(item, selected))
      )}

      <SectionHead>{t("upcoming")}</SectionHead>
      {!upcoming.data ? (
        upcoming.isError ? null : (
          <ScreenSkeleton variant="list" delay={150} rows={3} />
        )
      ) : nextDays.length === 0 ? (
        <EmptyState compact tone="sage" icon={CalendarCheck2} title={t("upcoming.empty")} />
      ) : (
        nextDays.map((day) => (
          <div key={day} className="agm-group">
            <SectionHead size="small">{`${dayName(day, today, member.timeZone, locale, words)} · ${dayMonth(`${day}T12:00:00Z`, member.timeZone, locale)}`}</SectionHead>
            {(nextByDay.get(day) ?? []).map((item) => row(item, day))}
          </div>
        ))
      )}
    </Screen>
  );
}
