/**
 * "Ishdan ketish" (Me → Leaving, and the bot's `lifecycle.leaving` link): the resignation letter
 * (my last working day, two weeks ahead by default, and my reason if I want to give one); while
 * it waits, what I asked for and "I'm staying"; once my manager agrees the day, that day, what I
 * hand over (HR ticks it off) and three short questions before I go.
 *
 * Calm on purpose: leaving is a person's own decision; nothing here argues with it.
 */
import { Check, DoorOpen, Hourglass, Send, Undo2 } from "lucide-react";
import { useState, type ReactNode } from "react";

import { useI18n } from "../../i18n";
import { capitalise, dayMonthLong, dayMonthYear, weekdayLong } from "../../lib/time";
import { useDraftGuard } from "../../lib/useDraftGuard";
import { useNavigation } from "../../state/navigation";
import { useMember } from "../../state/session";
import { confirm } from "../../telegram";
import { Banner, BottomBar, Button, Card, ChipGroup, DateInput, EmptyState, Field, ListCard, ListRow, LoadError, PageHeader, ProgressBar, Screen, ScreenSkeleton, SectionHead, Textarea, cx } from "../../ui";
import { useFeedback } from "../states";
import { EXIT_REASONS, RECOMMEND, useExitAnswers, useLeaving, useRequestLeaving, useWithdrawLeaving, type ExitReason, type LeavingState, type MyLeaving, type Recommend } from "./api";
import { closedNote, daysBetween, EXIT_BETTER_MAX, exitPayload, handoverProgress, LEAVE_REASON_MAX, leavePayload, leavingStage, suggestedLastDay } from "./lib";
import { daysLeftText, exitReasonLabel, handoverIcon, handoverLabel, keepTogether, recommendLabel, useRecordT, type RecordKey, type RecordT } from "./text";
import "./lifecycle.css";

export default function LeavingPage() {
  const t = useRecordT();
  const member = useMember();
  const navigation = useNavigation();
  const leaving = useLeaving(member.companyId);
  const header = <PageHeader kicker={member.company.name} title={t("leaving.title")} subtitle={t("leaving.subtitle")} onBack={navigation.pop} />;

  if (!leaving.data) {
    return (
      <Screen variant="detail">
        {header}
        {leaving.isError ? (
          <LoadError error={leaving.error} onRetry={() => void leaving.refetch()} onBack={navigation.pop} />
        ) : (
          <ScreenSkeleton variant="detail" delay={150} />
        )}
      </Screen>
    );
  }

  const state = leaving.data;
  const stage = leavingStage(state);
  if (stage === "form") return <RequestForm key={state.current?.id ?? "new"} state={state} header={header} />;
  if (stage === "requested" && state.current) return <Requested state={state} current={state.current} header={header} />;
  if (stage === "agreed" && state.current) return <Agreed state={state} current={state.current} header={header} />;
  return (
    <Screen variant="detail">
      {header}
      <EmptyState icon={DoorOpen} tone="sage" title={t("none.title")} body={t("none.body")} />
    </Screen>
  );
}

/** "Seshanba, 20-noyabr" / "Пятница, 20 ноября": a day that starts a line, never split at "20-". */
function longDay(day: string, locale: string): string {
  return keepTogether(capitalise(`${weekdayLong(day, "UTC", locale)}, ${dayMonthLong(day, "UTC", locale)}`));
}

// — The letter —

