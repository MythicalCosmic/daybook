/**
 * A course (docs/PLAN-LEARNING.md §4.4, §12.1): its progress and deadline, the steps (locked, open,
 * done) and "Continue" to the next open one. Lessons open the player, pages the knowledge reader
 * with "I’ve read it", quizzes their intro. An optional course of the person's audience starts
 * with "Start the course"; a finished one shows its certificate.
 */
import { useQueryClient } from "@tanstack/react-query";
import { CircleCheck, FileText, ListChecks, Lock, PlayCircle, type LucideIcon } from "lucide-react";
import { useEffect, useRef } from "react";

import { useI18n } from "../../i18n";
import { useNow } from "../../lib/useNow";
import { dayMonth } from "../../lib/time";
import { useNavigation } from "../../state/navigation";
import { useMember } from "../../state/session";
import { useToast } from "../../state/toast";
import { haptic } from "../../telegram";
import { Badge, Banner, BottomBar, Card, cx, LoadError, PageHeader, PdfLink, ProgressRing, Screen, SectionHead, Skeleton } from "../../ui";
import { errorText } from "../../lib/actions";
import type { PageProps } from "../registry";
import { certificateLink, useCourse, useStartCourse } from "./api";
import { continueStep, dueText, stepObjectId, stepTarget } from "./lib";
import { CourseTile, useIsTop } from "./parts";
import { useLearningT, type LearningKey } from "./text";
import type { CourseDetail, CourseStep, StepKind } from "./types";
import "./learning.css";

const STEP_ICON: Record<StepKind, LucideIcon> = { lesson: PlayCircle, page: FileText, quiz: ListChecks };
const STEP_LABEL: Record<StepKind, LearningKey> = { lesson: "step.lesson", page: "step.page", quiz: "step.quiz" };

export default function CoursePage({ params }: PageProps) {
  const member = useMember();
  const navigation = useNavigation();
  const id = Number(params.id);
  const course = useCourse(member.companyId, id);
  const top = useIsTop("learning", "course", params);
  const refetch = course.refetch;
  // Back from a step (a page confirmed in the reader, a lesson, a quiz): the steps afresh.
  const wasTop = useRef(top);
  useEffect(() => {
    if (top && !wasTop.current) void refetch();
    wasTop.current = top;
  }, [top, refetch]);

  if (!course.data) {
    return (
      <Screen variant="detail">
        {course.isError ? <LoadError error={course.error} onRetry={() => void course.refetch()} onBack={navigation.pop} /> : <CourseSkeleton />}
      </Screen>
    );
  }
  return <Course course={course.data} />;
}

function CourseSkeleton() {
  return (
    <div className="lrn-stack" aria-hidden>
      <Skeleton height={34} width="70%" radius={10} />
      <Skeleton height={104} />
      <Skeleton height={20} width="30%" radius={8} />
      {[0, 1, 2, 3].map((index) => (
        <Skeleton key={index} height={64} />
      ))}
    </div>
  );
}

