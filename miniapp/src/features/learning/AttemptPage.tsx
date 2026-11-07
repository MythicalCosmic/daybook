/**
 * An attempt at a quiz (docs/PLAN-LEARNING.md §4.7, §12.1). While it runs: one question per screen,
 * a strip of every question (answered ones filled), the time left when there is a limit, each
 * answer saved as it is given (through the retry queue), Back and Next, and Finish (asking first,
 * and saying how many have no answer). At the deadline it finishes by itself: the server grades
 * what was saved. Once over: the score ring, passed or not, the points, the review the quiz
 * allows, "Try again" when allowed (or when it will be), and back to the course.
 */
import { useQueryClient } from "@tanstack/react-query";
import { CircleCheck, CircleX, Hourglass, Lightbulb, Sparkles, Timer, WifiOff, Check as CheckIcon } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { api, ApiError } from "../../api/client";
import { useI18n } from "../../i18n";
import { errorText } from "../../lib/actions";
import { useNow } from "../../lib/useNow";
import { useNavigation } from "../../state/navigation";
import { useMember } from "../../state/session";
import { useToast } from "../../state/toast";
import { confirm, haptic } from "../../telegram";
import { Badge, Banner, BottomBar, Card, celebrate, cx, LoadError, PageHeader, ProgressRing, Screen, SectionHead, Skeleton } from "../../ui";
import type { PageProps } from "../registry";
import { afterAttempt, answersOf, finishAttempt, isPlay, learningKeys, saveAnswer, useAttempt, useQuiz, useStartAttempt } from "./api";
import { countdown, isAhead, isAnswered, scoreText, sharePercent, whenText } from "./lib";
import { backToCourse, numberParam } from "./parts";
import { AnswerText, orderOf, QuestionHead, QuestionInput, type Commit } from "./questions";
import { drain, useQueueState } from "./queue";
import { attemptPage } from "./QuizPage";
import { useLearningT } from "./text";
import type { Answer, AttemptPlay, AttemptResult, AttemptView, QuestionPlay, ReviewItem } from "./types";
import "./learning.css";

/** Typing is saved this long after the last key (a tap at once). */
export const TYPING_SAVE_MS = 700;
/** Up to this many questions the strip is a row of buttons; beyond, a picture of progress. */
const TAPPABLE_STRIP = 15;

export default function AttemptPage({ params }: PageProps) {
  const member = useMember();
  const navigation = useNavigation();
  const id = Number(params.id);
  const attempt = useAttempt(member.companyId, id);

  if (!attempt.data) {
    return (
      <Screen variant="detail">
        {attempt.isError ? (
          <LoadError error={attempt.error} onRetry={() => void attempt.refetch()} onBack={navigation.pop} />
        ) : (
          <div className="lrn-stack" aria-hidden>
            <Skeleton height={30} width="56%" radius={10} />
            <Skeleton height={12} radius={6} />
            <Skeleton height={260} />
          </div>
        )}
      </Screen>
    );
  }
  return isPlay(attempt.data) ? <Player key={`play-${id}`} play={attempt.data} params={params} /> : <Result result={attempt.data} params={params} />;
}

// — the player —

