import { AlertCircle, CalendarClock, Camera, Check, Flag, MessageCircleQuestion, Mic, PenLine, RotateCcw, UserRound, X } from "lucide-react";
import { useId, useLayoutEffect, useMemo, useRef, useState } from "react";

import { useMembers } from "../../api/hooks";
import { givesWork } from "../../api/permissions";
import { AssigneeSelect, type AssigneeOption } from "../../components/AssigneeSelect";
import { StepsEditor } from "../../components/StepsEditor";
import { WhenPicker } from "../../components/WhenPicker";
import { useFeatureT } from "../../i18n/feature";
import { errorText } from "../../lib/actions";
import { formatDue } from "../../lib/taskView";
import { hourIn } from "../../lib/time";
import { useDraftGuard } from "../../lib/useDraftGuard";
import { useNow, useViewContext } from "../../lib/useNow";
import { useMember } from "../../state/session";
import { useToast } from "../../state/toast";
import { confirm, haptic } from "../../telegram";
import { BottomBar } from "../../ui";
import { cx } from "../../ui/cx";
import { useApplyDraft, useDiscardDraft, type AIDraft, type ApplyResult, type Problem } from "./api";
import {
  acceptProblem,
  applyPayload,
  dueOf,
  editableFrom,
  firstUnready,
  isBlocking,
  kept,
  makeMine,
  pickAssignee,
  problemsOf,
  quickDue,
  sameTimeTomorrow,
  setWhen,
  type EditableDraft,
} from "./drafts";
import { messages } from "./messages";

const WHO: readonly Problem[] = ["no_assignee_match", "ambiguous_assignee", "not_allowed"];

/**
 * What the AI understood, card by card: the title, for whom ("Me" first), when (the (+) sheet's
 * own controls), urgent, photo, checklist lines, remove. Problems read in plain words with their
 * fix one tap away; "Create N tasks" is Telegram's main button.
 */
