/**
 * The question editor's model and its live checks (the same rules the server applies on save,
 * apps/learning/grading.py and docs/PLAN-LEARNING.md §4.3), the learner's view for the preview,
 * and small helpers of the pages (bands, schedules, percentages).
 */
import type {
  Band,
  Check,
  ChoiceOption,
  Difficulty,
  ImageRef,
  MatchPair,
  OrderItem,
  Question,
  QuestionData,
  QuestionKind,
  QuestionPlay,
  QuestionState,
} from "./types";

export const KINDS: readonly QuestionKind[] = ["single", "multi", "true_false", "order", "match", "text", "number"];
export const DIFFICULTIES: readonly Difficulty[] = ["easy", "medium", "hard"];
export const LETTERS = "ABCDEFGH";
export const LIMITS = {
  text: 300,
  question: 1000,
  explanation: 1000,
  options: [2, 6] as const,
  items: [3, 8] as const,
  pairs: [2, 6] as const,
  answers: 10,
  unit: 20,
  points: [1, 10] as const,
};
/** Mastery bands (apps/learning/skills.py): weak below 60, strong from 85. */
export const WEAK = 60;
export const STRONG = 85;

/** Everything the editor can hold; `dataOf` keeps only the kind's part. */
export interface Draft {
  kind: QuestionKind;
  text: string;
  explanation: string;
  topic_id: number | null;
  difficulty: Difficulty;
  points: number;
  image: ImageRef | null;
  state: QuestionState;
  options: ChoiceOption[];
  answer: boolean;
  items: OrderItem[];
  pairs: MatchPair[];
  answers: string[];
  caseSensitive: boolean;
  value: number | null;
  tolerance: number;
  unit: string;
}

export function blankDraft(kind: QuestionKind = "single"): Draft {
  return {
    kind,
    text: "",
    explanation: "",
    topic_id: null,
    difficulty: "medium",
    points: 1,
    image: null,
    state: "active",
    options: [
      { text: "", correct: true },
      { text: "", correct: false },
      { text: "", correct: false },
    ],
    answer: true,
    items: [{ text: "" }, { text: "" }, { text: "" }],
    pairs: [
      { left: "", right: "" },
      { left: "", right: "" },
    ],
    answers: [""],
    caseSensitive: false,
    value: null,
    tolerance: 0,
    unit: "",
  };
}

function list<T>(value: unknown): T[] {
  return Array.isArray(value) ? (value as T[]) : [];
}

export function draftOf(question: Question): Draft {
  const draft = blankDraft(question.kind);
  const data = question.data ?? {};
  Object.assign(draft, {
    text: question.text,
    explanation: question.explanation,
    topic_id: question.topic?.id ?? null,
    difficulty: question.difficulty,
    points: question.points,
    image: question.image,
    state: question.state,
  });
  if (question.kind === "single" || question.kind === "multi") draft.options = list<ChoiceOption>(data.options).map((o) => ({ ...o }));
  if (question.kind === "true_false") draft.answer = data.answer === true;
  if (question.kind === "order") draft.items = list<OrderItem>(data.items).map((i) => ({ ...i }));
  if (question.kind === "match") draft.pairs = list<MatchPair>(data.pairs).map((p) => ({ ...p }));
  if (question.kind === "text") {
    draft.answers = list<string>(data.answers);
    draft.caseSensitive = data.case === true;
  }
  if (question.kind === "number") {
    draft.value = typeof data.value === "number" ? data.value : null;
    draft.tolerance = typeof data.tolerance === "number" ? data.tolerance : 0;
    draft.unit = typeof data.unit === "string" ? data.unit : "";
  }
  return draft;
}

/** The kind's `data` as the server takes it (texts trimmed; empty accepted answers dropped). */
export function dataOf(draft: Draft): QuestionData {
  switch (draft.kind) {
    case "single":
    case "multi":
      return { options: draft.options.map((o) => ({ ...(o.id ? { id: o.id } : {}), text: o.text.trim(), correct: o.correct })) };
    case "true_false":
      return { answer: draft.answer };
    case "order":
      return { items: draft.items.map((i) => ({ ...(i.id ? { id: i.id } : {}), text: i.text.trim() })) };
    case "match":
      return { pairs: draft.pairs.map((p) => ({ ...(p.id ? { id: p.id } : {}), left: p.left.trim(), right: p.right.trim() })) };
    case "text":
      return { answers: draft.answers.map((a) => a.trim()).filter(Boolean), case: draft.caseSensitive };
    case "number":
      return { value: draft.value, tolerance: draft.tolerance, unit: draft.unit.trim() };
  }
}

