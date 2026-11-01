import { useState } from "react";

import { useTeamStats } from "../api/hooks";
import type { Period, Score, TeamRow } from "../api/types";
import { Ring } from "../components/Ring";
import { useI18n, type Translate } from "../i18n";
import { duration } from "../lib/taskView";
import { tone, type Tone } from "../lib/team";
import { dayMonth } from "../lib/time";
import { useNavigation } from "../state/navigation";
import { useMember } from "../state/session";
import { Avatar, Card, LoadError, PageHeader, Screen, SectionHead, Segmented, Skeleton } from "../ui";

const PERIODS: Period[] = ["week", "last_week", "month"];
const TONE_TAG: Record<Tone, string> = {
  good: "tag-sage",
  fair: "tag-neutral",
  poor: "tag-accent",
  none: "tag-neutral",
};

/** How everyone's shared work went, for people who may see reports. */
export function Team() {
  const { t, locale } = useI18n();
  const member = useMember();
  const navigation = useNavigation();
  const [period, setPeriod] = useState<Period>("week");
  const stats = useTeamStats(member.companyId, period);
  const data = stats.data;

  return (
    <div className="detail-layer">
      <Screen variant="detail">
        <PageHeader kicker={member.company.name} title={t("team.title")} onBack={navigation.pop} />

        <Segmented
          fit
          label={t("team.title")}
          options={PERIODS.map((option) => ({ value: option, label: t(`team.period.${option}`) }))}
          value={period}
          onChange={setPeriod}
        />

        {!data ? (
          stats.isError ? (
            <LoadError compact error={stats.error} onRetry={() => void stats.refetch()} />
          ) : (
            <>
              <Skeleton height={132} />
              <Skeleton height={260} />
            </>
          )
        ) : (
          <>
            <Totals score={data.totals} range={`${dayMonth(data.start, member.timeZone, locale)}–${dayMonth(data.end, member.timeZone, locale)}`} t={t} />
            <SectionHead size="small">{t("team.people")}</SectionHead>
            <div className="team-people">
              {data.members.map((row) => (
                <Person key={row.member.id} row={row} t={t} />
              ))}
            </div>
          </>
        )}
      </Screen>
    </div>
  );
}

function Totals({ score, range, t }: { score: Score; range: string; t: Translate }) {
  return (
    <Card className="team-totals">
      {score.total === 0 ? (
        <span className="muted">
          {t("team.empty")} <span className="num">{range}</span>
        </span>
      ) : (
        <>
          <div className="team-totals-head">
            <Ring done={score.on_time} total={score.total} />
            <div className="team-totals-text">
              <span className="heading num team-totals-percent">{score.on_time_percent}%</span>
              <span className="team-totals-label">
                {t("team.onTime")} · <span className="num">{range}</span>
              </span>
            </div>
          </div>
          <div className="team-totals-tags">
            {score.late > 0 && <span className="tag tag-neutral">{t("team.late", { count: score.late })}</span>}
            {score.missed > 0 && <span className="tag tag-accent">{t("team.missed", { count: score.missed })}</span>}
            {score.avg_delay_minutes != null && (
              <span className="tag tag-neutral">{t("team.avgDelay", { duration: duration(score.avg_delay_minutes, t) })}</span>
            )}
            {score.reminders > 0 && <span className="tag tag-neutral">{t("team.reminders", { count: score.reminders })}</span>}
          </div>
        </>
      )}
      {score.late_now > 0 && <span className="row-meta row-meta--alert">{t("team.lateNow", { count: score.late_now })}</span>}
    </Card>
  );
}

function Person({ row, t }: { row: TeamRow; t: Translate }) {
  const meta = [
    row.member.position,
    row.total ? t("team.tasks", { count: row.total }) : t("team.noWork"),
    row.late ? t("team.late", { count: row.late }) : null,
    row.missed ? t("team.missed", { count: row.missed }) : null,
  ]
    .filter(Boolean)
    .join(" · ");
  return (
    <div className="row row--static">
      <Avatar name={row.member.name} size="md" />
      <div className="row-main">
        <span className="row-title">{row.member.name}</span>
        <span className="row-meta row-meta--wrap">{meta}</span>
        {row.late_now > 0 && <span className="row-meta row-meta--alert">{t("team.lateNow", { count: row.late_now })}</span>}
      </div>
      {row.on_time_percent != null && <span className={`tag ${TONE_TAG[tone(row)]} num`}>{row.on_time_percent}%</span>}
    </div>
  );
}
