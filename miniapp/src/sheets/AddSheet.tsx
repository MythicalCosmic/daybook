import { CalendarClock, Camera, ChevronDown, Eye, Flag, Plus, Repeat as RepeatIcon, X } from "lucide-react";
import { useId, useMemo, useState } from "react";

import { useCreateTask, useMembers, type NewTask } from "../api/hooks";
import type { QuickAdd, Repeat } from "../api/types";
import { FeatureSlot } from "../features/FeatureSlot";
import { useI18n } from "../i18n";
import { errorText } from "../lib/actions";
import { quickAddAvailable, readPassed, readSignature, recognised, useQuickAdd } from "../lib/quickAdd";
import { addDays, clock, dayKey, hourIn, zonedInstant } from "../lib/time";
import { useDraftGuard } from "../lib/useDraftGuard";
import { useNavigation } from "../state/navigation";
import { useMember } from "../state/session";
import { useToast } from "../state/toast";
import { haptic } from "../telegram";
import { BottomBar } from "../ui";

const REPEATS: Repeat[] = ["none", "daily", "weekdays", "weekly"];
type When = "today" | "tomorrow" | "date" | "none";
const TITLE_MAX = 200;
const STEPS_MAX = 50;

/**
 * The (+) sheet: a task for me, or (for whoever hands out work) for a colleague. The title is read
 * as it's typed ("Kassani sanash ertaga 18:00"): what was understood shows under it with the
 * weekday and the date, and "Not a date" keeps the words in the title (R2 T1/T2). The deadline
 * the client sends is always one the person saw.
 */
