/**
 * My achievements (Me → "My achievements", PLAN-LEARNING §12.2): the level ring and how far the
 * next level is, the learning streak, the leaderboard and "Say thanks", the badges earned and
 * those still to earn with how to get them, and the latest points.
 */
import { Flame, HeartHandshake, Trophy } from "lucide-react";

import { useI18n } from "../../i18n";
import { dayMonth } from "../../lib/time";
import { useNavigation } from "../../state/navigation";
import { useMember } from "../../state/session";
import { Card, CardButton, EmptyState, LoadError, PageHeader, ProgressBar, Screen, ScreenSkeleton, SectionHead } from "../../ui";
import type { PageProps } from "../registry";
import { useRecognitionMe, type EarnedBadge, type HistoryRow, type LockedBadge } from "./api";
import { LevelRing, levelShare, Medal, useRecognitionT } from "./parts";
import "./recognition.css";

export default function AchievementsPage(_: PageProps) {
  const t = useRecognitionT();
  const member = useMember();
  const navigation = useNavigation();
  const me = useRecognitionMe(member.companyId);

  if (me.isPending) return <ScreenSkeleton variant="hero" delay={150} />;
  if (!me.data) return <LoadError error={me.error} onRetry={() => void me.refetch()} />;
  const data = me.data;
  const { level } = data;
  const total = data.badges.length + data.locked.length;

  return (
    <Screen variant="detail" className="rcg-screen">
      <PageHeader title={t("title")} kicker={member.company.name} onBack={navigation.pop} />

      {data.enabled && (
        <Card tone="accent" className="rcg-level-card">
          <LevelRing number={level.number} share={levelShare(data.points, level)} size={92} stroke={8} />
          <div className="rcg-level-text">
            <span className="rcg-level-kicker">{t("level", { number: level.number })}</span>
            <span className="heading rcg-level-name">{level.name}</span>
            <span className="rcg-level-points num">{t("points", { count: data.points })}</span>
          </div>
          {level.next_at !== null ? (
            <ProgressBar
              value={data.points - level.starts_at}
              total={level.next_at - level.starts_at}
              size="sm"
              caption={t("level.next", { count: level.next_at - data.points, name: level.next_name ?? "" })}
              ariaLabel={t("level.of", { points: data.points, next: level.next_at })}
            />
          ) : (
            <p className="rcg-level-top">{t("level.top")}</p>
          )}
        </Card>
      )}

      <Card className="rcg-streak-card" layout="row">
        <span className={data.streak > 0 ? "rcg-flame rcg-flame--on" : "rcg-flame"} aria-hidden>
          <Flame size={24} strokeWidth={2.4} />
        </span>
        <span className="rcg-streak-text">
          <span className="rcg-streak-kicker">{t("streak.title")}</span>
          <span className="rcg-streak-days">{data.streak > 0 ? t("streak.days", { count: data.streak }) : t("streak.none")}</span>
          <span className="rcg-streak-note">
            {data.best_streak > 0 && `${t("streak.best", { count: data.best_streak })} · `}
            {t("streak.note")}
          </span>
        </span>
      </Card>

      {(data.leaderboard || data.kudos_enabled) && (
        <div className="rcg-actions">
          {data.leaderboard && (
            <CardButton className="rcg-action" onClick={() => navigation.push({ feature: "recognition", page: "leaderboard" })}>
              <Trophy size={20} strokeWidth={2.4} aria-hidden />
              <span>{t("board.open")}</span>
            </CardButton>
          )}
          {data.kudos_enabled && (
            <CardButton className="rcg-action" onClick={() => navigation.push({ feature: "recognition", page: "kudos" })}>
              <HeartHandshake size={20} strokeWidth={2.4} aria-hidden />
              <span>{t("feed.title")}</span>
            </CardButton>
          )}
        </div>
      )}

      <SectionHead count={data.badges.length}>{t("badges.title")}</SectionHead>
      {data.badges.length > 0 && (
        <div className="rcg-badges" data-testid="badges-earned">
          {data.badges.map((badge) => (
            <BadgeTile key={`${badge.key}:${badge.ref}`} badge={badge} />
          ))}
        </div>
      )}
      {data.locked.length > 0 && (
        <>
          <div className="rcg-subhead">
            {t("badges.toEarn")} <span className="num">{t("badges.count", { earned: data.badges.length, total })}</span>
          </div>
          <div className="rcg-badges" data-testid="badges-locked">
            {data.locked.map((badge) => (
              <BadgeTile key={badge.key} badge={badge} locked />
            ))}
          </div>
        </>
      )}

      <SectionHead>{t("history.title")}</SectionHead>
      {data.recent.length ? (
        <Card padding="list">
          {data.recent.map((row) => (
            <HistoryLine key={row.id} row={row} />
          ))}
        </Card>
      ) : (
        <EmptyState compact tone="sage" icon={Trophy} title={t("history.title")} body={t("history.empty")} />
      )}
    </Screen>
  );
}

function BadgeTile({ badge, locked = false }: { badge: EarnedBadge | LockedBadge; locked?: boolean }) {
  const t = useRecognitionT();
  return (
    <div className={locked ? "rcg-badge rcg-badge--locked" : "rcg-badge"}>
      <Medal icon={badge.icon} tier={badge.tier} locked={locked} />
      <span className="rcg-badge-name">{badge.name}</span>
      {locked ? <span className="rcg-badge-how">{badge.description}</span> : <span className={`rcg-tier rcg-tier--${badge.tier}`}>{t(`tier.${badge.tier}`)}</span>}
    </div>
  );
}

function HistoryLine({ row }: { row: HistoryRow }) {
  const member = useMember();
  const { locale } = useI18n();
  const plus = row.points > 0;
  return (
    <div className="list-item rcg-history">
      <span className="rcg-history-text">
        <span className="rcg-history-label">{row.label}</span>
        <span className="rcg-history-detail">{[row.detail, dayMonth(row.at, member.timeZone, locale)].filter(Boolean).join(" · ")}</span>
      </span>
      <span className={plus ? "rcg-history-points num" : "rcg-history-points rcg-history-points--minus num"}>
        {plus ? `+${row.points}` : `−${Math.abs(row.points)}`}
      </span>
    </div>
  );
}
