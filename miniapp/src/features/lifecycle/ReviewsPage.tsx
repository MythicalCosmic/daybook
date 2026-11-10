/**
 * "Baholashlarim" (Me → My reviews, and the bot's `lifecycle.reviews` link): a round waiting for my
 * answers first (or sent, waiting for my manager), then my published reviews with their rating and
 * what followed (new ones marked until I read them), and the goals my reviews set me.
 */
import { CheckCheck, ClipboardPen, Hourglass, Star, Target } from "lucide-react";

import { useI18n } from "../../i18n";
import { dayMonthYear } from "../../lib/time";
import { useNavigation } from "../../state/navigation";
import { useMember } from "../../state/session";
import { Badge, CardButton, EmptyState, ListCard, ListRow, LoadError, PageHeader, Screen, ScreenSkeleton, SectionHead, cx } from "../../ui";
import { useFeatureOpen } from "../useFeatureOpen";
import { noBreak, useMyReviews, type MyReviewRow } from "./reviews";
import { useRecordT, type RecordKey } from "./text";
import "./lifecycle.css";

export default function ReviewsPage() {
  const t = useRecordT();
  const { locale } = useI18n();
  const member = useMember();
  const navigation = useNavigation();
  const go = useFeatureOpen("lifecycle");
  const reviews = useMyReviews(member.companyId);
  const header = <PageHeader kicker={member.company.name} title={t("rv.listTitle")} subtitle={t("rv.listSubtitle")} onBack={navigation.pop} />;

  if (!reviews.data) {
    return (
      <Screen variant="detail">
        {header}
        {reviews.isError ? <LoadError error={reviews.error} onRetry={() => void reviews.refetch()} onBack={navigation.pop} /> : <ScreenSkeleton variant="list" delay={150} />}
      </Screen>
    );
  }
  const { open, past, goals } = reviews.data;
  const day = (value: string) => noBreak(dayMonthYear(value, "UTC", locale, new Date()));
  const openReview = (row: MyReviewRow) => go.page("review", { id: row.id });

  return (
    <Screen variant="detail">
      {header}
      {!open.length && !past.length && <EmptyState icon={Star} tone="sage" title={t("rv.emptyTitle")} body={t("rv.emptyBody")} />}

      {open.map((row) => (
        <CardButton key={row.id} tone={row.can_answer ? "accent" : "plain"} className="rv-open" onClick={() => openReview(row)}>
          <span className="circle rv-open-icon">{row.can_answer ? <ClipboardPen size={20} aria-hidden="true" /> : <Hourglass size={20} aria-hidden="true" />}</span>
          <span className="rv-open-main">
            <span className="rv-open-title">{noBreak(row.round.name)}</span>
            <span className={cx("rv-open-line", row.late && "lc-warn")}>
              {row.can_answer
                ? row.late
                  ? t("rv.openLate", { date: day(row.round.self_due_on) })
                  : t(row.state === "draft" ? "rv.openContinue" : "rv.openTodo", { date: day(row.round.self_due_on) })
                : t("rv.openSent")}
            </span>
          </span>
        </CardButton>
      ))}

      {past.length > 0 && (
        <>
          <SectionHead count={past.length}>{t("rv.past")}</SectionHead>
          <ListCard>
            {past.map((row) => (
              <ListRow
                key={row.id}
                icon={row.acknowledged_at ? CheckCheck : Star}
                title={row.round.name}
                subtitle={[row.rating ? t("rv.ratingShort", { rating: row.rating }) : null, row.outcome && row.outcome !== "none" ? t(`rv.outcome.${row.outcome}` as RecordKey) : null].filter(Boolean).join(" · ")}
                value={row.acknowledged_at ? undefined : <Badge tone="accent">{t("rv.new")}</Badge>}
                onClick={() => openReview(row)}
              />
            ))}
          </ListCard>
        </>
      )}

      {goals.length > 0 && (
        <>
          <SectionHead count={goals.length}>{t("rv.myGoals")}</SectionHead>
          <ListCard>
            {goals.map((goal) => (
              <ListRow
                key={goal.id}
                icon={Target}
                title={goal.title}
                subtitle={[t("rv.goalBy", { date: day(goal.due_on) }), goal.round].filter(Boolean).join(" · ")}
                onClick={goal.review_id ? () => go.page("review", { id: goal.review_id! }) : undefined}
              />
            ))}
          </ListCard>
        </>
      )}
    </Screen>
  );
}
