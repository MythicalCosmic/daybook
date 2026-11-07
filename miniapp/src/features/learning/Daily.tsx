/**
 * The question of the day (docs/PLAN-LEARNING.md §4.8): answered right where it shows, on Home or
 * its own page (`daily`, the bot's "Answer in the app"), for every kind. True or false answers
 * with one tap; the others with "Answer". Then the result: right or not, the right answer, the
 * explanation, the points and the streak, with confetti and a success buzz when right.
 */
import { CircleCheck, CircleX, Flame, Lightbulb, Sparkles } from "lucide-react";
import { useRef, useState } from "react";

import { errorText } from "../../lib/actions";
import { useNavigation } from "../../state/navigation";
import { useMember } from "../../state/session";
import { useToast } from "../../state/toast";
import { haptic } from "../../telegram";
import { Badge, Button, celebrate, cx, EmptyState, LoadError, PageHeader, Screen, Skeleton } from "../../ui";
import type { PageProps } from "../registry";
import { useAnswerDaily, useDaily } from "./api";
import { isAnswered } from "./lib";
import { AnswerText, orderOf, QuestionHead, QuestionInput } from "./questions";
import { useLearningT } from "./text";
import type { Answer, DailyQuestion, DailyResult } from "./types";
import "./learning.css";

/** What a fresh answer brought (points and streak come only with the answer itself). */
type Outcome = Pick<DailyResult, "points" | "share">;

/** The day's question and its answer, or its result once answered. */
export function DailyBody({ daily, streak, onAnswered, compact = false }: { daily: DailyQuestion; streak: number | null; onAnswered?: () => void; compact?: boolean }) {
  const t = useLearningT();
  const member = useMember();
  const toast = useToast();
  const send = useAnswerDaily(member.companyId);
  const question = daily.question;
  const [answer, setAnswer] = useState<Answer | null>(() => (question.kind === "order" ? { order: orderOf(question, null) } : null));
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const button = useRef<HTMLDivElement>(null);

  const submit = (value: Answer | null) => {
    if (!value || send.isPending) return;
    send.mutate(
      { id: daily.id, answer: value },
      {
        onSuccess: (result) => {
          setOutcome({ points: result.points, share: result.share });
          if (result.correct) celebrate({ from: button.current });
          else haptic.notify("warning");
          onAnswered?.();
        },
        onError: (error) => {
          haptic.notify("error");
          toast(errorText(error, t, t("daily.failed")), { tone: "error" });
        },
      },
    );
  };

  if (daily.answered) return <DailyResultView daily={daily} streak={streak} outcome={outcome} compact={compact} />;
  return (
    <div className="lrn-daily-body" ref={button}>
      <QuestionHead question={question} compact={compact} />
      <QuestionInput
        question={question}
        value={answer}
        disabled={send.isPending}
        onChange={(next) => {
          setAnswer(next);
          // Two big buttons are the answer itself: one tap, as in the bot.
          if (question.kind === "true_false") submit(next);
        }}
      />
      {question.kind !== "true_false" && (
        <Button variant="primary" block loading={send.isPending} disabled={!isAnswered(question, answer)} onClick={() => submit(answer)}>
          {t("daily.answer")}
        </Button>
      )}
    </div>
  );
}

function DailyResultView({ daily, streak, outcome, compact }: { daily: DailyQuestion; streak: number | null; outcome: Outcome | null; compact: boolean }) {
  const t = useLearningT();
  const right = Boolean(daily.correct);
  const partly = !right && (outcome?.share ?? 0) > 0;
  return (
    <div className={cx("lrn-daily-result", right ? "lrn-daily-result--right" : "lrn-daily-result--wrong")} role="status">
      <span className="lrn-daily-verdict">
        {right ? <CircleCheck size={24} strokeWidth={2.5} aria-hidden /> : <CircleX size={24} strokeWidth={2.5} aria-hidden />}
        <span>{right ? t("daily.right") : partly ? t("daily.partly") : t("daily.wrong")}</span>
        {outcome?.points ? (
          <Badge tone="accent" size="small" icon={Sparkles}>
            {t("points", { count: outcome.points })}
          </Badge>
        ) : null}
      </span>
      <p className={cx("lrn-qtext", compact && "lrn-qtext--small")}>{daily.question.text}</p>
      {daily.answer && (
        <span className="lrn-review-line">
          <span className="lrn-review-label">{t("answer.yours")}</span>
          <AnswerText question={daily.question} answer={daily.answer} />
        </span>
      )}
      {!right && daily.right_answer && (
        <span className="lrn-review-line lrn-review-line--right">
          <span className="lrn-review-label">{t("answer.right")}</span>
          <AnswerText question={daily.question} answer={daily.right_answer} />
        </span>
      )}
      {daily.explanation && (
        <p className="lrn-explain">
          <Lightbulb size={16} strokeWidth={2.5} aria-hidden />
          <span>{daily.explanation}</span>
        </p>
      )}
      {streak ? (
        <span className="lrn-streak">
          <Flame size={16} strokeWidth={2.6} aria-hidden />
          {t("streak", { count: streak })}
        </span>
      ) : null}
    </div>
  );
}

/** `daily`: the question of the day on its own page. */
export default function DailyPage(_props: PageProps) {
  const t = useLearningT();
  const member = useMember();
  const navigation = useNavigation();
  const daily = useDaily(member.companyId);
  const view = daily.data;
  return (
    <Screen variant="detail">
      <PageHeader kicker={t("title")} title={t("daily.title")} onBack={navigation.pop} />
      {!view ? (
        daily.isError ? (
          <LoadError error={daily.error} onRetry={() => void daily.refetch()} onBack={navigation.pop} />
        ) : (
          <div className="lrn-stack" aria-hidden>
            <Skeleton height={22} width="80%" radius={8} />
            <Skeleton height={60} />
            <Skeleton height={60} />
            <Skeleton height={60} />
          </div>
        )
      ) : view.daily ? (
        <div className="card lrn-daily-page">
          <DailyBody daily={view.daily} streak={view.streak} />
        </div>
      ) : (
        <EmptyState icon={Lightbulb} tone="sage" title={t("daily.none.title")} body={t("daily.none.body")} />
      )}
    </Screen>
  );
}
