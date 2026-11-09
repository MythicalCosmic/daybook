/**
 * A video lesson (docs/PLAN-LEARNING.md §4.2, §12.1): the player (the uploaded MP4 with its poster,
 * or YouTube), resumed where the person left off; what was really watched goes to the server as
 * they watch, and the bar shows the server's percent. "Next step" once watched (from a course),
 * the notes and topics below. A video still being prepared, or one that won't play, says so.
 */
import { useQueryClient } from "@tanstack/react-query";
import { CircleCheck, Clock3, RotateCw, VideoOff, WifiOff } from "lucide-react";
import { useMemo, useState } from "react";

import { useNavigation } from "../../state/navigation";
import { useMember } from "../../state/session";
import { useToast } from "../../state/toast";
import { haptic } from "../../telegram";
import { Badge, BottomBar, celebrate, LoadError, PageHeader, ProgressBar, Screen, ScreenSkeleton, SectionHead } from "../../ui";
import type { PageProps } from "../registry";
import { safeHtml } from "../knowledge/safeHtml";
import { useFollowLink } from "../knowledge/links";
import "../knowledge/knowledge.css";
import { learningKeys, useLesson } from "./api";
import { minutesOf, stepTarget } from "./lib";
import { backToCourse, numberParam, PlayerState, TopicChips, useIsTop } from "./parts";
import { VideoPlayer, YouTubePlayer } from "./players";
import { useWatchReporter } from "./progress";
import { useQueueState } from "./queue";
import { useLearningT } from "./text";
import type { LessonDetail, ProgressAnswer } from "./types";
import "./learning.css";

export default function LessonPage({ params }: PageProps) {
  const member = useMember();
  const navigation = useNavigation();
  const id = Number(params.id);
  const course = numberParam(params, "course");
  const lesson = useLesson(member.companyId, id, course);

  if (!lesson.data) {
    return (
      <Screen variant="detail">
        {lesson.isError ? <LoadError error={lesson.error} onRetry={() => void lesson.refetch()} onBack={navigation.pop} /> : <LessonSkeleton />}
      </Screen>
    );
  }
  return <Lesson lesson={lesson.data} params={params} refetch={() => void lesson.refetch()} />;
}

function LessonSkeleton() {
  return <ScreenSkeleton variant="detail" delay={150} />;
}

function Lesson({ lesson, params, refetch }: { lesson: LessonDetail; params: PageProps["params"]; refetch: () => void }) {
  const t = useLearningT();
  const member = useMember();
  const navigation = useNavigation();
  const toast = useToast();
  const client = useQueryClient();
  const followLink = useFollowLink();
  const course = numberParam(params, "course");
  const assignment = numberParam(params, "assignment");
  const active = useIsTop("learning", "lesson", params);
  const [percent, setPercent] = useState(lesson.progress?.percent ?? 0);
  const [completed, setCompleted] = useState(Boolean(lesson.progress?.completed_at));
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const offline = useQueueState(`progress:${lesson.id}:`);
  const notes = useMemo(() => safeHtml(lesson.notes_html ?? ""), [lesson.notes_html]);

  const onAnswer = (answer: ProgressAnswer) => {
    setPercent(answer.percent);
    if (answer.completed) setCompleted(true);
    if (answer.completed_now) {
      celebrate();
      toast(answer.points ? `${t("lesson.done")} ${t("points", { count: answer.points })}` : t("lesson.done"), { tone: "success" });
      // The step is done in every open course holding the lesson: the lists show it.
      void client.invalidateQueries({ queryKey: learningKeys.home(member.companyId) });
      void client.invalidateQueries({ predicate: (entry) => entry.queryKey[0] === "learning" && entry.queryKey[2] === "course" });
    }
  };
  const duration = lesson.video?.duration_seconds || lesson.duration_seconds;
  const watcher = useWatchReporter({ company: member.companyId, lesson: lesson.id, durationHint: duration, onAnswer });
  const start = lesson.progress?.position ?? 0;
  const retry = () => {
    haptic.select();
    setFailed(false);
    setAttempt((count) => count + 1);
    refetch();
  };

  let player;
  if (lesson.processing) {
    player = <PlayerState icon={Clock3} title={t("lesson.processing.title")} body={t("lesson.processing.body")} action={{ label: t("common.retry"), onClick: retry, icon: RotateCw }} />;
  } else if (failed) {
    player = <PlayerState icon={VideoOff} tone="accent" title={t("lesson.cantPlay.title")} body={t("lesson.cantPlay.body")} action={{ label: t("common.retry"), onClick: retry, icon: RotateCw }} />;
  } else if (lesson.source === "youtube" && lesson.youtube_id) {
    player = <YouTubePlayer key={attempt} id={lesson.youtube_id} start={start} watcher={watcher} active={active} label={t("lesson.player")} onFail={() => setFailed(true)} />;
  } else if (lesson.video?.url) {
    player = <VideoPlayer key={attempt} video={lesson.video} start={start} watcher={watcher} active={active} label={t("lesson.player")} onFail={() => setFailed(true)} />;
  } else {
    player = <PlayerState icon={VideoOff} title={t("lesson.noVideo.title")} body={t("lesson.noVideo.body")} />;
  }
  const playable = !lesson.processing && !failed && (Boolean(lesson.video?.url) || (lesson.source === "youtube" && Boolean(lesson.youtube_id)));
  const minutes = minutesOf(duration);

  const next = lesson.next;
  const goNext = () => {
    if (!next) return;
    haptic.select();
    navigation.replace(stepTarget(next.kind, next.id, course, assignment));
  };

  return (
    <>
      <Screen variant="detail">
        <PageHeader
          kicker={t("step.lesson")}
          title={`${lesson.emoji ? `${lesson.emoji} ` : ""}${lesson.title}`}
          subtitle={minutes ? t("min", { count: minutes }) : undefined}
          onBack={navigation.pop}
        />
        <div className="lrn-player">{player}</div>
        {playable && (
          <div className="lrn-watch">
            <ProgressBar
              value={percent}
              total={100}
              target={lesson.completion_percent}
              tone={completed ? "sage" : "accent"}
              label={t("lesson.watched")}
              valueLabel={`${percent}%`}
              caption={
                completed ? (
                  <Badge tone="sage" size="small" icon={CircleCheck}>
                    {t("lesson.watched")}
                  </Badge>
                ) : (
                  t("lesson.toFinish", { percent: lesson.completion_percent })
                )
              }
            />
            {offline.failing && (
              <p className="lrn-offline" role="status">
                <WifiOff size={15} strokeWidth={2.5} aria-hidden />
                {t("lesson.offline")}
              </p>
            )}
          </div>
        )}
        {lesson.summary && <p className="lrn-summary">{lesson.summary}</p>}
        <TopicChips topics={lesson.topics} />
        {notes && (
          <>
            <SectionHead size="small">{t("lesson.notes")}</SectionHead>
            <article
              className="kbm-article"
              onClick={(event) => {
                const anchor = event.target instanceof Element ? event.target.closest("a[href]") : null;
                if (anchor && followLink(anchor.getAttribute("href") ?? "")) {
                  event.preventDefault();
                  haptic.select();
                }
              }}
              dangerouslySetInnerHTML={{ __html: notes }}
            />
          </>
        )}
      </Screen>
      {completed && next ? (
        <BottomBar primary={{ text: t("lesson.next"), onClick: goNext, shine: true }} />
      ) : completed && course ? (
        <BottomBar primary={{ text: t("course.back"), onClick: () => backToCourse(navigation, course) }} />
      ) : null}
    </>
  );
}