function RequestForm({ state, header }: { state: LeavingState; header: ReactNode }) {
  const t = useRecordT();
  const { locale } = useI18n();
  const member = useMember();
  const feedback = useFeedback();
  const send = useRequestLeaving(member.companyId);
  const [day, setDay] = useState(() => suggestedLastDay(state));
  const [reason, setReason] = useState("");
  useDraftGuard(Boolean(reason.trim()));
  const payload = leavePayload(day, reason, state.today);
  const notice = daysBetween(state.today, day);
  const note = closedNote(state);

  const submit = async () => {
    if (!payload || send.isPending) return;
    if (!(await confirm(t("form.confirm", { date: longDay(day, locale) })))) return;
    send.mutate(payload, { onSuccess: () => feedback.ok(t("form.sent")), onError: feedback.fail });
  };

  return (
    <>
      <Screen variant="detail">
        {header}
        {note && (
          <Banner
            tone={note === "withdrawnByMe" ? "sage" : "plain"}
            icon={note === "withdrawnByMe" ? Undo2 : DoorOpen}
            title={t(`closed.${note}` as RecordKey)}
            body={[state.current?.close_reason && t("closed.reason", { reason: state.current.close_reason }), t("closed.askAgain")].filter(Boolean).join(" ")}
          />
        )}
        <SectionHead>{t("form.heading")}</SectionHead>
        <p className="ft-quiet">{t("form.intro")}</p>
        <div className="lc-form">
          <Field label={t("form.day")} hint={notice < state.notice_days ? <span className="lc-warn">{t("form.short")}</span> : t("form.notice", { count: notice })}>
            <DateInput value={day} onChange={setDay} label={t("form.day")} min={state.today} today={state.today} long />
          </Field>
          <Field label={t("form.reason")}>
            <Textarea value={reason} onChange={(event) => setReason(event.target.value)} rows={4} maxLength={LEAVE_REASON_MAX} placeholder={t("form.reasonPlaceholder")} />
          </Field>
        </div>
      </Screen>
      <BottomBar primary={{ text: t("form.send"), onClick: () => void submit(), loading: send.isPending, disabled: !payload, icon: Send }} />
    </>
  );
}

// — Waiting for the manager —

function Requested({ state, current, header }: { state: LeavingState; current: MyLeaving; header: ReactNode }) {
  const t = useRecordT();
  const { locale } = useI18n();
  const member = useMember();
  const sameYear = new Date(`${state.today}T12:00:00Z`);
  return (
    <Screen variant="detail">
      {header}
      <Banner icon={Hourglass} title={t("requested.title")} body={t("requested.body")} />
      <ListCard>
        {current.wished_last_day && <ListRow title={t("fact.asked")} value={longDay(current.wished_last_day, locale)} />}
        {current.notice_days !== null && <ListRow title={t("fact.notice")} value={t("fact.days", { count: current.notice_days })} />}
        <ListRow title={t("fact.sent")} value={dayMonthYear(current.requested_at, member.timeZone, locale, sameYear)} />
      </ListCard>
      {current.reason && (
        <Card tone="outline" className="lc-yours">
          <div className="lc-yours-head">{t("fact.reason")}</div>
          <p className="ft-text">{current.reason}</p>
        </Card>
      )}
      {current.can_withdraw && <Withdraw current={current} />}
    </Screen>
  );
}

function Withdraw({ current }: { current: MyLeaving }) {
  const t = useRecordT();
  const member = useMember();
  const feedback = useFeedback();
  const withdraw = useWithdrawLeaving(member.companyId);
  const run = async () => {
    if (withdraw.isPending || !(await confirm(t("withdraw.confirm")))) return;
    withdraw.mutate(current.id, { onSuccess: () => feedback.ok(t("withdraw.done")), onError: feedback.fail });
  };
  return (
    <Button variant="ghost" block icon={Undo2} loading={withdraw.isPending} onClick={() => void run()} className="lc-withdraw">
      {t("withdraw.button")}
    </Button>
  );
}

// — The day agreed —

function Agreed({ state, current, header }: { state: LeavingState; current: MyLeaving; header: ReactNode }) {
  const t = useRecordT();
  const { locale } = useI18n();
  const day = current.last_day ?? current.wished_last_day ?? state.today;
  const left = daysBetween(state.today, day);
  const progress = handoverProgress(current.handover);
  return (
    <Screen variant="detail">
      {header}
      <Card tone="accent" className="lc-day" data-testid="last-day">
        <div className="lc-day-kicker">{t("agreed.kicker")}</div>
        <div className="heading lc-day-date">{longDay(day, locale)}</div>
        <div className="lc-day-meta">
          <span className="tag tag-small lc-day-left">{daysLeftText(t, left)}</span>
          {current.agreed_by && <span>{t("agreed.by", { name: current.agreed_by })}</span>}
        </div>
      </Card>
      <p className="ft-quiet">{left <= 0 ? t("agreed.lastDay") : t("agreed.evening")}</p>

      {current.handover.length > 0 && (
        <>
          <SectionHead>{t("handover.title")}</SectionHead>
          <HandoverList items={current.handover} progress={progress} t={t} />
          <p className="ft-hint lc-pad">{t("handover.intro")}</p>
        </>
      )}

      {current.can_answer && <ExitQuestions current={current} />}
      {current.can_withdraw && <Withdraw current={current} />}
    </Screen>
  );
}

