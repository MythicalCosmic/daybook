/**
 * The seven kinds of question (docs/PLAN-LEARNING.md §4.3) as the person answers them, with big
 * touch targets: radio cards (single), checkbox cards (multi), two big buttons (true/false), a
 * list with up/down buttons and a drag handle (order), tap a left then a right with colour pairs
 * (match), a text box (text) and a number box with its unit (number). The same inputs serve the
 * quiz player and the question of the day; `AnswerText` says an answer back in a review.
 */
import { ArrowDown, ArrowUp, Check, GripVertical, X } from "lucide-react";
import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";

import { useI18n } from "../../i18n";
import { useNavigation } from "../../state/navigation";
import { disableVerticalSwipes, haptic } from "../../telegram";
import { cx, IconButton, Input } from "../../ui";
import { formatNumber, letter, parseNumber } from "./lib";
import type { Answer, Choice, QuestionKind, QuestionPlay, RightAnswer } from "./types";
import { useLearningT, type LearningKey } from "./text";

/** How an answer changed: a tap is saved at once, typing a moment after the last key. */
export type Commit = "now" | "soon";

type InputProps = {
  question: QuestionPlay;
  value: Answer | null | undefined;
  onChange: (answer: Answer, commit: Commit) => void;
  disabled?: boolean;
};

const HINT: Record<QuestionKind, LearningKey> = {
  single: "q.single",
  multi: "q.multi",
  true_false: "q.trueFalse",
  order: "q.order",
  match: "q.match",
  text: "q.text",
  number: "q.number",
};

/** The question itself: its picture (a tap shows all of it), the text and what to do. */
export function QuestionHead({ question, compact = false }: { question: QuestionPlay; compact?: boolean }) {
  const t = useLearningT();
  const navigation = useNavigation();
  return (
    <div className={cx("lrn-qhead", compact && "lrn-qhead--compact")}>
      {question.image_url && (
        <button type="button" className="lrn-qimage" aria-label={t("q.image")} onClick={() => navigation.openSheet({ kind: "photo", src: question.image_url! })}>
          <img src={question.image_url} alt="" loading="lazy" />
        </button>
      )}
      <p className="lrn-qtext">{question.text}</p>
      <p className="lrn-qhint">{t(HINT[question.kind])}</p>
    </div>
  );
}

/** The answer input for any kind. */
export function QuestionInput(props: InputProps) {
  switch (props.question.kind) {
    case "single":
      return <SingleInput {...props} />;
    case "multi":
      return <MultiInput {...props} />;
    case "true_false":
      return <TrueFalseInput {...props} />;
    case "order":
      return <OrderInput {...props} />;
    case "match":
      return <MatchInput {...props} />;
    case "text":
      return <TextInput {...props} />;
    case "number":
      return <NumberInput {...props} />;
  }
}

function SingleInput({ question, value, onChange, disabled }: InputProps) {
  const t = useLearningT();
  const chosen = value && "option" in value ? value.option : null;
  return (
    <div className="lrn-choices" role="radiogroup" aria-label={t("q.single")}>
      {question.options.map((option, index) => {
        const on = option.id === chosen;
        return (
          <button
            key={option.id}
            type="button"
            role="radio"
            aria-checked={on}
            disabled={disabled}
            className={cx("lrn-choice", on && "lrn-choice--on")}
            onClick={() => {
              if (on) return;
              haptic.select();
              onChange({ option: option.id }, "now");
            }}
          >
            <span className="lrn-choice-mark" aria-hidden>
              {letter(index)}
            </span>
            <span className="lrn-choice-text">{option.text}</span>
          </button>
        );
      })}
    </div>
  );
}

function MultiInput({ question, value, onChange, disabled }: InputProps) {
  const t = useLearningT();
  const chosen = new Set(value && "options" in value ? value.options : []);
  return (
    <div className="lrn-choices" role="group" aria-label={t("q.multi")}>
      {question.options.map((option, index) => {
        const on = chosen.has(option.id);
        return (
          <button
            key={option.id}
            type="button"
            role="checkbox"
            aria-checked={on}
            disabled={disabled}
            className={cx("lrn-choice lrn-choice--multi", on && "lrn-choice--on")}
            onClick={() => {
              haptic.select();
              // Kept in the order shown, so the saved answer doesn't depend on the order of taps.
              const next = question.options.map((item) => item.id).filter((id) => (id === option.id ? !on : chosen.has(id)));
              onChange({ options: next }, "now");
            }}
          >
            <span className="lrn-choice-mark lrn-choice-mark--box" aria-hidden>
              {on ? <Check size={16} strokeWidth={3} /> : letter(index)}
            </span>
            <span className="lrn-choice-text">{option.text}</span>
          </button>
        );
      })}
    </div>
  );
}

