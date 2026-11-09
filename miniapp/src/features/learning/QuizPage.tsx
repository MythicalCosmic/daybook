/**
 * A quiz before it starts (docs/PLAN-LEARNING.md §4.7, §12.1): how many questions, the time limit,
 * the pass mark, the attempts left and the best so far; "Start the test" (or "Continue the test"
 * for one in progress), or why not (a cool-down until …, no attempts left). Opened from a course
 * step (with its assignment), a regular check (its entry) or a link.
 */
import { CalendarClock, CircleCheck, Hourglass, ListChecks, Target, Timer, Trophy, type LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { useI18n } from "../../i18n";
import { errorText } from "../../lib/actions";
import { useNow } from "../../lib/useNow";
import { useNavigation, type Params } from "../../state/navigation";
import { useMember } from "../../state/session";
import { useToast } from "../../state/toast";
import { haptic } from "../../telegram";
import { Badge, Banner, BottomBar, Card, LoadError, PageHeader, Screen, Skeleton } from "../../ui";
import type { PageProps } from "../registry";
import { useQuiz, useStartAttempt } from "./api";
import { isAhead, minutesOf, whenText } from "./lib";
import { numberParam } from "./parts";
import { useLearningT, type LearningT } from "./text";
import type { QuizDetail } from "./types";
import "./learning.css";

export default function QuizPage({ params }: PageProps) {
  return (
    <QuizIntro
      quizId={Number(params.id)}
      assignment={numberParam(params, "assignment")}
      course={numberParam(params, "course")}
      entry={numberParam(params, "entry")}
    />
  );
}

/** Why the quiz can't start now, in words (the server's own reason when it gives one). */
export function blockedText(quiz: QuizDetail, now: Date, timeZone: string, locale: string, t: LearningT): string {
  if (quiz.retry_at && isAhead(quiz.retry_at, now)) return t("quiz.retryAt", { when: whenText(quiz.retry_at, now, timeZone, locale, t) });
  if (quiz.max_attempts !== null && quiz.attempts_used >= quiz.max_attempts) return t("quiz.noAttempts");
  // A sentence from the server reads as it is; a bare code ("not_in_audience") gets the general line.
  return quiz.reason && /\s/.test(quiz.reason.trim()) ? quiz.reason : t("quiz.unavailable");
}

/** Where the player for an attempt opens, with what it came from. */
export function attemptPage(id: number, quiz: number, context: { assignment: number | null; course: number | null; entry: number | null }) {
  const params: Params = { id, quiz };
  if (context.assignment) params.assignment = context.assignment;
  if (context.course) params.course = context.course;
  if (context.entry) params.entry = context.entry;
  return { feature: "learning", page: "attempt", params };
}

export function QuizIntro({
  quizId,
  assignment,
  course,
  entry,
  due,
}: {
  quizId: number;
  assignment: number | null;
  course: number | null;
  entry: number | null;
  /** A check's deadline. */
  due?: string;
}) {
  const t = useLearningT();
  const { locale } = useI18n();
  const member = useMember();
  const navigation = useNavigation();
  const toast = useToast();
  const now = useNow();
  const quiz = useQuiz(member.companyId, quizId, { assignment, entry });
  const start = useStartAttempt(member.companyId, quizId);

  if (!quiz.data) {
    return (
      <Screen variant="detail">
        {quiz.isError ? <LoadError error={quiz.error} onRetry={() => void quiz.refetch()} onBack={navigation.pop} /> : <IntroSkeleton />}
      </Screen>
    );
  }
  const data = quiz.data;
  const context = { assignment, course, entry };
  const open = (attempt: number) => navigation.replace(attemptPage(attempt, data.id, context));
  const begin = () =>
    start.mutate(
      { assignment, entry },
      {
        onSuccess: (play) => {
          haptic.impact("medium");
          open(play.id);
        },
        onError: (error) => {
          haptic.notify("error");
          toast(errorText(error, t, t("quiz.startFailed")), { tone: "error" });
          void quiz.refetch();
        },
      },
    );
  const attemptsLeft = data.max_attempts === null ? null : Math.max(0, data.max_attempts - data.attempts_used);
  const minutes = data.time_limit_seconds ? minutesOf(data.time_limit_seconds) : 0;
  const blocked = !data.in_progress && !data.can_start;

  return (
    <>
      <Screen variant="detail">
        <PageHeader
          kicker={t(entry ? "check.kicker" : "step.quiz")}
          title={`${data.emoji ? `${data.emoji} ` : ""}${data.title}`}
          subtitle={due ? t("check.due", { when: whenText(due, now, member.timeZone, locale, t) }) : undefined}
          onBack={navigation.pop}
        />
        {data.description && <p className="lrn-summary">{data.description}</p>}
        <Card padding="sm" className="lrn-facts">
          <Fact icon={ListChecks} label={t("quiz.facts.questions")} value={String(data.questions)} />
          <Fact icon={Timer} label={t("quiz.facts.time")} value={minutes ? t("min", { count: minutes }) : t("quiz.noLimit")} />
          <Fact icon={Target} label={t("quiz.facts.pass")} value={`${data.pass_percent}%`} />
          <Fact
            icon={Hourglass}
            label={t("quiz.facts.attempts")}
            value={attemptsLeft === null ? t("quiz.unlimited") : t("quiz.attempts", { left: attemptsLeft, max: data.max_attempts ?? 0 })}
          />
          {data.best && (
            <Fact
              icon={Trophy}
              label={t("quiz.facts.best")}
              value={
                <span className="lrn-fact-best">
                  <span className="num">{data.best.percent}%</span>
                  {data.best.passed && (
                    <Badge tone="sage" size="small" icon={CircleCheck}>
                      {t("quiz.passed")}
                    </Badge>
                  )}
                </span>
              }
            />
          )}
        </Card>
        {blocked ? (
          <Banner tone="accent" icon={CalendarClock} title={blockedText(data, now, member.timeZone, locale, t)} />
        ) : (
          <p className="lrn-note">{t(data.time_limit_seconds ? "quiz.timedHint" : "quiz.hint")}</p>
        )}
      </Screen>
      {data.in_progress ? (
        <BottomBar primary={{ text: t("quiz.resume"), onClick: () => open(data.in_progress!), shine: true }} />
      ) : data.can_start ? (
        <BottomBar primary={{ text: t("quiz.start"), onClick: begin, loading: start.isPending, shine: true }} />
      ) : null}
    </>
  );
}

function Fact({ icon: Icon, label, value }: { icon: LucideIcon; label: string; value: ReactNode }) {
  return (
    <div className="lrn-fact">
      <span className="lrn-fact-icon" aria-hidden>
        <Icon size={18} strokeWidth={2.4} />
      </span>
      <span className="lrn-fact-label">{label}</span>
      <span className="lrn-fact-value">{value}</span>
    </div>
  );
}

function IntroSkeleton() {
  return (
    <div className="lrn-stack" aria-hidden>
      <Skeleton height={34} width="64%" radius={10} />
      <Skeleton height={18} width="90%" radius={8} />
      <Skeleton height={214} />
      <Skeleton height={44} />
    </div>
  );
}