function HandoverList({ items, progress, t }: { items: MyLeaving["handover"]; progress: { done: number; total: number }; t: RecordT }) {
  return (
    <Card padding="sm" className="lc-hand-card">
      <div className="lc-hand-progress">
        <ProgressBar value={progress.done} total={progress.total} tone="sage" size="sm" label={t("handover.progress", { done: progress.done, left: progress.total - progress.done })} />
      </div>
      <ul className="lc-hand-list">
        {items.map((item) => {
          const Icon = handoverIcon(item.kind);
          const sub =
            item.kind === "tasks" && !item.done && item.open_tasks
              ? t("handover.openTasks", { count: item.open_tasks })
              : item.kind === "tasks" && item.open_tasks === 0
                ? t("handover.noTasks")
                : item.done
                  ? t("handover.done")
                  : t("handover.toDo");
          return (
            <li key={item.id} className={cx("lc-hand", item.done && "lc-hand--done")} data-testid="handover-item">
              <span className="lc-hand-mark" aria-hidden>
                {item.done && <Check size={14} strokeWidth={3.2} />}
              </span>
              <span className="lc-hand-text">
                <span className="lc-hand-title">{handoverLabel(t, item)}</span>
                <span className="lc-hand-sub">{sub}</span>
              </span>
              <Icon className="lc-hand-icon" size={18} strokeWidth={2.2} aria-hidden />
            </li>
          );
        })}
      </ul>
    </Card>
  );
}

// — Before I go —

function ExitQuestions({ current }: { current: MyLeaving }) {
  const t = useRecordT();
  const member = useMember();
  const feedback = useFeedback();
  const answer = useExitAnswers(member.companyId);
  const given = current.exit_interview;
  const [editing, setEditing] = useState(!given);
  const [reason, setReason] = useState<ExitReason | null>(given?.reason ?? null);
  const [better, setBetter] = useState(given?.better ?? "");
  const [recommend, setRecommend] = useState<Recommend | null>(given?.recommend || null);
  const payload = exitPayload(reason, better, recommend);

  const send = () => {
    if (!payload || answer.isPending) return;
    answer.mutate(
      { id: current.id, ...payload },
      {
        onSuccess: () => {
          feedback.ok(t("exit.sent"));
          setEditing(false);
        },
        onError: feedback.fail,
      },
    );
  };

  if (given && !editing) {
    return (
      <>
        <SectionHead>{t("exit.title")}</SectionHead>
        <Card tone="outline" className="lc-yours" data-testid="exit-answers">
          <div className="lc-yours-head">{t("exit.yours")}</div>
          <p className="ft-text">{t("exit.answeredReason", { reason: exitReasonLabel(t, given.reason) })}</p>
          {given.better && <p className="ft-text">{given.better}</p>}
          {given.recommend && <p className="ft-text">{t("exit.answeredRecommend", { answer: recommendLabel(t, given.recommend) })}</p>}
          <Button variant="ghost" className="lc-change" onClick={() => setEditing(true)}>
            {t("exit.change")}
          </Button>
        </Card>
      </>
    );
  }
  return (
    <>
      <SectionHead>{t("exit.title")}</SectionHead>
      <p className="ft-quiet">{t("exit.intro")}</p>
      <div className="lc-form" data-testid="exit-form">
        <Field label={t("exit.reason")}>
          <ChipGroup options={EXIT_REASONS.map((value) => ({ value, label: exitReasonLabel(t, value) }))} value={reason} onChange={setReason} label={t("exit.reason")} />
        </Field>
        <Field label={t("exit.better")} optional>
          <Textarea value={better} onChange={(event) => setBetter(event.target.value)} rows={3} maxLength={EXIT_BETTER_MAX} placeholder={t("exit.betterPlaceholder")} />
        </Field>
        <Field label={t("exit.recommend")} optional>
          <ChipGroup options={RECOMMEND.map((value) => ({ value, label: recommendLabel(t, value) }))} value={recommend} onChange={setRecommend} allowNone label={t("exit.recommend")} />
        </Field>
        <Button variant="primary" block icon={Send} disabled={!payload} loading={answer.isPending} onClick={send}>
          {t("exit.send")}
        </Button>
      </div>
    </>
  );
}