function TrueFalseInput({ value, onChange, disabled }: InputProps) {
  const t = useLearningT();
  const chosen = value && "value" in value && typeof value.value === "boolean" ? value.value : null;
  const button = (answer: boolean) => (
    <button
      type="button"
      role="radio"
      aria-checked={chosen === answer}
      disabled={disabled}
      className={cx("lrn-tf", answer ? "lrn-tf--true" : "lrn-tf--false", chosen === answer && "lrn-tf--on")}
      onClick={() => {
        if (chosen === answer) return;
        haptic.select();
        onChange({ value: answer }, "now");
      }}
    >
      {answer ? <Check size={26} strokeWidth={3} aria-hidden /> : <X size={26} strokeWidth={3} aria-hidden />}
      <span>{t(answer ? "q.true" : "q.false")}</span>
    </button>
  );
  return (
    <div className="lrn-tfs" role="radiogroup" aria-label={t("q.trueFalse")}>
      {button(true)}
      {button(false)}
    </div>
  );
}

/** The order shown: the saved one when it holds exactly these items, else the server's shuffle. */
export function orderOf(question: QuestionPlay, value: Answer | null | undefined): string[] {
  const shown = question.options.map((option) => option.id);
  const saved = value && "order" in value ? value.order : null;
  if (saved && saved.length === shown.length && shown.every((id) => saved.includes(id))) return saved;
  return shown;
}

/** Move the item at `from` to `to`. */
export function moveItem<T>(list: readonly T[], from: number, to: number): T[] {
  const next = [...list];
  const [item] = next.splice(from, 1);
  next.splice(Math.max(0, Math.min(next.length, to)), 0, item);
  return next;
}

/**
 * Where a dragged row goes: past half of the neighbour's height it swaps with it. `offset` is how
 * far the finger moved since the drag (re)started; the caller moves its start by the swapped
 * row's height so the row stays under the finger.
 */
export function dragStep(index: number, offset: number, heights: readonly number[]): { to: number; shift: number } {
  if (offset > 0 && index < heights.length - 1 && offset > heights[index + 1] / 2) return { to: index + 1, shift: heights[index + 1] };
  if (offset < 0 && index > 0 && -offset > heights[index - 1] / 2) return { to: index - 1, shift: -heights[index - 1] };
  return { to: index, shift: 0 };
}

function OrderInput({ question, value, onChange, disabled }: InputProps) {
  const t = useLearningT();
  const order = orderOf(question, value);
  const byId = new Map(question.options.map((option) => [option.id, option] as const));
  const list = useRef<HTMLOListElement>(null);
  const drag = useRef<{ id: string; startY: number; pointer: number; release: () => void } | null>(null);
  const [dragging, setDragging] = useState<{ id: string; offset: number } | null>(null);
  const live = useRef(order);
  live.current = order;

  const move = (from: number, to: number) => {
    if (to < 0 || to >= order.length || from === to) return;
    haptic.select();
    onChange({ order: moveItem(order, from, to) }, "now");
  };

  const heights = () => [...(list.current?.children ?? [])].map((row) => (row as HTMLElement).getBoundingClientRect().height);

  const onPointerDown = (event: ReactPointerEvent<HTMLSpanElement>, id: string) => {
    if (disabled || drag.current) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture?.(event.pointerId);
    // While a finger drags a row, Telegram's swipe-down must not close the app.
    drag.current = { id, startY: event.clientY, pointer: event.pointerId, release: disableVerticalSwipes() };
    setDragging({ id, offset: 0 });
    haptic.impact("light");
  };
  const onPointerMove = (event: ReactPointerEvent<HTMLSpanElement>) => {
    const state = drag.current;
    if (!state || event.pointerId !== state.pointer) return;
    const current = live.current;
    const index = current.indexOf(state.id);
    const offset = event.clientY - state.startY;
    const step = dragStep(index, offset, heights());
    if (step.to !== index) {
      state.startY += step.shift;
      haptic.select();
      onChange({ order: moveItem(current, index, step.to) }, "now");
      setDragging({ id: state.id, offset: offset - step.shift });
    } else {
      setDragging({ id: state.id, offset });
    }
  };
  const onPointerEnd = (event: ReactPointerEvent<HTMLSpanElement>) => {
    const state = drag.current;
    if (!state || event.pointerId !== state.pointer) return;
    state.release();
    drag.current = null;
    setDragging(null);
  };
  // A page closed mid-drag gives the swipe back.
  useEffect(() => () => drag.current?.release(), []);

  return (
    <ol ref={list} className="lrn-order" aria-label={t("q.order")}>
      {order.map((id, index) => {
        const item = byId.get(id);
        const lifted = dragging?.id === id;
        return (
          <li key={id} className={cx("lrn-order-row", lifted && "lrn-order-row--lifted")} style={lifted ? { transform: `translateY(${dragging.offset}px)` } : undefined}>
            <span
              className="lrn-order-grip"
              role="img"
              aria-label={t("q.drag")}
              onPointerDown={(event) => onPointerDown(event, id)}
              onPointerMove={onPointerMove}
              onPointerUp={onPointerEnd}
              onPointerCancel={onPointerEnd}
            >
              <GripVertical size={20} strokeWidth={2.4} aria-hidden />
            </span>
            <span className="lrn-order-n num" aria-hidden>
              {index + 1}
            </span>
            <span className="lrn-order-text">{item?.text}</span>
            <span className="lrn-order-moves">
              <IconButton icon={ArrowUp} label={t("q.up")} size={42} variant="ghost" disabled={disabled || index === 0} onClick={() => move(index, index - 1)} />
              <IconButton icon={ArrowDown} label={t("q.down")} size={42} variant="ghost" disabled={disabled || index === order.length - 1} onClick={() => move(index, index + 1)} />
            </span>
          </li>
        );
      })}
    </ol>
  );
}

