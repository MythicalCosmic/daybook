/**
 * What training puts on Home and Me (docs/PLAN-LEARNING.md §12.1): a check card while a round of
 * theirs is open ("Dushanba tekshiruvi: 5 questions, by Wednesday, 10:00", Start), the question
 * of the day answered right there, and the open mandatory courses (at most three, with "All").
 * Me's "My training" counts the open mandatory courses. Each card renders nothing when there is
 * nothing for the person, or when the server didn't answer.
 */
import { ChevronRight, ClipboardCheck, Flame, Lightbulb } from "lucide-react";
import { useEffect, useState } from "react";

import { useI18n } from "../../i18n";
import { useNow } from "../../lib/useNow";
import { Banner, Button, Card, cx, ProgressBar } from "../../ui";
import type { MeItemStatus, SlotProps } from "../registry";
import { useFeatureOpen } from "../useFeatureOpen";
import { useChecks, useDaily, useLearningHome, useQuiz } from "./api";
import { DailyBody } from "./Daily";
import { dueText, isAhead, openMandatory, whenText } from "./lib";
import { CourseTile } from "./parts";
import { restoreOnce } from "./queue";
import { useLearningT } from "./text";
import type { CheckEntry } from "./types";
import "./learning.css";

/** Reports a closed app left behind go out once, when training first shows. */
function useRestoreQueue(): void {
  useEffect(() => restoreOnce(), []);
}

/** Home: the open mandatory courses, late first, at most three. */
export function TrainingCard({ member }: SlotProps) {
  const t = useLearningT();
  const { locale } = useI18n();
  const go = useFeatureOpen("learning");
  const now = useNow();
  const home = useLearningHome(member.companyId);
  useRestoreQueue();
  const open = openMandatory(home.data?.todo);
  if (!open.length) return null;
  return (
    <Card padding="list" className="lrn-home-card">
      <span className="lrn-card-head">
        <span className="card-title">{t("title")}</span>
        <button type="button" className="btn btn-ghost lrn-card-all" onClick={() => go.page("home")}>
          {t("card.all")}
        </button>
      </span>
      {open.slice(0, 3).map((card) => {
        const due = dueText(card, now, member.timeZone, locale, t);
        return (
          <button key={card.id} type="button" className="lrn-mini" onClick={() => go.page("course", { id: card.course.id })}>
            <CourseTile course={card.course} />
            <span className="lrn-mini-text">
              <span className="lrn-mini-title">{card.course.title}</span>
              <ProgressBar value={card.percent} size="sm" tone="accent" ariaLabel={`${card.percent}%`} />
              <span className="lrn-mini-meta">
                {t("stepsDone", { done: card.steps_done, total: card.steps_total })}
                {due && (
                  <>
                    {" · "}
                    <span className={cx(card.late && "lrn-late")}>{due}</span>
                  </>
                )}
              </span>
            </span>
            <ChevronRight className="lrn-mini-chevron" size={19} strokeWidth={2.5} aria-hidden />
          </button>
        );
      })}
    </Card>
  );
}

/** Home: the question of the day, answered in place; once answered, one quiet line. */
export function DailyCard({ member }: SlotProps) {
  const t = useLearningT();
  const go = useFeatureOpen("learning");
  const daily = useDaily(member.companyId);
  // Answered here and now: the result stays in the card instead of folding into a line.
  const [fresh, setFresh] = useState(false);
  useRestoreQueue();
  const view = daily.data;
  if (!view?.daily) return null;
  if (view.daily.answered && !fresh) {
    return (
      <Banner
        size="lg"
        iconTone="sage"
        icon={Lightbulb}
        title={t(view.daily.correct ? "daily.doneRight" : "daily.doneWrong")}
        body={view.streak ? t("streak", { count: view.streak }) : t("daily.doneBody")}
        wrap
        onClick={() => go.page("daily")}
      />
    );
  }
  return (
    <Card className="lrn-daily">
      <span className="lrn-daily-head">
        <span className="lrn-daily-badge" aria-hidden>
          <Lightbulb size={18} strokeWidth={2.5} />
        </span>
        <span className="card-title">{t("daily.title")}</span>
        {view.streak ? (
          <span className="tag tag-sage tag-small lrn-daily-streak">
            <Flame size={13} strokeWidth={2.6} aria-hidden />
            {t("streak", { count: view.streak })}
          </span>
        ) : null}
      </span>
      <DailyBody daily={view.daily} streak={view.streak} compact onAnswered={() => setFresh(true)} />
    </Card>
  );
}

/** The rounds of checks open for the person now, soonest deadline first. */
export function openChecks(entries: readonly CheckEntry[] | undefined, now: Date): CheckEntry[] {
  return (entries ?? []).filter((entry) => !entry.done && isAhead(entry.due_at, now)).sort((a, b) => Date.parse(a.due_at) - Date.parse(b.due_at));
}

/** Home: a check to answer, with its deadline and Start. */
export function CheckCard({ member }: SlotProps) {
  const t = useLearningT();
  const { locale } = useI18n();
  const go = useFeatureOpen("learning");
  const now = useNow();
  const checks = useChecks(member.companyId);
  const open = openChecks(checks.data, now);
  const first = open[0];
  // How many questions: from the quiz the first round asks (one request, only while one is open).
  const quiz = useQuiz(member.companyId, first?.quiz_id ?? 0, { entry: first?.entry_id ?? null });
  if (!first) return null;
  return (
    <>
      {open.slice(0, 2).map((entry) => {
        const when = whenText(entry.due_at, now, member.timeZone, locale, t);
        const count = entry === first ? quiz.data?.questions : undefined;
        return (
          <Card key={entry.entry_id} className="lrn-check-card">
            <span className="circle banner-circle banner-circle--accent lrn-check-icon" aria-hidden>
              <ClipboardCheck size={21} strokeWidth={2.4} />
            </span>
            <span className="lrn-check-text">
              <span className="lrn-check-kicker">{t("check.kicker")}</span>
              <span className="banner-title">{entry.title}</span>
              <span className="row-meta row-meta--wrap">{count ? t("check.body", { questions: t("quiz.questions", { count }), when }) : t("check.due", { when })}</span>
            </span>
            <Button variant="primary" className="lrn-check-start" onClick={() => go.page("check", { id: entry.entry_id })}>
              {t("check.start")}
            </Button>
          </Card>
        );
      })}
    </>
  );
}

/** Me → My training: how many mandatory courses are open. */
export function useMeStatus({ member }: SlotProps): MeItemStatus {
  const home = useLearningHome(member.companyId);
  return { badge: openMandatory(home.data?.todo).length || null };
}