function Player({ play, params }: { play: AttemptPlay; params: PageProps["params"] }) {
  const t = useLearningT();
  const member = useMember();
  const navigation = useNavigation();
  const toast = useToast();
  const client = useQueryClient();
  const company = member.companyId;
  const quizId = numberParam(params, "quiz") ?? play.quiz.id;
  const questions = play.questions;
  const [answers, setAnswers] = useState<Record<string, Answer>>(() => ({ ...play.answers }));
  const [index, setIndex] = useState(() => Math.max(0, questions.findIndex((question) => !isAnswered(question, play.answers[String(question.id)]))));
  const [finishing, setFinishing] = useState(false);
  const typing = useRef(new Map<number, { timer: ReturnType<typeof setTimeout>; question: QuestionPlay; answer: Answer }>());
  const saving = useQueueState(answersOf(play.id));
  const deadline = play.deadline_at ? Date.parse(play.deadline_at) : null;
  const now = useNow(deadline ? 1_000 : 60_000);
  const left = deadline === null ? null : (deadline - now.getTime()) / 1000;
  const timeUp = left !== null && left <= 0;
  const body = useRef<HTMLDivElement>(null);
  const finished = useRef(false);
  const question = questions[Math.min(index, questions.length - 1)];

  const send = (target: QuestionPlay, answer: Answer) => {
    saveAnswer(company, play.id, target.id, answer).catch((error: unknown) => {
      // Refused after the deadline: the attempt is being graded; the page shows its result.
      if (error instanceof ApiError && error.status === 400 && !finished.current) void finish(true);
    });
  };
  const change = (target: QuestionPlay, answer: Answer, commit: Commit) => {
    setAnswers((before) => ({ ...before, [String(target.id)]: answer }));
    const waiting = typing.current.get(target.id);
    if (waiting) clearTimeout(waiting.timer);
    typing.current.delete(target.id);
    if (commit === "now") {
      send(target, answer);
      return;
    }
    const timer = setTimeout(() => {
      typing.current.delete(target.id);
      send(target, answer);
    }, TYPING_SAVE_MS);
    typing.current.set(target.id, { timer, question: target, answer });
  };
  const flushTyping = () => {
    for (const waiting of typing.current.values()) {
      clearTimeout(waiting.timer);
      send(waiting.question, waiting.answer);
    }
    typing.current.clear();
  };
  /** An order question left as shown is answered with that order (it may well be right). */
  const withShownOrder = (target: QuestionPlay, current: Record<string, Answer>): Record<string, Answer> => {
    if (target.kind !== "order" || current[String(target.id)]) return current;
    const answer: Answer = { order: orderOf(target, null) };
    change(target, answer, "now");
    return { ...current, [String(target.id)]: answer };
  };

  const goTo = (next: number) => {
    if (next < 0 || next >= questions.length || next === index) return;
    flushTyping();
    withShownOrder(question, answers);
    haptic.select();
    setIndex(next);
  };
  // A new question starts at its top, however far the last one was scrolled.
  useEffect(() => {
    const screen = body.current?.closest(".screen");
    if (screen && typeof screen.scrollTo === "function") screen.scrollTo({ top: 0 });
  }, [index]);
  useEffect(() => () => typing.current.forEach((waiting) => clearTimeout(waiting.timer)), []);

  const finish = async (auto = false) => {
    if (finished.current) return;
    flushTyping();
    const current = withShownOrder(question, answers);
    if (!auto) {
      const unanswered = questions.filter((item) => !isAnswered(item, current[String(item.id)])).length;
      const ok = await confirm(unanswered ? t("player.unanswered", { count: unanswered }) : t("player.confirm"));
      if (!ok) return;
    }
    finished.current = true;
    setFinishing(true);
    const saved = await drain(answersOf(play.id), auto ? 4_000 : 8_000);
    if (!saved && !auto) {
      finished.current = false;
      setFinishing(false);
      haptic.notify("error");
      toast(t("player.notSent"), { tone: "error" });
      return;
    }
    let result: AttemptResult;
    try {
      result = await finishAttempt(company, play.id);
    } catch (error) {
      // Over already (the deadline, another phone): the attempt itself reads as its result.
      const view = await api<AttemptView>(`/companies/${company}/learning/attempts/${play.id}/`).catch(() => null);
      if (view && !isPlay(view)) {
        result = view;
      } else {
        finished.current = false;
        setFinishing(false);
        haptic.notify("error");
        toast(errorText(error, t, t("player.finishFailed")), { tone: "error" });
        return;
      }
    }
    if (result.passed) celebrate();
    else haptic.notify("warning");
    afterAttempt(client, company, play.id, result, quizId);
  };

  // Out of time: what was saved is graded, here and on the server.
  useEffect(() => {
    if (timeUp && !finished.current) void finish(true);
  }, [timeUp]);

  const answeredCount = questions.filter((item) => isAnswered(item, answers[String(item.id)])).length;
  const last = index === questions.length - 1;
  const tappable = questions.length <= TAPPABLE_STRIP;

  return (
    <>
      <Screen variant="detail">
        <PageHeader
          kicker={`${play.quiz.emoji ? `${play.quiz.emoji} ` : ""}${play.quiz.title}`}
          title={t("player.count", { n: index + 1, total: questions.length })}
          onBack={navigation.pop}
          actions={
            left !== null ? (
              <span className={cx("lrn-timer num", left < 60 && "lrn-timer--low")} role="timer" aria-label={t("player.timeLeft")}>
                <Timer size={16} strokeWidth={2.6} aria-hidden />
                {countdown(left)}
              </span>
            ) : undefined
          }
        />
        <div className="lrn-strip" role="group" aria-label={t("player.answered", { done: answeredCount, total: questions.length })}>
          {questions.map((item, at) => {
            const classes = cx("lrn-strip-seg", isAnswered(item, answers[String(item.id)]) && "lrn-strip-seg--done", at === index && "lrn-strip-seg--current");
            return tappable ? (
              <button key={item.id} type="button" className={classes} aria-label={t("player.goTo", { n: at + 1 })} aria-current={at === index ? "step" : undefined} onClick={() => goTo(at)} />
            ) : (
              <span key={item.id} className={classes} aria-hidden />
            );
          })}
        </div>
        {timeUp && <Banner tone="accent" icon={Hourglass} title={t("player.timeUp")} />}
        <div ref={body} className="lrn-qcard card">
          <QuestionHead question={question} />
          <QuestionInput key={question.id} question={question} value={answers[String(question.id)]} disabled={finishing || timeUp} onChange={(answer, commit) => change(question, answer, commit)} />
          <span className="lrn-qpoints">{t("q_points", { count: question.points })}</span>
        </div>
        <SaveLine pending={saving.pending} failing={saving.failing} any={answeredCount > 0} />
      </Screen>
      <BottomBar
        primary={
          last
            ? { text: t("player.finish"), onClick: () => void finish(), loading: finishing, disabled: timeUp && !finishing }
            : { text: t("player.next"), onClick: () => goTo(index + 1), disabled: finishing }
        }
        secondary={{ text: t("player.back"), onClick: () => goTo(index - 1), disabled: index === 0 || finishing }}
      />
    </>
  );
}

