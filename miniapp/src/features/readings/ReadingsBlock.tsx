/**
 * Storage readings on the task screen (`task.actions`, PLAN-OWNER §14.10): a routine's run that
 * asks for numbers (a fridge's 2–8 °C, the room's humidity) is finished by typing them here.
 *
 * - My open run: each reading with its allowed range, a field that takes Telegram's number
 *   keyboard ("5,2" or "5.2"), whether the value is in range as it's typed, the note as soon as one
 *   is out of range (the alert carries it), and its own "Save and complete".
 * - A finished run: the values taken with their range, notes and rechecks; within two hours of a
 *   value out of range, "Take it again" for the second measurement.
 * - Someone else's open run: what is measured and the ranges.
 *
 * Nothing at all for a task that takes no readings.
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, RotateCcw, TriangleAlert } from "lucide-react";
import { useRef, useState, type KeyboardEvent } from "react";

import { refreshAfterTaskChange } from "../../api/hooks";
import { useI18n, type Lang } from "../../i18n";
import { useFeatureT, type FeatureTranslate } from "../../i18n/feature";
import { errorText, useDoneToast } from "../../lib/actions";
import { clock } from "../../lib/time";
import type { Member } from "../../state/session";
import { useToast } from "../../state/toast";
import { haptic } from "../../telegram";
import { Badge, Button, Card, CardTitle, cx, Field, Input, Textarea } from "../../ui";
import type { TaskSlotProps } from "../registry";
import {
  asReadingsTask,
  completeWithReadings,
  recheckReadings,
  takesReadings,
  type ReadingSpec,
  type ReadingsTask,
  type ReadingTaken,
} from "./api";
import { entryOf, formatNumber, latestByKey, parseValue, rangeText, stillOut, valueText, type Entry } from "./lib";
import { messages } from "./messages";
import "./readings.css";

const OPEN = ["todo", "in_progress", "returned"];
const NOTE_MAX = 300;

export default function ReadingsBlock({ member, task }: TaskSlotProps) {
  if (!takesReadings(task)) return null;
  const own = asReadingsTask(task);
  if (task.actions.includes("complete")) return <TakeReadings member={member} task={own} />;
  if (own.readings_taken?.length) return <TakenReadings member={member} task={own} />;
  if (OPEN.includes(task.status)) return <AskedReadings task={own} />;
  return null;
}

type Translate = FeatureTranslate<keyof (typeof messages)["en"]>;

/** A value a field suggests: the middle of the range, so a typed-over placeholder reads right. */
function example(spec: ReadingSpec): number {
  const low = spec.min === null ? null : Number(spec.min);
  const high = spec.max === null ? null : Number(spec.max);
  if (low !== null && high !== null) return Number(((low + high) / 2).toFixed(1));
  if (high !== null) return Number((high * 0.8).toFixed(1));
  if (low !== null) return low + 2;
  return 5.2;
}

function problemOf(entry: Entry, t: Translate, lang: Lang): string | undefined {
  if (entry.state === "invalid") return t("notANumber", { example: formatNumber(5.2, lang) });
  if (entry.state === "implausible") return t("implausible");
  return undefined;
}

function RangeState({ entry, t }: { entry: Entry; t: Translate }) {
  if (entry.state !== "in" && entry.state !== "out") return null;
  const out = entry.state === "out";
  return (
    <span className={cx("rdg-state", out ? "rdg-state--out" : "rdg-state--in")} aria-live="polite">
      {out ? <TriangleAlert size={15} strokeWidth={2.6} aria-hidden /> : <Check size={15} strokeWidth={3} aria-hidden />}
      {out ? t("outOfRange") : t("inRange")}
    </span>
  );
}

/** The fields of some specs, the note when a value is out of range, and what's typed so far. */
function useReadingsForm(specs: readonly ReadingSpec[]) {
  const { lang } = useI18n();
  const [values, setValues] = useState<Record<string, string>>({});
  const [note, setNote] = useState("");
  const entries = specs.map((spec) => entryOf(values[spec.key] ?? "", spec));
  const complete = entries.every((entry) => entry.state === "in" || entry.state === "out");
  const anyOut = entries.some((entry) => entry.state === "out");
  const typed = Object.fromEntries(specs.map((spec) => [spec.key, (values[spec.key] ?? "").trim()]));
  return {
    values,
    entries,
    note,
    setNote,
    complete,
    anyOut,
    typed,
    set: (key: string, value: string) => setValues((before) => ({ ...before, [key]: value })),
    /** Shown back in the person's style once they leave the field: "5.2" reads "5,2" in Uzbek. */
    tidy: (key: string) =>
      setValues((before) => {
        const value = parseValue(before[key] ?? "");
        return value === null ? before : { ...before, [key]: formatNumber(value, lang) };
      }),
  };
}