/** A problem as an i18n key and its values. */
export interface Problem {
  key: string;
  values?: Record<string, unknown>;
}
export type Problems = Record<string, Problem>;

const QUOTES = /[‘’`´ʻʼʹ′‛]/g;
const DASHES = /\s*[‐-―−﹘﹣－-]\s*/g;
// `\p{L}`: in JS `\W` is ASCII even with `u`; Python's `[^\W\d_]` is any letter.
const DEGREES = /\s*°\s*[cCсС]?(?!\p{L})/gu;
// The digit is caught and put back: older Telegram webviews (Safari < 16.4) have no lookbehind.
const CELSIUS = /(\d)\s*[cCсС](?!\p{L})/gu;

/** A typed answer as the server compares it (grading.normalize_text). */
export function normalize(value: string, caseSensitive: boolean): string {
  let text = (value ?? "").normalize("NFKC").replace(QUOTES, "'");
  text = text.replace(DEGREES, "").replace(CELSIUS, "$1").replace(DASHES, "-");
  text = text.split(/\s+/).filter(Boolean).join(" ").replace(/^[.,;:!?"«»“” ]+|[.,;:!?"«»“” ]+$/g, "");
  return caseSensitive ? text : text.toLowerCase();
}

function textProblem(problems: Problems, where: string, value: string, limit: number = LIMITS.text): void {
  const text = value.trim();
  if (!text) problems[where] = { key: "quizzes.err.empty" };
  else if (text.length > limit) problems[where] = { key: "quizzes.err.long", values: { max: limit } };
}

function sameTexts(problems: Problems, where: string, texts: string[]): void {
  const folded = texts.map((text) => normalize(text, false)).filter(Boolean);
  if (new Set(folded).size !== folded.length) problems[where] = { key: "quizzes.err.same" };
}

function countProblem(problems: Problems, where: string, count: number, [low, high]: readonly [number, number]): void {
  if (count < low || count > high) problems[where] = { key: "quizzes.err.count", values: { min: low, max: high } };
}

/** What stops the question being saved, by where (`text`, `options`, `options.1.text`…). */
export function validate(draft: Draft): Problems {
  const problems: Problems = {};
  textProblem(problems, "text", draft.text, LIMITS.question);
  if (draft.explanation.length > LIMITS.explanation) problems.explanation = { key: "quizzes.err.long", values: { max: LIMITS.explanation } };
  if (draft.points < LIMITS.points[0] || draft.points > LIMITS.points[1]) problems.points = { key: "quizzes.err.points" };
  switch (draft.kind) {
    case "single":
    case "multi": {
      draft.options.forEach((option, index) => textProblem(problems, `options.${index}.text`, option.text));
      countProblem(problems, "options", draft.options.length, LIMITS.options);
      if (!problems.options) sameTexts(problems, "options", draft.options.map((o) => o.text));
      const right = draft.options.filter((o) => o.correct).length;
      if (!problems.options && draft.kind === "single" && right !== 1) problems.options = { key: "quizzes.err.oneRight" };
      if (!problems.options && draft.kind === "multi" && right < 1) problems.options = { key: "quizzes.err.someRight" };
      break;
    }
    case "order":
      draft.items.forEach((item, index) => textProblem(problems, `items.${index}.text`, item.text));
      countProblem(problems, "items", draft.items.length, LIMITS.items);
      if (!problems.items) sameTexts(problems, "items", draft.items.map((i) => i.text));
      break;
    case "match":
      draft.pairs.forEach((pair, index) => {
        textProblem(problems, `pairs.${index}.left`, pair.left);
        textProblem(problems, `pairs.${index}.right`, pair.right);
      });
      countProblem(problems, "pairs", draft.pairs.length, LIMITS.pairs);
      if (!problems.pairs) sameTexts(problems, "pairs", draft.pairs.map((p) => p.left));
      if (!problems.pairs) sameTexts(problems, "pairs", draft.pairs.map((p) => p.right));
      break;
    case "text": {
      const answers = draft.answers.map((a) => a.trim()).filter(Boolean);
      if (!answers.length) problems.answers = { key: "quizzes.err.noAnswer" };
      else if (answers.length > LIMITS.answers) problems.answers = { key: "quizzes.err.manyAnswers", values: { max: LIMITS.answers } };
      draft.answers.forEach((answer, index) => {
        if (answer.trim() && !normalize(answer, draft.caseSensitive)) problems[`answers.${index}`] = { key: "quizzes.err.lettersOrDigits" };
        else if (answer.trim().length > LIMITS.text) problems[`answers.${index}`] = { key: "quizzes.err.long", values: { max: LIMITS.text } };
      });
      break;
    }
    case "number":
      if (draft.value === null || !Number.isFinite(draft.value)) problems.value = { key: "quizzes.err.value" };
      if (!(draft.tolerance >= 0)) problems.tolerance = { key: "quizzes.err.tolerance" };
      if (draft.unit.trim().length > LIMITS.unit) problems.unit = { key: "quizzes.err.long", values: { max: LIMITS.unit } };
      break;
    case "true_false":
      break;
  }
  return problems;
}

/** Server errors (`{"data.options.1.text": ["…"]}`) under the editor's own names. */
export function serverProblems(fields: Record<string, string[]>): Record<string, string> {
  const found: Record<string, string> = {};
  for (const [field, messages] of Object.entries(fields)) {
    const where = field.replace(/^data\./, "");
    if (messages[0]) found[where] = messages[0];
  }
  return found;
}

function shuffled<T>(values: readonly T[], random: () => number): T[] {
  const copy = [...values];
  for (let index = copy.length - 1; index > 0; index -= 1) {
    const other = Math.floor(random() * (index + 1));
    [copy[index], copy[other]] = [copy[other]!, copy[index]!];
  }
  return copy;
}

/** A shuffle that never leaves the steps (or the right side) in their right order. */
function mixed<T>(values: readonly T[], random: () => number): T[] {
  if (values.length < 2) return [...values];
  for (let tries = 0; tries < 12; tries += 1) {
    const next = shuffled(values, random);
    if (next.some((value, index) => value !== values[index])) return next;
  }
  return [...values.slice(1), values[0]!];
}

/** The draft as a learner would see it (the preview): options shuffled, steps and the right side
 * mixed, ids by place for order and match — never the answer. */
export function previewOf(draft: Draft, random: () => number = Math.random): QuestionPlay {
  const play: QuestionPlay = {
    id: 0,
    kind: draft.kind,
    text: draft.text,
    image_url: draft.image?.url ?? null,
    points: draft.points,
    options: [],
    left: [],
    right: [],
    unit: null,
  };
  if (draft.kind === "single" || draft.kind === "multi") {
    play.options = shuffled(draft.options, random).map((option, index) => ({ id: option.id ?? `p${index}`, text: option.text }));
  } else if (draft.kind === "order") {
    play.options = mixed(draft.items, random).map((item, index) => ({ id: `o${index + 1}`, text: item.text }));
  } else if (draft.kind === "match") {
    play.left = draft.pairs.map((pair, index) => ({ id: `l${index + 1}`, text: pair.left }));
    play.right = mixed(draft.pairs, random).map((pair, index) => ({ id: `r${index + 1}`, text: pair.right }));
  } else if (draft.kind === "number") {
    play.unit = draft.unit.trim() || null;
  }
  return play;
}

/** Moves an item of a list up or down (the editor's arrows). */
export function moved<T>(values: readonly T[], index: number, step: -1 | 1): T[] {
  const target = index + step;
  if (target < 0 || target >= values.length) return [...values];
  const copy = [...values];
  [copy[index], copy[target]] = [copy[target]!, copy[index]!];
  return copy;
}

/** A mastery score's band (unrated without one). */
export function band(score: number | null | undefined): Band {
  if (score === null || score === undefined) return "unrated";
  if (score < WEAK) return "weak";
  if (score >= STRONG) return "strong";
  return "ok";
}

export const BAND_TONE: Record<Band, "danger" | "warning" | "success" | "neutral"> = {
  weak: "danger",
  ok: "warning",
  strong: "success",
  unrated: "neutral",
};

/** A cell's colours in the skill matrix (tokens, so both themes work). */
export const BAND_CELL: Record<Band, string> = {
  weak: "bg-danger-soft text-danger",
  ok: "bg-warning-soft text-warning",
  strong: "bg-success-soft text-success",
  unrated: "bg-surface-2 text-muted",
};

/** "Every Monday, 10:00" or "Every month on the 1st, 09:00" (`weekday` 0 is Monday). */
export function scheduleText(check: Pick<Check, "every" | "weekday" | "month_day" | "at">, t: (key: string, values?: Record<string, unknown>) => string): string {
  const at = check.at.slice(0, 5);
  if (check.every === "month") return t("quizzes.checks.monthly", { day: check.month_day ?? 1, time: at });
  return t("quizzes.checks.weekly", { day: t(`quizzes.everyWeekday.${check.weekday ?? 0}`), time: at });
}

/** A whole percent, or "—" when there is nothing to divide. */
export function percent(part: number, whole: number): number | null {
  return whole > 0 ? Math.floor((part / whole) * 100) : null;
}

export const DONE_STATES = new Set(["finished", "expired"]);