export function Review({
  draft,
  onApplied,
  onDiscarded,
  onAgain,
}: {
  draft: AIDraft;
  onApplied: (result: ApplyResult) => void;
  onDiscarded: () => void;
  /** Start over (say it again, or type it again). */
  onAgain: () => void;
}) {
  const t = useFeatureT(messages);
  const member = useMember();
  const toast = useToast();
  const now = useNow(15_000);
  const timeZone = member.timeZone;
  const canAssign = givesWork(member);
  const members = useMembers(member.companyId, canAssign);
  const [cards, setCards] = useState(() => editableFrom(draft, new Date(), timeZone));
  const [edited, setEdited] = useState(false);
  const [flagged, setFlagged] = useState<string | null>(null);
  const apply = useApplyDraft(member.companyId, draft.id);
  const discard = useDiscardDraft(member.companyId, draft.id);
  useDraftGuard(edited);

  const left = kept(cards);
  // The people I may give work to, and anyone the AI matched who isn't among them (still a choice).
  const people = useMemo(() => {
    const list: AssigneeOption[] = (members.data ?? []).filter((person) => person.id !== member.id);
    for (const card of cards) {
      const matched = card.assignee;
      if (matched && matched.id !== member.id && !list.some((person) => person.id === matched.id)) list.push(matched);
    }
    return list;
  }, [members.data, member.id, cards]);

  const change = (next: EditableDraft) => {
    setEdited(true);
    setCards((all) => all.map((card) => (card.key === next.key ? next : card)));
  };

  const submit = () => {
    if (!left.length || apply.isPending) return;
    const unready = firstUnready(cards, now, timeZone);
    if (unready) {
      setFlagged(unready);
      haptic.notify("warning");
      toast(t("review.fixFirst"), { tone: "error" });
      document.getElementById(cardId(unready))?.scrollIntoView?.({ behavior: "smooth", block: "center" });
      return;
    }
    apply.mutate(applyPayload(cards, now, timeZone), {
      onSuccess: (result) => {
        haptic.notify("success");
        onApplied(result);
      },
      onError: (error) => {
        haptic.notify("error");
        toast(errorText(error, t), { tone: "error" });
      },
    });
  };

  const drop = async () => {
    if (discard.isPending) return;
    if (edited && !(await confirm(t("review.discardAsk")))) return;
    discard.mutate(undefined, {
      onSuccess: () => {
        toast(t("review.discarded"));
        onDiscarded();
      },
      onError: (error) => toast(errorText(error, t), { tone: "error" }),
    });
  };

  if (!draft.drafts.length) {
    return (
      <div className="ai-stage ai-review fade-in">
        {draft.transcript && <Heard text={draft.transcript} voice={draft.audio !== null} />}
        <div className="ai-state">
          <span className="ai-state-icon ai-state-icon--warn" aria-hidden>
            <MessageCircleQuestion size={28} strokeWidth={2.3} />
          </span>
          <div className="heading title-sm">{t("review.emptyTitle")}</div>
          <p className="ai-state-body">{t("review.emptyBody")}</p>
        </div>
        <BottomBar primary={{ text: draft.audio ? t("failed.sayAgain") : t("done.againText"), icon: draft.audio ? Mic : PenLine, onClick: onAgain }} />
      </div>
    );
  }

  return (
    <div className="ai-stage ai-review fade-in">
      <div className="ai-review-head">
        <div className="ui-kicker">{t("review.kicker")}</div>
        <div className="heading title-sm">{t("review.title", { count: left.length })}</div>
      </div>

      {draft.transcript && <Heard text={draft.transcript} voice={draft.audio !== null} />}

      {draft.questions.length > 0 && (
        <div className="ai-questions">
          <span className="ai-questions-label">
            <MessageCircleQuestion size={16} strokeWidth={2.5} aria-hidden />
            {t("review.questions")}
          </span>
          <ul>
            {draft.questions.map((question, index) => (
              <li key={index}>{question}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="ai-cards">
        {cards.map((card, index) => (
          <DraftCard
            key={card.key}
            number={index + 1}
            card={card}
            people={people}
            canAssign={canAssign}
            flagged={flagged === card.key}
            now={now}
            onChange={change}
          />
        ))}
      </div>

      <button type="button" className="btn btn-ghost ai-discard" disabled={discard.isPending} onClick={() => void drop()}>
        {t("review.discard")}
      </button>

      <BottomBar
        primary={{
          text: left.length ? t("review.create", { count: left.length }) : t("review.nothingLeft"),
          icon: Check,
          disabled: !left.length,
          loading: apply.isPending,
          shine: true,
          onClick: submit,
        }}
      />
    </div>
  );
}

const cardId = (key: string) => `ai-card-${key}`;

/** What was heard (or typed), three lines with "Show all" when it runs longer. */
export function Heard({ text, voice }: { text: string; voice: boolean }) {
  const t = useFeatureT(messages);
  const [open, setOpen] = useState(false);
  const long = text.length > 160;
  return (
    <blockquote className={cx("ai-quote", long && !open && "ai-quote--clamped")}>
      <span className="ai-quote-label">
        {voice ? <Mic size={14} strokeWidth={2.6} aria-hidden /> : <PenLine size={14} strokeWidth={2.6} aria-hidden />}
        {t(voice ? "review.heard" : "review.typed")}
      </span>
      <span className="ai-quote-text">{text}</span>
      {long && (
        <button type="button" className="ai-quote-toggle" aria-expanded={open} onClick={() => setOpen(!open)}>
          {open ? t("review.showLess") : t("review.showAll")}
        </button>
      )}
    </blockquote>
  );
}

function DraftCard({
  number,
  card,
  people,
  canAssign,
  flagged,
  now,
  onChange,
}: {
  number: number;
  card: EditableDraft;
  people: readonly AssigneeOption[];
  canAssign: boolean;
  flagged: boolean;
  now: Date;
  onChange: (card: EditableDraft) => void;
}) {
  const t = useFeatureT(messages);
  const ctx = useViewContext();
  const member = useMember();
  const ids = useId();
  const select = useRef<HTMLSelectElement>(null);
  const titleBox = useRef<HTMLTextAreaElement>(null);
  const [editingWhen, setEditingWhen] = useState(false);
  const timeZone = member.timeZone;
  // The title box is as tall as its words (a long title wraps instead of scrolling inside).
  useLayoutEffect(() => {
    if (titleBox.current) grow(titleBox.current);
  }, [card.title, card.removed]);

  if (card.removed) {
    return (
      <div className="ai-card ai-card--removed">
        <span className="ai-card-num" aria-hidden>
          {number}
        </span>
        <span className="ai-card-removed-title">{card.title || t("review.taskTitle")}</span>
        <button type="button" className="btn btn-ghost ai-card-restore" onClick={() => onChange({ ...card, removed: false })}>
          <RotateCcw size={16} strokeWidth={2.6} aria-hidden />
          <span>{t("review.restore")}</span>
        </button>
      </div>
    );
  }

  const problems = problemsOf(card, now, timeZone);
  const who = problems.filter((problem) => WHO.includes(problem));
  const when = problems.filter((problem) => !WHO.includes(problem));
  const due = dueOf(card, now, timeZone);
  const attention = flagged && (problems.some(isBlocking) || !card.title.trim());

  const chooseSomeone = () => {
    const box = select.current;
    if (!box) return;
    box.focus();
    try {
      (box as HTMLSelectElement & { showPicker?: () => void }).showPicker?.();
    } catch {
      // Focus is enough where the list can't be opened from code.
    }
  };

  const fixesFor = (problem: Problem): { label: string; run: () => void }[] => {
    switch (problem) {
      case "no_assignee_match":
      case "ambiguous_assignee":
      case "not_allowed":
        return [
          ...(canAssign ? [{ label: t(problem === "not_allowed" ? "fix.someoneElse" : "fix.choose"), run: chooseSomeone }] : []),
          { label: t("fix.mine"), run: () => onChange(makeMine(card)) },
        ];
      case "no_due":
        return [
          ...(hourIn(now, timeZone) < 17 ? [{ label: t("fix.today", { time: "18:00" }), run: () => onChange(quickDue(card, "today", "18:00")) }] : []),
          { label: t("fix.tomorrow", { time: "09:00" }), run: () => onChange(quickDue(card, "tomorrow", "09:00")) },
          { label: t("add.noDeadline"), run: () => onChange(acceptProblem(card, "no_due")) },
        ];
      case "past_due":
        return due
          ? [
              { label: t("fix.sameTimeTomorrow"), run: () => onChange(sameTimeTomorrow(card, now, timeZone)) },
              { label: t("fix.pickTime"), run: () => setEditingWhen(true) },
            ]
          : [{ label: t("fix.pickTime"), run: () => setEditingWhen(true) }];
    }
  };

  const problemText = (problem: Problem): string => {
    const name = card.assigneeGuess.trim();
    switch (problem) {
      case "no_assignee_match":
        return name ? t("problem.noMatch", { name }) : t("problem.noMatchUnknown");
      case "ambiguous_assignee":
        return name ? t("problem.ambiguous", { name }) : t("problem.noMatchUnknown");
      case "not_allowed":
        return t("problem.notAllowed");
      case "no_due":
        return t("problem.noDue");
      case "past_due":
        return t("problem.pastDue");
    }
  };

  const problemLines = (list: Problem[]) =>
    list.map((problem) => (
      <div key={problem} className={cx("ai-problem", !isBlocking(problem) && "ai-problem--soft")}>
        <span className="ai-problem-text">
          <AlertCircle size={17} strokeWidth={2.5} aria-hidden />
          <span>{problemText(problem)}</span>
        </span>
        <span className="ai-problem-fixes">
          {fixesFor(problem).map((fix) => (
            <button
              key={fix.label}
              type="button"
              className="ui-chip ai-fix"
              onClick={() => {
                haptic.select();
                fix.run();
              }}
            >
              {fix.label}
            </button>
          ))}
        </span>
      </div>
    ));

  return (
    <article id={cardId(card.key)} className={cx("ai-card", attention && "ai-card--attention")} aria-labelledby={`${ids}-title`}>
      <div className="ai-card-head">
        <span className="ai-card-num" aria-hidden>
          {number}
        </span>
        <textarea
          id={`${ids}-title`}
          className="ai-card-title"
          value={card.title}
          rows={1}
          maxLength={200}
          aria-label={t("review.taskTitle")}
          onChange={(event) => onChange({ ...card, title: event.target.value.replace(/\s*\n\s*/g, " ") })}
          ref={titleBox}
        />
        <button
          type="button"
          className="btn btn-ghost btn-icon ai-card-remove"
          aria-label={t("review.remove")}
          onClick={() => {
            haptic.impact("light");
            onChange({ ...card, removed: true });
          }}
        >
          <X size={19} strokeWidth={2.5} />
        </button>
      </div>
      {!card.title.trim() && <span className="ai-card-note">{t("add.read.needTitle")}</span>}

      <div className="ai-row">
        <label className="ai-row-label" htmlFor={`${ids}-for`}>
          <UserRound size={17} strokeWidth={2.4} aria-hidden />
          {t("add.for")}
        </label>
        {canAssign ? (
          <div className="ai-row-control">
            <AssigneeSelect
              ref={select}
              id={`${ids}-for`}
              value={card.assigneeId}
              people={people}
              invalid={who.some(isBlocking)}
              onChange={(assignee) => onChange(pickAssignee(card, assignee))}
            />
          </div>
        ) : (
          <span className="ai-row-value" id={`${ids}-for`}>
            {t("add.forMe")}
          </span>
        )}
      </div>
      {problemLines(who)}

      <div className="ai-row">
        <span className="ai-row-label" id={`${ids}-when`}>
          <CalendarClock size={17} strokeWidth={2.4} aria-hidden />
          {t("add.when")}
        </span>
        <button
          type="button"
          className="ai-row-value ai-row-button"
          aria-expanded={editingWhen}
          aria-describedby={`${ids}-when`}
          onClick={() => {
            haptic.select();
            setEditingWhen(!editingWhen);
          }}
        >
          <span className={cx("num", !due && "muted")}>{due ? formatDue(due.toISOString(), ctx) : t("add.noDeadline")}</span>
          <span className="ai-row-change">{t("review.change")}</span>
        </button>
      </div>
      {editingWhen && (
        <div className="ai-when fade-in">
          <WhenPicker value={card.when} onChange={(value) => onChange(setWhen(card, value))} now={now} timeZone={timeZone} labelledBy={`${ids}-when`} />
        </div>
      )}
      {problemLines(when)}

      <div className="ui-chips ai-card-flags" role="group" aria-label={t("add.options")}>
        <button
          type="button"
          className="ui-chip ui-chip--urgent"
          aria-pressed={card.priority === "urgent"}
          onClick={() => {
            haptic.select();
            onChange({ ...card, priority: card.priority === "urgent" ? "normal" : "urgent" });
          }}
        >
          <Flag size={16} strokeWidth={2.5} aria-hidden />
          <span>{t("priority.urgent")}</span>
        </button>
        <button
          type="button"
          className="ui-chip"
          aria-pressed={card.proof === "photo"}
          onClick={() => {
            haptic.select();
            onChange({ ...card, proof: card.proof === "photo" ? "none" : "photo" });
          }}
        >
          <Camera size={16} strokeWidth={2.5} aria-hidden />
          <span>{t("proof.tag.photo")}</span>
        </button>
      </div>

      {card.description && (
        <div className="field">
          <label htmlFor={`${ids}-description`}>{t("add.description")}</label>
          <textarea
            id={`${ids}-description`}
            className="input plus-grow"
            rows={2}
            maxLength={2000}
            value={card.description}
            onChange={(event) => {
              onChange({ ...card, description: event.target.value });
              grow(event.target);
            }}
          />
        </div>
      )}

      {card.checklist.length > 0 && <StepsEditor steps={card.checklist} onChange={(checklist) => onChange({ ...card, checklist })} />}
    </article>
  );
}

/** Let a text box grow with what's typed (up to about eight lines). */
function grow(box: HTMLTextAreaElement): void {
  box.style.height = "auto";
  box.style.height = `${Math.min(box.scrollHeight, 240)}px`;
}