type Form = ReturnType<typeof useReadingsForm>;

function ReadingFields({ specs, form, t, onLast }: { specs: readonly ReadingSpec[]; form: Form; t: Translate; onLast: () => void }) {
  const { lang } = useI18n();
  const inputs = useRef<(HTMLInputElement | null)[]>([]);
  const next = (index: number) => (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key !== "Enter") return;
    event.preventDefault();
    const following = inputs.current[index + 1];
    if (following) following.focus();
    else onLast();
  };
  return (
    <div className="rdg-fields">
      {specs.map((spec, index) => {
        const entry = form.entries[index]!;
        const range = rangeText(spec, lang);
        return (
          <div key={spec.key} className="rdg-field">
            <Field label={spec.label} hint={range ? t("allowed", { range }) : undefined} error={problemOf(entry, t, lang)}>
              <div className="rdg-input">
                <Input
                  ref={(element) => {
                    inputs.current[index] = element;
                  }}
                  num
                  type="text"
                  inputMode="decimal"
                  enterKeyHint={index === specs.length - 1 ? "done" : "next"}
                  autoComplete="off"
                  placeholder={formatNumber(example(spec), lang)}
                  value={form.values[spec.key] ?? ""}
                  onChange={(event) => form.set(spec.key, event.target.value)}
                  onBlur={() => form.tidy(spec.key)}
                  onKeyDown={next(index)}
                  className={cx(entry.state === "out" && "rdg-input--out")}
                />
                {spec.unit && (
                  <span className="rdg-unit" aria-hidden>
                    {spec.unit}
                  </span>
                )}
              </div>
            </Field>
            <RangeState entry={entry} t={t} />
          </div>
        );
      })}
    </div>
  );
}

function NoteField({ form, t, label, required }: { form: Form; t: Translate; label: string; required: boolean }) {
  return (
    <Field label={label} hint={required ? t("noteHint") : undefined} optional={!required}>
      <Textarea
        rows={2}
        maxLength={NOTE_MAX}
        value={form.note}
        placeholder={t("notePlaceholder")}
        onChange={(event) => form.setNote(event.target.value)}
      />
    </Field>
  );
}

function TakeReadings({ member, task }: { member: Member; task: ReadingsTask }) {
  const t = useFeatureT(messages);
  const client = useQueryClient();
  const doneToast = useDoneToast();
  const specs = task.readings ?? [];
  const form = useReadingsForm(specs);
  const [problem, setProblem] = useState<string | null>(null);
  const needsNote = form.anyOut && !form.note.trim();
  const ready = form.complete && !needsNote;
  const save = useMutation({
    mutationFn: () => completeWithReadings(member.companyId, task.id, form.typed, form.anyOut ? form.note.trim() : ""),
    onSuccess: (done) => {
      setProblem(null);
      haptic("success");
      refreshAfterTaskChange(client, member.companyId, done);
      doneToast(done);
    },
    onError: (error: unknown) => {
      haptic("error");
      setProblem(errorText(error, t, t("failed")));
    },
  });
  const submit = () => {
    if (ready && !save.isPending) save.mutate();
  };
  return (
    <Card className="rdg">
      <CardTitle>{t("title")}</CardTitle>
      <ReadingFields specs={specs} form={form} t={t} onLast={submit} />
      {form.anyOut && <NoteField form={form} t={t} label={t("note")} required />}
      <Button variant="primary" size="lg" block loading={save.isPending} disabled={!ready} onClick={submit}>
        {t("save")}
      </Button>
      {problem ? (
        <div className="rdg-problem" role="alert">
          {problem}
        </div>
      ) : needsNote && form.complete ? (
        <div className="rdg-hint">{t("needNote")}</div>
      ) : null}
    </Card>
  );
}

function TakenRow({ reading, member, earlierOut, t }: { reading: ReadingTaken; member: Member; earlierOut: boolean; t: Translate }) {
  const { lang, locale } = useI18n();
  const time = clock(reading.recorded_at, member.timeZone, locale);
  const range = rangeText(reading, lang);
  const state = reading.in_range ? (reading.is_recheck && earlierOut ? t("backInRange") : t("inRange")) : reading.is_recheck ? t("stillOut") : t("outOfRange");
  return (
    <li className={cx("rdg-row", reading.is_recheck && "rdg-row--recheck")}>
      <div className="rdg-row-main">
        <span className="rdg-row-label">
          {reading.label}
          {reading.is_recheck && (
            <Badge size="small" tone="sage" className="rdg-tag">
              {t("recheckTag")}
            </Badge>
          )}
        </span>
        <span className="row-meta">{reading.recorded_by ? t("taken", { time, name: reading.recorded_by.name }) : time}</span>
        {reading.note && <span className="rdg-note">{reading.note}</span>}
      </div>
      <div className="rdg-row-side">
        <span className={cx("rdg-value num", !reading.in_range && "rdg-value--out")}>{valueText(reading.value, reading.unit, lang)}</span>
        <span className={cx("rdg-row-state", reading.in_range ? "rdg-state--in" : "rdg-state--out")}>{state}</span>
        {range && <span className="rdg-range num">{range}</span>}
      </div>
    </li>
  );
}