export function AddSheet() {
  const { t, locale } = useI18n();
  const member = useMember();
  const navigation = useNavigation();
  const create = useCreateTask(member.companyId);
  const toast = useToast();
  const ids = useId();
  const canAssign = member.permissions.includes("tasks.assign");
  const members = useMembers(member.companyId, canAssign);

  const [now] = useState(() => new Date());
  const hour = hourIn(now, member.timeZone);
  const today = dayKey(now, member.timeZone);
  // Default to the next full hour today, or tomorrow morning when the day is nearly over.
  const [when, setWhen] = useState<When>(hour < 22 ? "today" : "tomorrow");
  const [time, setTime] = useState(hour < 22 ? `${String(hour + 1).padStart(2, "0")}:00` : "09:00");
  const [date, setDate] = useState(addDays(today, 2));
  const [title, setTitle] = useState("");
  const [repeat, setRepeat] = useState<Repeat>("none");
  const [assignee, setAssignee] = useState<number | null>(null);
  const [urgentChoice, setUrgentChoice] = useState<boolean | null>(null);
  const [needsPhoto, setNeedsPhoto] = useState(false);
  const [illCheck, setIllCheck] = useState(false);
  const [details, setDetails] = useState(false);
  const [description, setDescription] = useState("");
  const [steps, setSteps] = useState<string[]>([]);
  const [dismissed, setDismissed] = useState<string | null>(null);
  const [flushing, setFlushing] = useState(false);

  const quick = useQuickAdd(member.companyId, title);
  const read = applied(quick.result, dismissed);
  const readsDue = Boolean(read?.due_at);
  // "bugun 01:00" typed at 03:00: nothing is read from it, and the sheet says why.
  const passed = !quick.stale && readPassed(title, quick.result);
  const people = useMemo(
    () => (members.data ?? []).filter((person) => person.id !== member.id),
    [members.data, member.id],
  );
  const forName = assignee === null ? null : people.find((person) => person.id === assignee)?.name ?? null;
  const urgent = urgentChoice ?? read?.priority === "urgent";

  // What the manual "When" means: a past time today rolls to tomorrow, and says so (as the bot does).
  const manualDay = when === "today" ? today : when === "tomorrow" ? addDays(today, 1) : when === "date" ? date : null;
  const manualInstant = manualDay ? zonedInstant(manualDay, time, member.timeZone) : null;
  const rolled = when === "today" && manualInstant !== null && manualInstant <= now;
  const manualDue = manualInstant && rolled ? zonedInstant(addDays(today, 1), time, member.timeZone) : manualInstant;
  const due = readsDue ? read!.due_at : manualDue ? manualDue.toISOString() : null;

  const filledSteps = steps.map((step) => step.trim()).filter(Boolean);
  const dirty = Boolean(title.trim() || description.trim() || filledSteps.length);
  useDraftGuard(dirty);
  const missingTitle = Boolean(read && !read.title.trim() && title.trim());
  const canSubmit = Boolean(title.trim()) && !missingTitle && !(when === "date" && !date && !readsDue);

  const submit = async () => {
    if (!canSubmit || create.isPending || flushing) return;
    let reading = read;
    if (quick.stale) {
      // Pressed before the text was read: read it now, and if that finds something new, show it
      // first rather than save a deadline nobody saw.
      setFlushing(true);
      const fresh = applied(await quick.flush(), dismissed);
      setFlushing(false);
      if ((fresh ? readSignature(fresh) : "") !== (reading ? readSignature(reading) : "")) return;
      if (fresh && !fresh.title.trim()) return;
      reading = fresh;
    }
    const finalDue = reading?.due_at ?? (manualDue ? manualDue.toISOString() : null);
    const task: NewTask = {
      title: (reading ? reading.title : title).trim(),
      due_at: finalDue,
      // Repeats are for my own tasks: a colleague's repeating work is a routine on the dashboard.
      repeat: assignee !== null || !finalDue ? "none" : reading?.repeat ?? repeat,
    };
    if (urgentChoice ?? reading?.priority === "urgent") task.priority = "urgent";
    if (assignee !== null) {
      task.assignee_id = assignee;
      if (needsPhoto) task.proof = "photo";
      if (illCheck) task.needs_confirmation = true;
    }
    if (description.trim()) task.description = description.trim();
    if (filledSteps.length) task.checklist = filledSteps;
    create.mutate(task, {
      onSuccess: () => {
        haptic("success");
        if (assignee !== null) {
          navigation.goTo("tasks", "given");
          toast(t("toast.given", { name: forName ?? "" }));
        } else {
          navigation.goTo("tasks", "personal");
          toast(t("toast.added"));
        }
      },
      onError: (error) => toast(errorText(error, t)),
    });
  };

  return (
    <>
      <FeatureSlot name="plus.actions" />
      <div className="heading title-sm">{t("add.title")}</div>

      {canAssign && (
        <div className="field">
          <label htmlFor={`${ids}-for`}>{t("add.for")}</label>
          <select
            id={`${ids}-for`}
            className="input"
            value={assignee ?? ""}
            onChange={(event) => {
              haptic.select();
              setAssignee(event.target.value ? Number(event.target.value) : null);
            }}
          >
            <option value="">{t("add.forMe")}</option>
            {people.map((person) => (
              <option key={person.id} value={person.id}>
                {person.position ? `${person.name} · ${person.position}` : person.name}
              </option>
            ))}
          </select>
        </div>
      )}

      <div className="field">
        <label htmlFor={`${ids}-title`}>{t("add.what")}</label>
        <input
          id={`${ids}-title`}
          className="input"
          placeholder={t(quickAddAvailable() ? "add.placeholderQuick" : "add.placeholder")}
          value={title}
          maxLength={TITLE_MAX}
          enterKeyHint="done"
          autoComplete="off"
          onChange={(event) => setTitle(event.target.value)}
          onKeyDown={(event) => event.key === "Enter" && void submit()}
        />
        {title.length > TITLE_MAX - 40 && <span className="field-count num">{`${title.length}/${TITLE_MAX}`}</span>}
      </div>

      {read && (
        <QuickRead
          read={read}
          urgent={urgent}
          missingTitle={missingTitle}
          forColleague={assignee !== null}
          onDismiss={() => {
            haptic.select();
            setDismissed(readSignature(read));
            setUrgentChoice(null);
          }}
        />
      )}

      {!readsDue && (
        <div className="field">
          <span className="field-label" id={`${ids}-when`}>{t("add.when")}</span>
          {passed && (
            <span className="field-note" role="status">
              {t("add.passed")}
            </span>
          )}
          <div className="ui-chips" role="group" aria-labelledby={`${ids}-when`}>
            {(["today", "tomorrow", "date", "none"] as const).map((option) => (
              <button
                key={option}
                type="button"
                className="ui-chip"
                aria-pressed={when === option}
                onClick={() => {
                  haptic.select();
                  setWhen(option);
                }}
              >
                <span>{t(WHEN_LABEL[option])}</span>
              </button>
            ))}
          </div>
          {when !== "none" && (
            <div className="plus-when">
              {when === "date" && (
                <input
                  className="input num"
                  type="date"
                  aria-label={t("add.date")}
                  min={addDays(today, 1)}
                  value={date}
                  onChange={(event) => setDate(event.target.value)}
                />
              )}
              <input className="input num" type="time" aria-label={t("add.time")} value={time} onChange={(event) => setTime(event.target.value || time)} />
            </div>
          )}
          {rolled && manualDue && <span className="field-note num">{t("add.rolled", { time: clock(manualDue, member.timeZone, locale) })}</span>}
        </div>
      )}

      <div className="ui-chips" role="group" aria-label={t("add.options")}>
        <button type="button" className="ui-chip ui-chip--urgent" aria-pressed={urgent} onClick={() => setUrgentChoice(!urgent)}>
          <Flag size={16} strokeWidth={2.5} aria-hidden />
          <span>{t("priority.urgent")}</span>
        </button>
        {assignee !== null && (
          <>
            <button type="button" className="ui-chip" aria-pressed={needsPhoto} onClick={() => setNeedsPhoto(!needsPhoto)}>
              <Camera size={16} strokeWidth={2.5} aria-hidden />
              <span>{t("proof.tag.photo")}</span>
            </button>
            <button type="button" className="ui-chip" aria-pressed={illCheck} onClick={() => setIllCheck(!illCheck)}>
              <Eye size={16} strokeWidth={2.5} aria-hidden />
              <span>{t("add.illCheck")}</span>
            </button>
          </>
        )}
      </div>

      {assignee === null && due && !read?.repeat && (
        <div className="field">
          <label htmlFor={`${ids}-repeat`}>{t("add.repeat")}</label>
          <select id={`${ids}-repeat`} className="input" value={repeat} onChange={(event) => setRepeat(event.target.value as Repeat)}>
            {REPEATS.map((option) => (
              <option key={option} value={option}>{t(`add.repeat.${option}`)}</option>
            ))}
          </select>
        </div>
      )}

      {details ? (
        <>
          <div className="field">
            <label htmlFor={`${ids}-description`}>{t("add.description")}</label>
            <textarea
              id={`${ids}-description`}
              className="input"
              rows={3}
              maxLength={2000}
              placeholder={t("add.descriptionPlaceholder")}
              value={description}
              onChange={(event) => setDescription(event.target.value)}
            />
          </div>
          <StepsEditor steps={steps} onChange={setSteps} />
        </>
      ) : (
        <button
          type="button"
          className="btn btn-ghost plus-more"
          aria-expanded={false}
          onClick={() => {
            haptic.select();
            setDetails(true);
          }}
        >
          <ChevronDown size={18} strokeWidth={2.5} aria-hidden />
          <span>{t("add.more")}</span>
        </button>
      )}

      <BottomBar
        primary={{
          text: assignee !== null ? t("add.give") : t("add.submit"),
          icon: Plus,
          disabled: !canSubmit,
          loading: create.isPending || flushing,
          onClick: () => void submit(),
        }}
      />
    </>
  );
}