function SaveLine({ pending, failing, any }: { pending: number; failing: boolean; any: boolean }) {
  const t = useLearningT();
  if (failing) {
    return (
      <p className="lrn-save lrn-save--offline" role="status">
        <WifiOff size={15} strokeWidth={2.5} aria-hidden />
        {t("player.offline")}
      </p>
    );
  }
  if (!any && !pending) return null;
  return (
    <p className="lrn-save" role="status">
      {pending ? null : <CheckIcon size={15} strokeWidth={2.8} aria-hidden />}
      {t(pending ? "player.saving" : "player.saved")}
    </p>
  );
}

// — the result —

function Result({ result, params }: { result: AttemptResult; params: PageProps["params"] }) {
  const t = useLearningT();
  const { locale } = useI18n();
  const member = useMember();
  const navigation = useNavigation();
  const toast = useToast();
  const client = useQueryClient();
  const now = useNow();
  const quizId = numberParam(params, "quiz");
  const assignment = numberParam(params, "assignment");
  const course = numberParam(params, "course");
  const entry = numberParam(params, "entry");
  const quiz = useQuiz(member.companyId, quizId ?? 0, { assignment, entry });
  const start = useStartAttempt(member.companyId, quizId ?? 0);
  const expired = result.state === "expired";
  const title = result.passed ? t("result.passed") : t("result.failed");
  const retryAt = quiz.data && !quiz.data.can_start && quiz.data.retry_at && isAhead(quiz.data.retry_at, now) ? quiz.data.retry_at : null;
  const canRetry = Boolean(quizId && quiz.data?.can_start && !quiz.data.in_progress);

  const retry = () =>
    start.mutate(
      { assignment, entry },
      {
        onSuccess: (play) => {
          haptic.impact("medium");
          client.setQueryData(learningKeys.attempt(member.companyId, play.id), play);
          navigation.replace(attemptPage(play.id, quizId!, { assignment, course, entry }));
        },
        onError: (error) => {
          haptic.notify("error");
          toast(errorText(error, t, t("quiz.startFailed")), { tone: "error" });
          void quiz.refetch();
        },
      },
    );

  return (
    <>
      <Screen variant="detail">
        <PageHeader kicker={quiz.data ? `${quiz.data.emoji ? `${quiz.data.emoji} ` : ""}${quiz.data.title}` : t("step.quiz")} title={title} onBack={navigation.pop} />
        <Card className={cx("lrn-result", result.passed ? "lrn-result--passed" : "lrn-result--failed")}>
          <ProgressRing value={result.percent} total={100} size={124} stroke={11} tone={result.passed ? "sage" : "accent"} label={`${result.percent}%`} ariaLabel={t("result.ring", { percent: result.percent })} />
          <span className="lrn-result-text">
            <span className="lrn-result-score num">{t("result.score", { score: scoreText(result.score, locale), max: scoreText(result.max_score, locale) })}</span>
            {quiz.data && <span className="lrn-result-pass">{t("result.passMark", { percent: quiz.data.pass_percent })}</span>}
            {result.points ? (
              <Badge tone="accent" icon={Sparkles}>
                {t("points", { count: result.points })}
              </Badge>
            ) : null}
          </span>
        </Card>
        {expired && <Banner icon={Hourglass} title={t("result.expired")} />}
        {result.course_step_done && <Banner tone="sage" icon={CircleCheck} title={t("result.stepDone")} />}
        {retryAt && <p className="lrn-note">{t("quiz.retryAt", { when: whenText(retryAt, now, member.timeZone, locale, t) })}</p>}
        <SectionHead size="small">{t("result.review")}</SectionHead>
        {result.review ? (
          <div className="lrn-stack">
            {result.review.map((item, at) => (
              <ReviewCard key={`${item.question.id}-${at}`} item={item} index={at} />
            ))}
          </div>
        ) : (
          <p className="lrn-note">{t("result.reviewHidden")}</p>
        )}
      </Screen>
      <BottomBar
        primary={course ? { text: t("course.back"), onClick: () => backToCourse(navigation, course) } : { text: t("result.done"), onClick: navigation.pop }}
        secondary={canRetry ? { text: t("result.tryAgain"), onClick: retry, loading: start.isPending } : undefined}
      />
    </>
  );
}

