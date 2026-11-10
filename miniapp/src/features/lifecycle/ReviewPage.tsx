/**
 * One of my performance reviews (the bot's `lifecycle.review:<id>` link, or My reviews):
 * - while the round is open and I haven't sent it: the questions one screen at a time (a rating
 *   from 1 to 5 with its words, a comment if I want; or my own words), my draft saved as I go,
 *   then a last look at my answers and Send;
 * - sent: when I sent it, and that my manager answers next;
 * - published: my manager's rating and summary, what follows (a raise, a bonus, a promotion, an
 *   improvement plan, and where its approval stands), their answer beside mine for each question,
 *   my numbers for the period, and "Tanishdim" once I have read it.
 * Nobody else's review is ever here.
 */
import { Award, CalendarClock, Check, CheckCheck, ChevronLeft, ChevronRight, CircleCheck, Gift, Hourglass, MessageSquareText, Minus, PenLine, Send, Target, TrendingUp } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { useI18n } from "../../i18n";
import { formatMoney } from "../../lib/money";
import { capitalise, dayMonthLong, dayMonthYear, weekdayLong } from "../../lib/time";
import { useNavigation } from "../../state/navigation";
import { useMember } from "../../state/session";
import { confirm, haptic } from "../../telegram";
import { Badge, Banner, BottomBar, Card, LoadError, PageHeader, ProgressBar, Screen, ScreenSkeleton, SectionHead, Textarea, cx } from "../../ui";
import type { PageProps } from "../registry";
import { useFeedback } from "../states";
import {
  answered,
  cleanAnswers,
  resumeStep,
  unrated,
  useAcknowledgeReview,
  useMyReview,
  useSaveAnswers,
  useSendAnswers,
  type MyReview,
  type ReviewAnswers,
  type ReviewOutcome,
  type ReviewQuestion,
} from "./reviews";
import { keepTogether, useRecordT, type RecordKey, type RecordT } from "./text";
import "./lifecycle.css";

const MAX_ANSWER = 2000;
const RATINGS = [1, 2, 3, 4, 5] as const;
const OUTCOME_ICONS: Record<ReviewOutcome, typeof Minus> = { none: Minus, raise: TrendingUp, bonus: Gift, promotion: Award, improvement_plan: Target };

export default function ReviewPage({ params }: PageProps) {
  const t = useRecordT();
  const member = useMember();
  const navigation = useNavigation();
  const id = Number(params.id);
  const review = useMyReview(member.companyId, id);
  const header = <PageHeader kicker={member.company.name} title={review.data?.round.name ?? t("rv.title")} subtitle={t("rv.subtitle")} onBack={navigation.pop} />;

  if (!review.data) {
    return (
      <Screen variant="detail">
        {header}
        {review.isError ? <LoadError error={review.error} onRetry={() => void review.refetch()} onBack={navigation.pop} /> : <ScreenSkeleton variant="detail" delay={150} />}
      </Screen>
    );
  }
  const data = review.data;
  if (data.can_answer) return <Answering key={data.id} review={data} />;
  if (data.state === "published") return <Published review={data} header={header} />;
  return <Sent review={data} header={header} />;
}

function longDay(day: string, locale: string): string {
  return keepTogether(capitalise(`${weekdayLong(day, "UTC", locale)}, ${dayMonthLong(day, "UTC", locale)}`));
}

function ratingWord(t: RecordT, rating: number): string {
  return t(`rv.word${rating}` as RecordKey);
}

// — Answering, one question at a time —