function Course({ course }: { course: CourseDetail }) {
  const t = useLearningT();
  const { locale } = useI18n();
  const member = useMember();
  const navigation = useNavigation();
  const toast = useToast();
  const client = useQueryClient();
  const now = useNow();
  const start = useStartCourse(member.companyId, course.id);
  const assignment = course.assignment;
  const completed = assignment?.state === "completed";
  const next = completed ? null : continueStep(course);
  const required = course.steps.filter((step) => step.required);
  const done = assignment ? assignment.steps_done : required.filter((step) => step.done).length;
  const total = assignment ? assignment.steps_total : required.length;
  const due = assignment ? dueText(assignment, now, member.timeZone, locale, t) : null;

  const open = (step: CourseStep) => {
    const target = stepObjectId(step);
    if (step.locked || target === null) {
      haptic.notify("warning");
      toast(t("course.locked"));
      return;
    }
    haptic.select();
    navigation.push(stepTarget(step.kind, target, course.id, assignment?.id ?? null));
  };
  const begin = () =>
    start.mutate(undefined, {
      onSuccess: () => {
        haptic.notify("success");
        toast(t("course.started"), { tone: "success" });
      },
      onError: (error) => {
        haptic.notify("error");
        toast(errorText(error, t, t("course.startFailed")), { tone: "error" });
      },
    });

  const subtitle = completed && assignment?.completed_at ? t("finished", { date: dayMonth(assignment.completed_at, member.timeZone, locale) }) : due;

  return (
    <>
      <Screen variant="detail">
        <PageHeader
          kicker={t(course.mandatory ? "course.mandatory" : "course.optional")}
          title={course.title}
          subtitle={subtitle ? <span className={cx(assignment?.late && !completed && "lrn-late")}>{subtitle}</span> : undefined}
          onBack={navigation.pop}
        />
        <Card layout="row" className="lrn-course-head">
          <CourseTile course={course} size="lg" />
          <span className="lrn-course-head-text">
            <span className="lrn-course-head-line num">{t("stepsDone", { done, total })}</span>
            <span className="lrn-course-head-meta">
              {[t("steps", { count: course.steps.length }), course.minutes ? t("min", { count: course.minutes }) : null].filter(Boolean).join(" · ")}
            </span>
          </span>
          <ProgressRing value={done} total={Math.max(total, 1)} size={58} stroke={6} tone={completed ? "sage" : "accent"} label={`${assignment?.percent ?? (total ? Math.round((done / total) * 100) : 0)}%`} />
        </Card>
        {completed && (
          <Banner tone="sage" icon={CircleCheck} title={t("course.finished")} />
        )}
        {completed && assignment?.certificate_url && (
          <PdfLink href={() => certificateLink(client, member.companyId, assignment.id)} title={t("certificate")} subtitle={t("certificate.sub")} />
        )}
        {course.description && <p className="lrn-summary">{course.description}</p>}
        <SectionHead size="small">{t("course.steps")}</SectionHead>
        <p className="lrn-note">{!assignment && course.can_start ? t("course.notStarted") : t(course.sequential ? "course.inOrder" : "course.anyOrder")}</p>
        <ol className="lrn-steps">
          {course.steps.map((step, index) => (
            <li key={step.id}>
              <StepRow step={step} index={index} current={next?.id === step.id} onOpen={() => open(step)} />
            </li>
          ))}
        </ol>
      </Screen>
      {!assignment && course.can_start ? (
        <BottomBar primary={{ text: t("course.start"), onClick: begin, loading: start.isPending, shine: true }} />
      ) : next ? (
        <BottomBar primary={{ text: t("course.continue"), onClick: () => open(next), shine: true }} />
      ) : null}
    </>
  );
}

function StepRow({ step, index, current, onOpen }: { step: CourseStep; index: number; current: boolean; onOpen: () => void }) {
  const t = useLearningT();
  const Icon = step.done ? CircleCheck : step.locked ? Lock : STEP_ICON[step.kind];
  const meta = [
    t(STEP_LABEL[step.kind]),
    step.minutes ? t("min", { count: step.minutes }) : null,
    step.kind === "quiz" && step.best_percent !== null ? t("step.best", { percent: step.best_percent }) : null,
  ]
    .filter(Boolean)
    .join(" · ");
  const state = step.done ? t("step.done") : step.locked ? t("step.locked") : null;
  return (
    <button
      type="button"
      className={cx("lrn-step", step.done && "lrn-step--done", step.locked && "lrn-step--locked", current && "lrn-step--current")}
      aria-disabled={step.locked || undefined}
      aria-current={current ? "step" : undefined}
      onClick={onOpen}
    >
      <span className="lrn-step-icon" aria-hidden>
        <Icon size={20} strokeWidth={2.4} />
      </span>
      <span className="lrn-step-text">
        <span className="lrn-step-title">
          <span className="lrn-step-n num" aria-hidden>
            {index + 1}.
          </span>{" "}
          {step.emoji ? `${step.emoji} ` : ""}
          {step.title}
        </span>
        <span className="lrn-step-meta">{meta}</span>
      </span>
      <span className="lrn-step-side">
        {!step.required && (
          <Badge size="small" tone="neutral">
            {t("optional")}
          </Badge>
        )}
        {state && <span className="lrn-sr">{state}</span>}
      </span>
    </button>
  );
}
