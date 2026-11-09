/**
 * Training (docs/PLAN-LEARNING.md §12.1): the checks to answer and the last ones, then the courses
 * in three tabs: To do (late first), Done (with their certificates) and Catalogue (optional
 * courses one may start on one's own).
 */
import { useQueryClient } from "@tanstack/react-query";
import { Award, BookOpenCheck, ClipboardCheck, GraduationCap, LibraryBig } from "lucide-react";
import { useState } from "react";

import { useI18n } from "../../i18n";
import { useNow } from "../../lib/useNow";
import { dayMonth } from "../../lib/time";
import { useNavigation } from "../../state/navigation";
import { useMember } from "../../state/session";
import { Badge, CardButton, cx, EmptyState, ListCard, ListRow, LoadError, PageHeader, PdfLink, ProgressBar, Screen, SectionHead, Segmented, Skeleton } from "../../ui";
import { useFeatureOpen } from "../useFeatureOpen";
import { certificateLink, useChecks, useLearningHome } from "./api";
import { dueText, sortTodo, whenText } from "./lib";
import { CourseTile } from "./parts";
import { openChecks } from "./slots";
import { useLearningT } from "./text";
import type { AssignmentCard, CheckEntry, CourseCard } from "./types";
import "./learning.css";

type Tab = "todo" | "done" | "catalog";

export default function LearningHome() {
  const t = useLearningT();
  const member = useMember();
  const navigation = useNavigation();
  const home = useLearningHome(member.companyId);
  const checks = useChecks(member.companyId);
  const [tab, setTab] = useState<Tab>("todo");
  const data = home.data;

  return (
    <Screen variant="detail">
      <PageHeader
        kicker={member.company.name}
        title={t("title")}
        subtitle={
          data?.certificates ? (
            <button type="button" className="lrn-cert-chip" onClick={() => setTab("done")}>
              <Award size={15} strokeWidth={2.6} aria-hidden />
              {t("certificates", { count: data.certificates })}
            </button>
          ) : undefined
        }
        onBack={navigation.pop}
      />
      <Checks entries={checks.data} />
      {!data ? (
        home.isError ? (
          <LoadError compact error={home.error} onRetry={() => void home.refetch()} />
        ) : (
          <HomeSkeleton />
        )
      ) : (
        <>
          <Segmented<Tab>
            role="tablist"
            fit
            value={tab}
            onChange={setTab}
            options={[
              { value: "todo", label: t("tab.todo"), count: data.todo.length },
              { value: "done", label: t("tab.done"), count: data.done.length },
              { value: "catalog", label: t("tab.catalog"), count: data.catalog.length },
            ]}
          />
          {tab === "todo" && <TodoList cards={data.todo} />}
          {tab === "done" && <DoneList cards={data.done} />}
          {tab === "catalog" && <Catalog courses={data.catalog} />}
        </>
      )}
    </Screen>
  );
}

function HomeSkeleton() {
  return (
    <div className="lrn-stack" aria-hidden>
      <Skeleton height={44} radius={999} />
      {[0, 1, 2].map((index) => (
        <Skeleton key={index} height={96} />
      ))}
    </div>
  );
}

/** Open checks first (with their deadline), then the last few answered or missed. */
function Checks({ entries }: { entries: CheckEntry[] | undefined }) {
  const t = useLearningT();
  const { locale } = useI18n();
  const member = useMember();
  const go = useFeatureOpen("learning");
  const now = useNow();
  if (!entries?.length) return null;
  const open = openChecks(entries, now);
  const rest = entries.filter((entry) => !open.includes(entry)).slice(0, 3);
  const state = (entry: CheckEntry) =>
    entry.done ? (entry.passed === false ? t("check.failed") : entry.passed ? t("check.passed") : t("check.answered")) : t("check.missed");
  return (
    <>
      <SectionHead size="small" count={open.length || undefined}>
        {t("checks.title")}
      </SectionHead>
      <ListCard>
        {open.map((entry) => (
          <ListRow
            key={entry.entry_id}
            icon={ClipboardCheck}
            title={entry.title}
            subtitle={t("check.dueShort", { when: whenText(entry.due_at, now, member.timeZone, locale, t) })}
            value={<Badge tone="accent" size="small">{t("check.start")}</Badge>}
            onClick={() => go.page("check", { id: entry.entry_id })}
          />
        ))}
        {rest.map((entry) => (
          <ListRow
            key={entry.entry_id}
            icon={ClipboardCheck}
            title={entry.title}
            subtitle={dayMonth(entry.due_at, member.timeZone, locale)}
            value={
              <Badge tone={entry.done && entry.passed !== false ? "sage" : "neutral"} size="small">
                {state(entry)}
              </Badge>
            }
            alert={!entry.done}
          />
        ))}
      </ListCard>
    </>
  );
}