function TakenReadings({ member, task }: { member: Member; task: ReadingsTask }) {
  const t = useFeatureT(messages);
  const { locale } = useI18n();
  const [rechecking, setRechecking] = useState(false);
  const taken = [...(task.readings_taken ?? [])].sort((a, b) => a.recorded_at.localeCompare(b.recorded_at) || a.id - b.id);
  const out = stillOut(taken);
  const until = task.recheck_until ?? null;
  const mine = task.assignee.id === member.id;
  const canRecheck = mine && until !== null && Date.parse(until) > Date.now() && out.length > 0;
  const firstOut = new Set(taken.filter((reading) => !reading.in_range && !reading.is_recheck).map((reading) => reading.key));
  return (
    <Card className="rdg">
      <CardTitle>{t("title")}</CardTitle>
      <ul className="rdg-list">
        {taken.map((reading) => (
          <TakenRow key={reading.id} reading={reading} member={member} earlierOut={firstOut.has(reading.key)} t={t} />
        ))}
      </ul>
      {canRecheck &&
        (rechecking ? (
          <Recheck member={member} task={task} keys={out} t={t} onClose={() => setRechecking(false)} />
        ) : (
          <div className="rdg-recheck-offer">
            <span className="rdg-hint">{t("recheckHint", { time: clock(until, member.timeZone, locale) })}</span>
            <Button variant="secondary" icon={RotateCcw} onClick={() => setRechecking(true)}>
              {t("recheck")}
            </Button>
          </div>
        ))}
    </Card>
  );
}

/** The second measurement of the keys still out of range: a note only when still out. */
function Recheck({ member, task, keys, t, onClose }: { member: Member; task: ReadingsTask; keys: string[]; t: Translate; onClose: () => void }) {
  const client = useQueryClient();
  const toast = useToast();
  const latest = latestByKey(task.readings_taken ?? []);
  const specs: ReadingSpec[] = keys.map((key) => {
    const spec = task.readings?.find((candidate) => candidate.key === key);
    const reading = latest.get(key)!;
    return spec ?? { key, label: reading.label, unit: reading.unit, min: reading.min, max: reading.max, critical: false };
  });
  const form = useReadingsForm(specs);
  const [problem, setProblem] = useState<string | null>(null);
  const needsNote = form.anyOut && !form.note.trim();
  const ready = form.complete && !needsNote;
  const save = useMutation({
    mutationFn: () => recheckReadings(member.companyId, task.id, form.typed, form.note.trim()),
    onSuccess: (updated) => {
      haptic("success");
      refreshAfterTaskChange(client, member.companyId, updated);
      toast(form.anyOut ? t("recheckSaved") : t("backInRange"), { tone: "success" });
      onClose();
    },
    onError: (error: unknown) => {
      haptic("error");
      setProblem(errorText(error, t, t("failed")));
    },
  });
  const submit = () => {
    if (ready && !save.isPending) save.mutate();
  };
  return (
    <div className="rdg-recheck">
      <div className="card-title">{t("recheck")}</div>
      <ReadingFields specs={specs} form={form} t={t} onLast={submit} />
      <NoteField form={form} t={t} label={t("recheckNote")} required={form.anyOut} />
      <div className="rdg-recheck-actions">
        <Button variant="ghost" onClick={onClose} disabled={save.isPending}>
          {t("recheckCancel")}
        </Button>
        <Button variant="primary" loading={save.isPending} disabled={!ready} onClick={submit}>
          {t("recheckSave")}
        </Button>
      </div>
      {problem ? (
        <div className="rdg-problem" role="alert">
          {problem}
        </div>
      ) : needsNote && form.complete ? (
        <div className="rdg-hint">{t("needNote")}</div>
      ) : null}
    </div>
  );
}

/** Someone else's open run: what it measures, and the ranges. */
function AskedReadings({ task }: { task: ReadingsTask }) {
  const t = useFeatureT(messages);
  const { lang } = useI18n();
  return (
    <Card className="rdg">
      <CardTitle>{t("asked")}</CardTitle>
      <ul className="rdg-list">
        {(task.readings ?? []).map((spec) => {
          const range = rangeText(spec, lang);
          return (
            <li key={spec.key} className="rdg-row">
              <span className="rdg-row-label">{spec.label}</span>
              {range && <span className="rdg-range num">{t("allowed", { range })}</span>}
            </li>
          );
        })}
      </ul>
    </Card>
  );
}