/** Pairs of a match answer, only of the question's own ids. */
export function pairsOf(question: QuestionPlay, value: Answer | null | undefined): Record<string, string> {
  const saved = value && "pairs" in value ? value.pairs : {};
  const left = new Set(question.left.map((item) => item.id));
  const right = new Set(question.right.map((item) => item.id));
  return Object.fromEntries(Object.entries(saved).filter(([l, r]) => left.has(l) && right.has(r)));
}

function MatchInput({ question, value, onChange, disabled }: InputProps) {
  const t = useLearningT();
  const pairs = pairsOf(question, value);
  const firstOpen = (current: Record<string, string>) => question.left.find((item) => !current[item.id])?.id ?? null;
  const [active, setActive] = useState<string | null>(() => firstOpen(pairs));
  const colour = new Map(question.left.map((item, index) => [item.id, index] as const));
  const leftOf = new Map(Object.entries(pairs).map(([l, r]) => [r, l] as const));

  const pickLeft = (id: string) => {
    haptic.select();
    setActive(active === id ? null : id);
  };
  const pickRight = (id: string) => {
    if (active) {
      const next = Object.fromEntries(Object.entries(pairs).filter(([l, r]) => l !== active && r !== id));
      next[active] = id;
      haptic.select();
      onChange({ pairs: next }, "now");
      setActive(firstOpen(next));
      return;
    }
    const owner = leftOf.get(id);
    if (owner) {
      // A tap on a matched right with nothing picked undoes that pair.
      const next = Object.fromEntries(Object.entries(pairs).filter(([l]) => l !== owner));
      haptic.select();
      onChange({ pairs: next }, "now");
      setActive(owner);
    }
  };

  const cell = (item: Choice, side: "left" | "right") => {
    const partner = side === "left" ? pairs[item.id] : leftOf.get(item.id);
    const leftId = side === "left" ? item.id : partner;
    const index = leftId !== undefined ? colour.get(leftId) : undefined;
    const matched = partner !== undefined;
    const on = side === "left" && active === item.id;
    return (
      <button
        key={item.id}
        type="button"
        disabled={disabled}
        aria-pressed={side === "left" ? on : matched}
        className={cx("lrn-match-cell", matched && index !== undefined && `lrn-pair--${index % 6}`, matched && "lrn-match-cell--paired", on && "lrn-match-cell--active")}
        onClick={() => (side === "left" ? pickLeft(item.id) : pickRight(item.id))}
      >
        {matched && index !== undefined && (
          <span className="lrn-match-n num" aria-label={t("q.pair", { n: index + 1 })}>
            {index + 1}
          </span>
        )}
        <span className="lrn-match-text">{item.text}</span>
      </button>
    );
  };

  return (
    <div className="lrn-match" role="group" aria-label={t("q.match")}>
      <div className="lrn-match-col">{question.left.map((item) => cell(item, "left"))}</div>
      <div className="lrn-match-col">{question.right.map((item) => cell(item, "right"))}</div>
    </div>
  );
}