const WHEN_LABEL = { today: "day.today", tomorrow: "day.tomorrow", date: "add.otherDay", none: "add.noDeadline" } as const;

/** The reading, unless it found nothing or the person said it isn't one. */
function applied(result: QuickAdd | null, dismissed: string | null): QuickAdd | null {
  return recognised(result) && readSignature(result) !== dismissed ? result : null;
}

/**
 * What the typed text was read as: "⏰ Ertaga, 22-oktabr (payshanba), 18:00", the title without
 * those words, urgency and repeat, and the one tap that keeps the words as typed.
 */
function QuickRead({
  read,
  urgent,
  missingTitle,
  forColleague,
  onDismiss,
}: {
  read: QuickAdd;
  urgent: boolean;
  missingTitle: boolean;
  /** A colleague's task doesn't repeat: say so rather than drop the repeat that was read. */
  forColleague: boolean;
  onDismiss: () => void;
}) {
  const { t } = useI18n();
  const repeat = read.repeat && !forColleague ? read.repeat : null;
  return (
    <div className="qa-read" role="status" aria-label={t("add.read.label")}>
      <span className="qa-read-icon" aria-hidden>
        <CalendarClock size={18} strokeWidth={2.5} />
      </span>
      <span className="qa-read-main">
        {read.due_at && read.due_label && <span className="qa-read-when num">{read.due_label}</span>}
        {(urgent || repeat) && (
          <span className="qa-read-tags">
            {urgent && (
              <span className="prio prio--urgent">
                <Flag size={12} strokeWidth={2.8} aria-hidden />
                {t("priority.urgent")}
              </span>
            )}
            {repeat && (
              <span className="qa-read-tag">
                <RepeatIcon size={13} strokeWidth={2.6} aria-hidden />
                {t(`add.repeat.${repeat}`)}
              </span>
            )}
          </span>
        )}
        {read.repeat && forColleague && <span className="qa-read-title">{t("add.read.noRepeat")}</span>}
        {missingTitle ? (
          <span className="qa-read-title qa-read-title--missing">{t("add.read.needTitle")}</span>
        ) : (
          <span className="qa-read-title">{t("add.read.title", { title: read.title.trim() })}</span>
        )}
        <button type="button" className="qa-read-undo" onClick={onDismiss}>
          <X size={15} strokeWidth={2.8} aria-hidden />
          <span>{t(read.due_at ? "add.read.notDate" : "add.read.keep")}</span>
        </button>
      </span>
    </div>
  );
}