function TodoList({ cards }: { cards: AssignmentCard[] }) {
  const t = useLearningT();
  if (!cards.length) return <EmptyState icon={BookOpenCheck} tone="sage" title={t("empty.todo.title")} body={t("empty.todo.body")} />;
  return (
    <div className="lrn-stack">
      {sortTodo(cards).map((card) => (
        <AssignmentRow key={card.id} card={card} />
      ))}
    </div>
  );
}

function AssignmentRow({ card }: { card: AssignmentCard }) {
  const t = useLearningT();
  const { locale } = useI18n();
  const member = useMember();
  const go = useFeatureOpen("learning");
  const now = useNow();
  const due = dueText(card, now, member.timeZone, locale, t);
  return (
    <CardButton className={cx("lrn-course", card.late && "lrn-course--late")} onClick={() => go.page("course", { id: card.course.id })}>
      <span className="lrn-course-top">
        <CourseTile course={card.course} />
        <span className="lrn-course-text">
          <span className="lrn-course-title">{card.course.title}</span>
          <span className="lrn-course-meta">
            {card.course.mandatory && (
              <Badge tone="accent" size="small">
                {t("mandatory")}
              </Badge>
            )}
            {due && <span className={cx(card.late && "lrn-late")}>{due}</span>}
          </span>
        </span>
      </span>
      <ProgressBar
        value={card.percent}
        size="sm"
        tone="accent"
        label={t("stepsDone", { done: card.steps_done, total: card.steps_total })}
        valueLabel={`${card.percent}%`}
      />
    </CardButton>
  );
}

function DoneList({ cards }: { cards: AssignmentCard[] }) {
  const t = useLearningT();
  const { locale } = useI18n();
  const member = useMember();
  const client = useQueryClient();
  const go = useFeatureOpen("learning");
  if (!cards.length) return <EmptyState icon={Award} tone="sage" title={t("empty.done.title")} body={t("empty.done.body")} />;
  return (
    <div className="lrn-stack">
      {cards.map((card) => (
        <div key={card.id} className="lrn-done">
          <ListRow
            variant="card"
            icon={<CourseTile course={card.course} />}
            title={card.course.title}
            subtitle={
              card.state === "exempt"
                ? t("exempt")
                : card.completed_at
                  ? t("finished", { date: dayMonth(card.completed_at, member.timeZone, locale) })
                  : t("stepsDone", { done: card.steps_done, total: card.steps_total })
            }
            onClick={() => go.page("course", { id: card.course.id })}
          />
          {card.certificate_url && (
            <PdfLink href={() => certificateLink(client, member.companyId, card.id)} title={t("certificate")} subtitle={t("certificate.sub")} variant="card" className="lrn-done-cert" />
          )}
        </div>
      ))}
    </div>
  );
}

function Catalog({ courses }: { courses: CourseCard[] }) {
  const t = useLearningT();
  const go = useFeatureOpen("learning");
  if (!courses.length) return <EmptyState icon={LibraryBig} tone="sage" title={t("empty.catalog.title")} body={t("empty.catalog.body")} />;
  return (
    <div className="lrn-stack">
      {courses.map((course) => (
        <CardButton key={course.id} className="lrn-course" onClick={() => go.page("course", { id: course.id })}>
          <span className="lrn-course-top">
            <CourseTile course={course} />
            <span className="lrn-course-text">
              <span className="lrn-course-title">{course.title}</span>
              <span className="lrn-course-meta">
                <GraduationCap size={14} strokeWidth={2.5} aria-hidden />
                {[t("steps", { count: course.steps }), course.minutes ? t("min", { count: course.minutes }) : null].filter(Boolean).join(" · ")}
              </span>
            </span>
          </span>
          {course.description && <span className="lrn-course-desc">{course.description}</span>}
        </CardButton>
      ))}
    </div>
  );
}
