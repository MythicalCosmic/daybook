/**
 * "Mening tarixim" (Me → My career, and the bot's `lifecycle.career` link when my job changes):
 * my job now, then one timeline: the changes approved to come ("From 1 December"), those that
 * took effect, and the day I joined. My own pay is in it: it is mine to see.
 */
import { ArrowRight, BriefcaseBusiness, Milestone } from "lucide-react";

import { useI18n } from "../../i18n";
import { dayMonthYear } from "../../lib/time";
import { useNavigation } from "../../state/navigation";
import { useMember } from "../../state/session";
import { Badge, Card, EmptyState, LoadError, PageHeader, Screen, ScreenSkeleton, SectionHead, cx } from "../../ui";
import { useCareer, type MyJobChange } from "./api";
import { partChanges, splitCareer } from "./lib";
import { payText, useRecordT, type RecordKey } from "./text";
import "./lifecycle.css";

export default function CareerPage() {
  const t = useRecordT();
  const { locale } = useI18n();
  const member = useMember();
  const navigation = useNavigation();
  const career = useCareer(member.companyId);
  const header = <PageHeader kicker={member.company.name} title={t("me.career")} subtitle={t("career.subtitle")} onBack={navigation.pop} />;

  if (!career.data) {
    return (
      <Screen variant="detail">
        {header}
        {career.isError ? (
          <LoadError error={career.error} onRetry={() => void career.refetch()} onBack={navigation.pop} />
        ) : (
          <ScreenSkeleton variant="detail" delay={150} />
        )}
      </Screen>
    );
  }

  const data = career.data;
  const { coming, applied } = splitCareer(data.changes);
  const where = [data.branch, data.department].filter(Boolean).join(" · ");
  return (
    <Screen variant="detail">
      {header}
      <Card className="lc-now" data-testid="career-now">
        <span className="circle lc-now-icon" aria-hidden>
          <BriefcaseBusiness size={20} strokeWidth={2.3} />
        </span>
        <span className="lc-now-text">
          <span className="lc-now-kicker">{t("career.now")}</span>
          <span className="lc-now-title">{data.position ?? t("career.noPosition")}</span>
          {where && <span className="lc-now-where">{where}</span>}
        </span>
      </Card>

      {data.changes.length === 0 ? (
        <>
          <EmptyState compact icon={Milestone} tone="sage" title={t("career.empty")} body={t("career.emptyBody")} />
          {data.hired_on && (
            <p className="ft-hint lc-pad" data-testid="career-joined">
              {t("career.joined", { date: dayMonthYear(data.hired_on, "UTC", locale) })}
            </p>
          )}
        </>
      ) : (
        <>
          <SectionHead size="small">{t("career.changes")}</SectionHead>
          <ol className="lc-timeline">
            {coming.map((change) => (
              <ChangeItem key={change.id} change={change} coming />
            ))}
            {applied.map((change) => (
              <ChangeItem key={change.id} change={change} />
            ))}
            {data.hired_on && (
              <li className="lc-tl lc-tl--start" data-testid="career-joined">
                <span className="lc-tl-dot" aria-hidden />
                <div className="lc-tl-body lc-tl-body--plain">
                  <span className="lc-tl-date">{t("career.joined", { date: dayMonthYear(data.hired_on, "UTC", locale) })}</span>
                </div>
              </li>
            )}
          </ol>
        </>
      )}
    </Screen>
  );
}

function ChangeItem({ change, coming = false }: { change: MyJobChange; coming?: boolean }) {
  const t = useRecordT();
  const { lang, locale } = useI18n();
  // History keeps its years: "1 December 2026", "2026-yil 1-dekabr".
  const day = dayMonthYear(change.effective_on, "UTC", locale);
  const lines = partChanges(change, (pay) => payText(t, pay, lang));
  return (
    <li className={cx("lc-tl", coming && "lc-tl--coming")} data-testid="career-change">
      <span className="lc-tl-dot" aria-hidden />
      <div className="lc-tl-body">
        <div className="lc-tl-head">
          <span className="lc-tl-date">{coming ? t("career.from", { date: day }) : day}</span>
          {coming && (
            <Badge tone="accent" size="small">
              {t("career.approved")}
            </Badge>
          )}
        </div>
        {lines.map((line) => (
          <div key={line.part} className="lc-tl-line">
            <span className="lc-tl-part">{t(`part.${line.part}` as RecordKey)}</span>
            <span className="lc-tl-change">
              <span className="lc-tl-was">{line.was ?? t("part.none")}</span>
              <ArrowRight className="lc-tl-arrow" size={14} strokeWidth={2.6} aria-hidden />
              <span className="lc-tl-now">{line.now ?? t("part.none")}</span>
            </span>
          </div>
        ))}
      </div>
    </li>
  );
}