/** Checklist steps for the new task: a line each, added and removed in place. */
function StepsEditor({ steps, onChange }: { steps: string[]; onChange: (steps: string[]) => void }) {
  const { t } = useI18n();
  const id = useId();
  const set = (index: number, text: string) => onChange(steps.map((step, at) => (at === index ? text : step)));
  return (
    <div className="field">
      <span className="field-label" id={`${id}-steps`}>{t("detail.checklist")}</span>
      <div className="plus-steps" role="group" aria-labelledby={`${id}-steps`}>
        {steps.map((step, index) => (
          <div key={index} className="plus-step">
            <input
              className="input"
              value={step}
              maxLength={200}
              aria-label={t("add.step", { n: index + 1 })}
              placeholder={t("add.stepPlaceholder")}
              autoFocus={index === steps.length - 1 && !step}
              onChange={(event) => set(index, event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && step.trim() && steps.length < STEPS_MAX) onChange([...steps, ""]);
              }}
            />
            <button
              type="button"
              className="btn btn-ghost btn-icon plus-step-remove"
              aria-label={t("add.stepRemove", { n: index + 1 })}
              onClick={() => onChange(steps.filter((_, at) => at !== index))}
            >
              <X size={18} strokeWidth={2.5} />
            </button>
          </div>
        ))}
        {steps.length < STEPS_MAX && (
          <button type="button" className="btn btn-secondary plus-step-add" onClick={() => onChange([...steps, ""])}>
            <Plus size={17} strokeWidth={2.6} aria-hidden />
            <span>{t("add.stepAdd")}</span>
          </button>
        )}
      </div>
    </div>
  );
}
