import { useState } from "react";

import { useTeamStats } from "../api/hooks";
import type { Period, Score, TeamRow } from "../api/types";
import { Ring } from "../components/Ring";
import { useI18n, type Translate } from "../i18n";
import { duration } from "../lib/taskView";
import { nameInitials, tone, type Tone } from "../lib/team";
import { dayMonth } from "../lib/time";
import { useMember } from "../state/session";
import { haptic } from "../telegram";
import { LoadError } from "../ui";

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
  const [period, setPeriod] = useState<Period>("week");
  const stats = useTeamStats(member.companyId, period);
  const data = stats.data;
  // Dates without a time: read them at noon UTC so no timezone moves the day.
  const day = (date: string) => dayMonth(`${date}T12:00:00Z`, "UTC", locale);

  return (
    <div className="detail-layer">
      <div className="screen screen--detail">
        <div style={{ padding: "0 4px" }}>
          <div className="muted" style={{ fontSize: 14, fontWeight: 600 }}>{member.company.name}</div>
          <h1 className="heading" style={{ fontSize: 30, lineHeight: 1.1 }}>{t("team.title")}</h1>
        </div>

        <div className="seg seg--fit">
          {PERIODS.map((option) => (
            <button
              key={option}
              className="seg-opt"
              aria-pressed={period === option}
              onClick={() => {
                haptic();
                setPeriod(option);
              }}
            >
              {t(`team.period.${option}`)}
            </button>
          ))}
        </div>

        {!data ? (
          stats.isError ? (
            <LoadError compact error={stats.error} onRetry={() => void stats.refetch()} />
          ) : (
            <>
              <div className="skeleton" style={{ height: 132 }} />
              <div className="skeleton" style={{ height: 260 }} />
            </>
          )
        ) : (
          <>
            <Totals score={data.totals} range={`${day(data.start)}–${day(data.end)}`} t={t} />
            <div className="section-head section-head--small">{t("team.people")}</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {data.members.map((row) => (
                <Person key={row.member.id} row={row} t={t} />
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function Totals({ score, range, t }: { score: Score; range: string; t: Translate }) {
  return (
    <div className="card" style={{ padding: 18, gap: 14 }}>
      {score.total === 0 ? (
        <span className="muted" style={{ fontSize: 15 }}>
          {t("team.empty")} <span className="num">{range}</span>
        </span>
      ) : (
        <>
          <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
            <Ring done={score.on_time} total={score.total} />
            <div style={{ display: "flex", flexDirection: "column", gap: 4, minWidth: 0 }}>
              <span className="heading num" style={{ fontSize: 32, lineHeight: 1 }}>
                {score.on_time_percent}%
              </span>
              <span style={{ fontSize: 14, fontWeight: 600 }}>
                {t("team.onTime")} · <span className="num">{range}</span>
              </span>
            </div>
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {score.late > 0 && <span className="tag tag-neutral">{t("team.late", { count: score.late })}</span>}
            {score.missed > 0 && <span className="tag tag-accent">{t("team.missed", { count: score.missed })}</span>}
            {score.avg_delay_minutes != null && (
              <span className="tag tag-neutral">
                {t("team.avgDelay", { duration: duration(score.avg_delay_minutes, t) })}
              </span>
            )}
            {score.reminders > 0 && (
              <span className="tag tag-neutral">{t("team.reminders", { count: score.reminders })}</span>
            )}
          </div>
        </>
      )}
      {score.late_now > 0 && (
        <span className="row-meta row-meta--alert">{t("team.lateNow", { count: score.late_now })}</span>
      )}
    </div>
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
      <span className="avatar" style={{ width: 40, height: 40, fontSize: 14 }}>
        {nameInitials(row.member.name)}
      </span>
      <div className="row-main">
        <span className="row-title">{row.member.name}</span>
        <span className="row-meta row-meta--wrap">{meta}</span>
        {row.late_now > 0 && (
          <span className="row-meta row-meta--alert">{t("team.lateNow", { count: row.late_now })}</span>
        )}
      </div>
      {row.on_time_percent != null && (
        <span className={`tag ${TONE_TAG[tone(row)]} num`}>{row.on_time_percent}%</span>
      )}
    </div>
  );
}
