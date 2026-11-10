/**
 * What performance reviews put on Home and Me: a card while a round waits for my answers ("answer
 * by Friday"), or when a published review waits for me to read it; Me's "My reviews" row with a
 * bubble for both.
 */
import { ClipboardPen, Star } from "lucide-react";

import { useI18n } from "../../i18n";
import { dayMonth } from "../../lib/time";
import { Banner } from "../../ui";
import type { MeItemStatus, SlotProps } from "../registry";
import { useFeatureOpen } from "../useFeatureOpen";
import { noBreak, useMyReviews, waitingCount } from "./reviews";
import { useRecordT } from "./text";

export function ReviewCard({ member }: SlotProps) {
  const t = useRecordT();
  const { locale } = useI18n();
  const go = useFeatureOpen("lifecycle");
  const reviews = useMyReviews(member.companyId);
  const toAnswer = reviews.data?.open.find((row) => row.can_answer);
  const unread = reviews.data?.past.find((row) => !row.acknowledged_at);
  if (toAnswer) {
    return (
      <Banner
        size="lg"
        iconTone="accent"
        icon={ClipboardPen}
        title={t("rv.homeTitle")}
        body={toAnswer.late ? t("rv.homeLate") : t("rv.homeBody", { date: noBreak(dayMonth(toAnswer.round.self_due_on, "UTC", locale)) })}
        wrap
        onClick={() => go.page("review", { id: toAnswer.id })}
      />
    );
  }
  if (unread) {
    return <Banner size="lg" iconTone="sage" icon={Star} title={t("rv.homeReady")} body={noBreak(unread.round.name)} wrap onClick={() => go.page("review", { id: unread.id })} />;
  }
  return null;
}

export function useReviewsStatus({ member }: SlotProps): MeItemStatus {
  const reviews = useMyReviews(member.companyId);
  return { badge: waitingCount(reviews.data) || null };
}