function Answering({ review }: { review: MyReview }) {
  const t = useRecordT();
  const { locale } = useI18n();
  const member = useMember();
  const navigation = useNavigation();
  const feedback = useFeedback();
  const questions = review.questions;
  const save = useSaveAnswers(member.companyId, review.id);
  const send = useSendAnswers(member.companyId, review.id);
  const [answers, setAnswers] = useState<ReviewAnswers>(() => ({ ...review.answers }));
  // 0 is the start, 1…N the questions, N + 1 the last look before sending.
  const [step, setStep] = useState(() => (review.state === "draft" ? Math.min(questions.length, resumeStep(questions, review.answers)) + 1 : 0));
  const dirty = useRef(false);

  const keep = () => {
    if (!dirty.current || save.isPending) return;
    dirty.current = false;
    save.mutate(cleanAnswers(answers));
  };
  // Leaving the page keeps what was typed.
  const latest = useRef(answers);
  latest.current = answers;
  useEffect(
    () => () => {
      if (dirty.current) save.mutate(cleanAnswers(latest.current));
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );

  const set = (questionId: string, patch: { rating?: number | null; text?: string }) => {
    dirty.current = true;
    setAnswers((current) => ({ ...current, [questionId]: { ...current[questionId], ...patch } }));
  };
  const go = (next: number) => {
    keep();
    setStep(Math.max(0, Math.min(questions.length + 1, next)));
    window.scrollTo?.({ top: 0 });
  };
  const missing = unrated(questions, answers);
  const submit = async () => {
    if (missing.length || send.isPending) return;
    if (!(await confirm(t("rv.sendConfirm")))) return;
    send.mutate(cleanAnswers(answers), {
      onSuccess: () => {
        dirty.current = false;
        haptic.notify("success");
      },
      onError: feedback.fail,
    });
  };

  const header = <PageHeader kicker={member.company.name} title={review.round.name} subtitle={t("rv.dueLine", { date: longDay(review.round.self_due_on, locale) })} onBack={navigation.pop} />;

  if (step === 0) {
    return (
      <>
        <Screen variant="detail">
          {header}
          <Card tone="accent" className="rv-intro">
            <MessageSquareText size={28} aria-hidden="true" />
            <div className="rv-intro-title">{t("rv.introTitle")}</div>
            <p className="ft-text">{t("rv.introBody", { count: questions.length })}</p>
            <div className="rv-intro-facts">
              <span>
                <CalendarClock size={15} aria-hidden="true" /> {t("rv.period", { from: dayMonthYear(review.round.period_start, "UTC", locale, new Date()), to: dayMonthYear(review.round.period_end, "UTC", locale, new Date()) })}
              </span>
              <span className={cx(review.late && "lc-warn")}>
                <Hourglass size={15} aria-hidden="true" /> {review.late ? t("rv.lateLine", { date: longDay(review.round.self_due_on, locale) }) : t("rv.dueLine", { date: longDay(review.round.self_due_on, locale) })}
              </span>
            </div>
          </Card>
          <p className="ft-quiet lc-pad">{t("rv.privacy")}</p>
        </Screen>
        <BottomBar primary={{ text: t("rv.start"), onClick: () => go(1), icon: ChevronRight, shine: true }} />
      </>
    );
  }

  if (step > questions.length) {
    return (
      <>
        <Screen variant="detail">
          {header}
          <SectionHead>{t("rv.checkTitle")}</SectionHead>
          <p className="ft-quiet">{missing.length ? t("rv.checkMissing", { count: missing.length }) : t("rv.checkBody")}</p>
          <div className="rv-check">
            {questions.map((question, index) => (
              <button key={question.id} type="button" className={cx("rv-check-row", missing.includes(question.id) && "rv-check-row--missing")} onClick={() => go(index + 1)}>
                <span className="rv-check-number">{index + 1}</span>
                <span className="rv-check-main">
                  <span className="rv-check-question">{question.text}</span>
                  <span className="rv-check-answer">{answerLine(t, question, answers)}</span>
                </span>
                <PenLine size={16} aria-hidden="true" />
              </button>
            ))}
          </div>
        </Screen>
        <BottomBar
          primary={{ text: t("rv.send"), onClick: () => void submit(), loading: send.isPending, disabled: missing.length > 0, icon: Send, shine: true }}
          secondary={{ text: t("rv.back"), onClick: () => go(questions.length) }}
        />
      </>
    );
  }

  const question = questions[step - 1]!;
  const answer = answers[question.id] ?? {};
  const canGoOn = question.kind === "text" || !!answer.rating;
  return (
    <>
      <Screen variant="detail">
        {header}
        <ProgressBar value={step} total={questions.length} label={t("rv.questionOf", { number: step, total: questions.length })} valueLabel={t("rv.answeredOf", { count: answered(questions, answers) })} size="sm" />
        <div className="rv-question" data-question={question.id}>
          <div className="rv-question-text">{question.text}</div>
          {question.kind === "rating" ? (
            <>
              <div className="rv-scale" role="radiogroup" aria-label={question.text}>
                {RATINGS.map((value) => (
                  <button
                    key={value}
                    type="button"
                    role="radio"
                    aria-checked={answer.rating === value}
                    className={cx("rv-scale-button", answer.rating === value && "rv-scale-button--on", answer.rating === value && `rv-tone-${value}`)}
                    onClick={() => {
                      haptic("light");
                      set(question.id, { rating: value });
                    }}
                  >
                    <span className="rv-scale-number">{value}</span>
                    <span className="rv-scale-word">{ratingWord(t, value)}</span>
                  </button>
                ))}
              </div>
              <Textarea value={answer.text ?? ""} onChange={(event) => set(question.id, { text: event.target.value })} rows={3} maxLength={MAX_ANSWER} placeholder={t("rv.commentPlaceholder")} />
            </>
          ) : (
            <Textarea value={answer.text ?? ""} onChange={(event) => set(question.id, { text: event.target.value })} rows={6} maxLength={MAX_ANSWER} placeholder={t("rv.textPlaceholder")} />
          )}
          {save.isPending && <p className="ft-hint">{t("rv.saving")}</p>}
        </div>
      </Screen>
      <BottomBar
        primary={{ text: step === questions.length ? t("rv.toCheck") : t("rv.next"), onClick: () => go(step + 1), disabled: !canGoOn, icon: ChevronRight }}
        secondary={{ text: t("rv.back"), onClick: () => go(step - 1), icon: ChevronLeft }}
      />
    </>
  );
}

function answerLine(t: RecordT, question: ReviewQuestion, answers: ReviewAnswers): string {
  const answer = answers[question.id];
  if (question.kind === "rating") {
    if (!answer?.rating) return t("rv.noRating");
    return `${answer.rating} · ${ratingWord(t, answer.rating)}${answer.text?.trim() ? ` · ${answer.text.trim()}` : ""}`;
  }
  return answer?.text?.trim() || t("rv.noAnswer");
}

// — Sent, waiting for my manager —

function Sent({ review, header }: { review: MyReview; header: ReactNode }) {
  const t = useRecordT();
  const { locale } = useI18n();
  const member = useMember();
  // Just sent (this visit): a thank-you; later visits say what comes next.
  const [justSent] = useState(() => !!review.self_sent_at && Date.now() - new Date(review.self_sent_at).getTime() < 5 * 60_000);
  return (
    <Screen variant="detail">
      {header}
      {justSent ? (
        <Card tone="sage" className="rv-done">
          <CircleCheck size={34} aria-hidden="true" />
          <div className="rv-done-title">{t("rv.sentTitle")}</div>
          <p className="ft-text">{t("rv.sentBody")}</p>
        </Card>
      ) : (
        <Banner tone="sage" icon={Check} title={t("rv.waitingTitle")} body={review.self_sent_at ? t("rv.waitingBody", { date: dayMonthYear(review.self_sent_at, member.timeZone, locale, new Date()) }) : undefined} />
      )}
      <SectionHead>{t("rv.yourAnswers")}</SectionHead>
      <div className="rv-check">
        {review.questions.map((question, index) => (
          <div key={question.id} className="rv-check-row rv-check-row--static">
            <span className="rv-check-number">{index + 1}</span>
            <span className="rv-check-main">
              <span className="rv-check-question">{question.text}</span>
              <span className="rv-check-answer">{answerLine(t, question, review.answers)}</span>
            </span>
          </div>
        ))}
      </div>
    </Screen>
  );
}

// — Published —

function Published({ review, header }: { review: MyReview; header: ReactNode }) {
  const t = useRecordT();
  const { locale, lang } = useI18n();
  const member = useMember();
  const feedback = useFeedback();
  const acknowledge = useAcknowledgeReview(member.companyId, review.id);
  const rating = review.rating ?? 0;
  const outcome = review.outcome ?? "none";
  const Icon = OUTCOME_ICONS[outcome];
  const read = () => {
    if (acknowledge.isPending) return;
    acknowledge.mutate(undefined, { onSuccess: () => feedback.ok(t("rv.readToast")), onError: feedback.fail });
  };
  const stateWord = review.change?.status ?? (review.bonus ? { proposed: "waiting", approved: "approved" }[review.bonus.status] ?? "rejected" : null);

  return (
    <>
      <Screen variant="detail">
        {header}
        <Card className="rv-hero">
          <div className={cx("rv-hero-score", `rv-tone-${rating}`)}>
            <span className="rv-hero-number">{rating || "—"}</span>
            <span className="rv-hero-of">/ 5</span>
          </div>
          <div className="rv-hero-main">
            <div className="rv-hero-word">{rating ? ratingWord(t, rating) : "—"}</div>
            <div className="ft-quiet">{t("rv.byLine", { name: review.reviewer ?? "—", date: review.published_at ? dayMonthYear(review.published_at, member.timeZone, locale, new Date()) : "" })}</div>
          </div>
        </Card>
        {review.summary && (
          <Card tone="outline" className="lc-yours">
            <div className="lc-yours-head">{t("rv.summary")}</div>
            <p className="ft-text">{review.summary}</p>
          </Card>
        )}

        <SectionHead>{t("rv.follows")}</SectionHead>
        <Card className="rv-outcome">
          <span className="circle rv-outcome-icon">
            <Icon size={20} aria-hidden="true" />
          </span>
          <div className="rv-outcome-main">
            <div className="rv-outcome-title">{t(`rv.outcome.${outcome}` as RecordKey)}</div>
            <div className="ft-quiet">{outcomeLine(t, review, locale, lang)}</div>
            {stateWord && <Badge tone={stateWord === "rejected" ? "neutral" : stateWord === "waiting" ? "accent" : "sage"}>{t(`rv.state.${stateWord}` as RecordKey)}</Badge>}
          </div>
        </Card>

        {review.goals.length > 0 && (
          <>
            <SectionHead>{t("rv.goals")}</SectionHead>
            <div className="rv-goals">
              {review.goals.map((goal) => (
                <div key={goal.id} className={cx("rv-goal", goal.status === "done" && "rv-goal--done")}>
                  {goal.status === "done" ? <CheckCheck size={18} aria-hidden="true" /> : <Target size={18} aria-hidden="true" />}
                  <div className="rv-goal-main">
                    <div className="rv-goal-title">{goal.title}</div>
                    <div className="ft-quiet">
                      {t("rv.goalBy", { date: dayMonthYear(goal.due_on, "UTC", locale, new Date()) })} · {t(`rv.goal.${goal.status}` as RecordKey)}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </>
        )}

        <SectionHead>{t("rv.compare")}</SectionHead>
        <div className="rv-compare">
          {review.questions.map((question, index) => {
            const mine = review.answers[question.id];
            const theirs = review.manager_answers?.[question.id];
            return (
              <Card key={question.id} padding="sm" className="rv-compare-card">
                <div className="rv-compare-question">
                  {index + 1}. {question.text}
                </div>
                {question.kind === "rating" ? (
                  <div className="rv-compare-row">
                    <span>
                      {t("rv.mine")}: <b>{mine?.rating ?? "—"}</b>
                    </span>
                    <span>
                      {t("rv.theirs")}: <b>{theirs?.rating ?? "—"}</b>
                    </span>
                  </div>
                ) : null}
                {theirs?.text && <p className="ft-text rv-compare-note">{theirs.text}</p>}
              </Card>
            );
          })}
        </div>

        {review.kpis && (
          <>
            <SectionHead>{t("rv.numbers")}</SectionHead>
            <Card className="rv-numbers">
              {review.kpis.tasks.total > 0 && <Fact label={t("rv.numbersTasks")} value={`${review.kpis.tasks.on_time_percent ?? "0"}%`} />}
              {review.kpis.attendance && <Fact label={t("rv.numbersLate")} value={String(review.kpis.attendance.late_arrivals)} />}
              {review.kpis.attendance && <Fact label={t("rv.numbersAbsent")} value={String(review.kpis.attendance.absent_days)} />}
              <Fact label={t("rv.numbersRecords")} value={String(review.kpis.discipline.records)} />
              {review.kpis.learning && <Fact label={t("rv.numbersCourses")} value={String(review.kpis.learning.completed)} />}
            </Card>
          </>
        )}
        {review.acknowledged_at && <p className="ft-hint lc-pad">{t("rv.readOn", { date: dayMonthYear(review.acknowledged_at, member.timeZone, locale, new Date()) })}</p>}
      </Screen>
      {!review.acknowledged_at && <BottomBar primary={{ text: t("rv.read"), onClick: read, loading: acknowledge.isPending, icon: CheckCheck }} />}
    </>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="rv-fact">
      <span className="rv-fact-value">{value}</span>
      <span className="rv-fact-label">{label}</span>
    </div>
  );
}

function outcomeLine(t: RecordT, review: MyReview, locale: string, lang: Parameters<typeof formatMoney>[2]): string {
  const day = (value: string | null | undefined) => (value ? dayMonthYear(value, "UTC", locale, new Date()) : "—");
  const change = review.change;
  switch (review.outcome) {
    case "raise":
      if (change?.pay_after && change.currency) return t("rv.raisePay", { amount: formatMoney(change.pay_after, change.currency, lang), date: day(change.effective_on) });
      return t("rv.raiseLine", { percent: review.raise_percent ?? "—", date: day(change?.effective_on) });
    case "promotion":
      return t("rv.promotionLine", { position: change?.position ?? "—", date: day(change?.effective_on) });
    case "bonus":
      return review.bonus ? t("rv.bonusLine", { amount: formatMoney(review.bonus.amount, review.bonus.currency, lang) }) : "";
    case "improvement_plan":
      return t("rv.planLine", { count: review.goals.length });
    default:
      return t("rv.noneLine");
  }
}