function TextInput({ value, onChange, disabled }: InputProps) {
  const t = useLearningT();
  const saved = value && "text" in value ? value.text : "";
  const [draft, setDraft] = useState(saved);
  return (
    <Input
      className="lrn-answer-input"
      value={draft}
      disabled={disabled}
      maxLength={300}
      placeholder={t("q.placeholder")}
      aria-label={t("q.text")}
      autoComplete="off"
      autoCapitalize="off"
      enterKeyHint="done"
      onChange={(event) => {
        setDraft(event.target.value);
        onChange({ text: event.target.value }, "soon");
      }}
      onBlur={() => {
        if (draft.trim()) onChange({ text: draft }, "now");
      }}
    />
  );
}

function NumberInput({ question, value, onChange, disabled }: InputProps) {
  const t = useLearningT();
  const { locale } = useI18n();
  const saved = value && "value" in value && typeof value.value === "number" ? formatNumber(value.value, locale).replace(/\s/g, "") : "";
  const [draft, setDraft] = useState(saved);
  return (
    <div className="lrn-number">
      <Input
        className="lrn-answer-input num"
        value={draft}
        disabled={disabled}
        inputMode="decimal"
        placeholder={t("q.numberPlaceholder")}
        aria-label={t("q.number")}
        autoComplete="off"
        enterKeyHint="done"
        onChange={(event) => {
          setDraft(event.target.value);
          const parsed = parseNumber(event.target.value);
          if (parsed !== null) onChange({ value: parsed }, "soon");
        }}
        onBlur={() => {
          const parsed = parseNumber(draft);
          if (parsed !== null) onChange({ value: parsed }, "now");
        }}
      />
      {question.unit && <span className="lrn-unit">{question.unit}</span>}
    </div>
  );
}

// — saying an answer back —

const optionText = (question: QuestionPlay, id: string | undefined) => question.options.find((option) => option.id === id)?.text ?? id ?? "";

/** An answer (the person's or the right one) as words, for the review and the day's result. */
export function AnswerText({ question, answer }: { question: QuestionPlay; answer: Answer | RightAnswer | null | undefined }) {
  const t = useLearningT();
  const { locale } = useI18n();
  if (!answer) return <span className="lrn-answer-none">{t("answer.none")}</span>;
  const a = answer as RightAnswer;
  switch (question.kind) {
    case "single":
      return <span>{optionText(question, a.option)}</span>;
    case "multi":
      return (a.options ?? []).length ? (
        <ul className="lrn-answer-list">
          {(a.options ?? []).map((id) => (
            <li key={id}>{optionText(question, id)}</li>
          ))}
        </ul>
      ) : (
        <span className="lrn-answer-none">{t("answer.none")}</span>
      );
    case "true_false":
      return <span>{typeof a.value === "boolean" ? t(a.value ? "q.true" : "q.false") : t("answer.none")}</span>;
    case "order":
      return (
        <ol className="lrn-answer-list lrn-answer-list--numbered">
          {(a.order ?? []).map((id) => (
            <li key={id}>{optionText(question, id)}</li>
          ))}
        </ol>
      );
    case "match": {
      const rightText = (id: string) => question.right.find((item) => item.id === id)?.text ?? id;
      const rows = question.left.filter((item) => a.pairs?.[item.id]);
      if (!rows.length) return <span className="lrn-answer-none">{t("answer.none")}</span>;
      return (
        <span className="lrn-answer-pairs">
          {rows.map((item) => (
            <span key={item.id} className="lrn-answer-pair">
              <span>{item.text}</span>
              <span className="lrn-answer-dash" aria-hidden>
                –
              </span>
              <span>{rightText(a.pairs![item.id])}</span>
            </span>
          ))}
        </span>
      );
    }
    case "text": {
      const texts = a.answers?.length ? a.answers : a.text !== undefined ? [a.text] : [];
      return <span>{texts.join(` ${t("answer.or")} `) || t("answer.none")}</span>;
    }
    case "number": {
      if (typeof a.value !== "number") return <span className="lrn-answer-none">{t("answer.none")}</span>;
      const unit = a.unit ?? question.unit;
      const tolerance = a.tolerance ? ` ± ${formatNumber(a.tolerance, locale)}` : "";
      return (
        <span className="num">
          {formatNumber(a.value, locale)}
          {tolerance}
          {unit ? ` ${unit}` : ""}
        </span>
      );
    }
  }
}