function ReviewCard({ item, index }: { item: ReviewItem; index: number }) {
  const t = useLearningT();
  const status = item.correct ? "right" : item.share > 0 ? "partial" : "wrong";
  return (
    <Card className={cx("lrn-review", `lrn-review--${status}`)}>
      <span className="lrn-review-head">
        <span className="lrn-review-n num">{index + 1}</span>
        <Badge tone={status === "wrong" ? "accent" : "sage"} size="small" icon={status === "wrong" ? CircleX : CircleCheck}>
          {status === "right" ? t("result.right") : status === "partial" ? t("result.partial", { percent: sharePercent(item.share) }) : t("result.wrong")}
        </Badge>
      </span>
      <p className="lrn-qtext lrn-qtext--small">{item.question.text}</p>
      <span className="lrn-review-line">
        <span className="lrn-review-label">{t("answer.yours")}</span>
        <AnswerText question={item.question} answer={item.answer} />
      </span>
      {!item.correct && item.right_answer && (
        <span className="lrn-review-line lrn-review-line--right">
          <span className="lrn-review-label">{t("answer.right")}</span>
          <AnswerText question={item.question} answer={item.right_answer} />
        </span>
      )}
      {item.explanation && (
        <p className="lrn-explain">
          <Lightbulb size={16} strokeWidth={2.5} aria-hidden />
          <span>{item.explanation}</span>
        </p>
      )}
    </Card>
  );
}
