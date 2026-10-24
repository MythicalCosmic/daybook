import {
  Ban,
  CalendarClock,
  Clock3,
  Lock,
  Package,
  PenLine,
  Pencil,
  Sunrise,
  Trash2,
  UserX,
  Wrench,
  type LucideIcon,
} from "lucide-react";
import { useId, useState, type ReactNode } from "react";

import { useMembers, useTask, useTaskAction } from "../api/hooks";
import type { BlockerReason, SnoozePreset, Task } from "../api/types";
import type { Key } from "../i18n";
import { errorText } from "../lib/actions";
import { formatDue, type ViewContext } from "../lib/taskView";
import { addDays, clock, dayKey, zonedInstant } from "../lib/time";
import { useDraftGuard } from "../lib/useDraftGuard";
import { useViewContext } from "../lib/useNow";
import { useNavigation } from "../state/navigation";
import { useMember } from "../state/session";
import { useToast } from "../state/toast";
import { haptic, popup } from "../telegram";
import { Avatar } from "../ui";

/** The task (usually from the cache) for a sheet about it. */
function WithTask({ taskId, children }: { taskId: number; children: (task: Task) => ReactNode }) {
  const member = useMember();
  const task = useTask(member.companyId, taskId);
  return task.data ? <>{children(task.data)}</> : <div className="skeleton" style={{ height: 220 }} />;
}

function SheetHead({ kicker, title }: { kicker: string; title: string }) {
  return (
    <div className="ui-sheet-title">
      <div className="ui-kicker">{kicker}</div>
      <div className="heading title-sm">{title}</div>
    </div>
  );
}

// — snooze —

export function SnoozeSheet({ taskId }: { taskId: number }) {
  return <WithTask taskId={taskId}>{(task) => <SnoozeForm task={task} />}</WithTask>;
}

const SNOOZES: { preset: SnoozePreset; label: Key; icon: LucideIcon }[] = [
  { preset: "15m", label: "snooze.15m", icon: Clock3 },
  { preset: "1h", label: "snooze.1h", icon: Clock3 },
  { preset: "tomorrow_morning", label: "snooze.tomorrow", icon: Sunrise },
];

/**
 * Remind me later (R2 T15): 15 minutes or an hour pause the reminders and say the deadline didn't
 * move; my own task can also move to tomorrow morning.
 */
function SnoozeForm({ task }: { task: Task }) {
  const ctx = useViewContext();
  const { t } = ctx;
  const member = useMember();
  const navigation = useNavigation();
  const toast = useToast();
  const action = useTaskAction(member.companyId);
  const personal = task.kind === "personal";
  const left = task.reminder?.snoozes_left;
  const pick = (preset: SnoozePreset) => {
    haptic.select();
    action.mutate(
      { taskId: task.id, action: "snooze", preset },
      {
        onSuccess: (snoozed) => {
          navigation.closeSheet();
          toast(snoozedText(snoozed, preset, ctx), { tone: "success" });
        },
        onError: (error) => toast(errorText(error, t), { tone: "error" }),
      },
    );
  };
  return (
    <>
      <SheetHead kicker={t("snooze.title")} title={task.title} />
      <div className="card list-card sheet-options">
        {SNOOZES.filter((option) => personal || option.preset !== "tomorrow_morning").map(({ preset, label, icon: Icon }) => (
          <button key={preset} type="button" className="list-item sheet-option" disabled={action.isPending} onClick={() => pick(preset)}>
            <span className="sheet-option-main">
              <Icon size={20} strokeWidth={2.4} aria-hidden />
              <span className="sheet-option-text">
                <span>{t(label)}</span>
                {preset === "tomorrow_morning" && <span className="sheet-option-note">{t("snooze.tomorrowNote")}</span>}
              </span>
            </span>
          </button>
        ))}
      </div>
      {task.due_at && <p className="sheet-note num">{t("snooze.keepsDue", { due: formatDue(task.due_at, ctx, true) })}</p>}
      {left !== undefined && <p className="sheet-note sheet-note--muted num">{t("snooze.left", { left })}</p>}
    </>
  );
}

/** What the toast says after a snooze: until when, and that the deadline stayed (or moved). */
export function snoozedText(task: Task, preset: SnoozePreset, ctx: ViewContext): string {
  const { t } = ctx;
  if (preset === "tomorrow_morning" && task.due_at) return t("toast.movedTomorrow", { time: clock(task.due_at, ctx.timeZone, ctx.locale) });
  const until = task.snoozed_until ?? task.reminder?.snoozed_until ?? null;
  if (!until) return t("toast.snoozedPlain");
  const time = clock(until, ctx.timeZone, ctx.locale);
  return task.due_at ? t("toast.snoozedDue", { time, due: formatDue(task.due_at, ctx, true) }) : t("toast.snoozed", { time });
}

// — can't do it —

export function BlockerSheet({ taskId }: { taskId: number }) {
  return <WithTask taskId={taskId}>{(task) => <BlockerForm task={task} />}</WithTask>;
}

const REASONS: { code: BlockerReason; icon: LucideIcon }[] = [
  { code: "no_stock", icon: Package },
  { code: "no_access", icon: Lock },
  { code: "broken", icon: Wrench },
  { code: "not_mine", icon: UserX },
  { code: "other", icon: PenLine },
];

/** "Can't do it" (R2 T57): a reason in one tap, a note if needed; reminders pause, the giver hears. */
function BlockerForm({ task }: { task: Task }) {
  const { t } = useViewContext();
  const member = useMember();
  const navigation = useNavigation();
  const toast = useToast();
  const action = useTaskAction(member.companyId);
  const id = useId();
  const [code, setCode] = useState<BlockerReason | null>(null);
  const [note, setNote] = useState("");
  useDraftGuard(Boolean(code || note.trim()));
  const needsNote = code === "other";
  const ready = code !== null && (!needsNote || Boolean(note.trim()));
  const send = () => {
    if (!ready || action.isPending) return;
    action.mutate(
      { taskId: task.id, action: "blocker", reasonCode: code, note: note.trim() },
      {
        onSuccess: () => {
          haptic.notify("success");
          navigation.closeSheet();
          toast(t("toast.blocked"));
        },
        onError: (error) => toast(errorText(error, t), { tone: "error" }),
      },
    );
  };
  return (
    <>
      <SheetHead kicker={t("blocker.open")} title={t("blocker.title")} />
      <div className="ui-chips" role="radiogroup" aria-label={t("blocker.title")}>
        {REASONS.map(({ code: option, icon: Icon }) => (
          <button
            key={option}
            type="button"
            className="ui-chip"
            role="radio"
            aria-checked={code === option}
            aria-pressed={code === option}
            onClick={() => {
              haptic.select();
              setCode(option);
            }}
          >
            <Icon size={16} strokeWidth={2.5} aria-hidden />
            <span>{t(`blocker.reason.${option}`)}</span>
          </button>
        ))}
      </div>
      <div className="field">
        <label htmlFor={`${id}-note`}>{needsNote ? t("blocker.noteNeeded") : t("blocker.note")}</label>
        <textarea id={`${id}-note`} className="input" rows={3} maxLength={500} value={note} onChange={(event) => setNote(event.target.value)} />
      </div>
      <p className="sheet-note sheet-note--muted">{t("blocker.hint")}</p>
      <button type="button" className="btn btn-primary btn-lg btn-block" disabled={!ready || action.isPending} onClick={send}>
        {t("blocker.send")}
      </button>
    </>
  );
}

// — need more time —

export function ExtensionSheet({ taskId }: { taskId: number }) {
  return <WithTask taskId={taskId}>{(task) => <ExtensionForm task={task} />}</WithTask>;
}

type More = "30m" | "1h" | "tomorrow" | "pick";
const MORE_LABEL: Record<More, Key> = { "30m": "extension.30m", "1h": "extension.1h", tomorrow: "extension.tomorrow", pick: "extension.other" };

/** "Need more time" (R2 T17): a later deadline the giver approves in one tap. */
function ExtensionForm({ task }: { task: Task }) {
  const ctx = useViewContext();
  const { t } = ctx;
  const member = useMember();
  const navigation = useNavigation();
  const toast = useToast();
  const action = useTaskAction(member.companyId);
  const id = useId();
  const [now] = useState(() => new Date());
  const due = task.due_at ? new Date(task.due_at) : now;
  // More time counts from the deadline, or from now once it has passed.
  const base = due > now ? due : now;
  const today = dayKey(now, member.timeZone);
  const [choice, setChoice] = useState<More>("30m");
  const [day, setDay] = useState(dayKey(base, member.timeZone));
  const [time, setTime] = useState(clock(new Date(+base + 60 * 60_000), member.timeZone, "en-GB"));
  const [note, setNote] = useState("");
  useDraftGuard(Boolean(note.trim()));

  const until =
    choice === "30m"
      ? new Date(+base + 30 * 60_000)
      : choice === "1h"
        ? new Date(+base + 60 * 60_000)
        : choice === "tomorrow"
          ? zonedInstant(addDays(today, 1), "09:00", member.timeZone)
          : day && time
            ? zonedInstant(day, time, member.timeZone)
            : null;
  const valid = until !== null && until > due && until > now;
  const send = () => {
    if (!valid || action.isPending) return;
    action.mutate(
      { taskId: task.id, action: "extension", until: until.toISOString(), note: note.trim() },
      {
        onSuccess: () => {
          haptic.notify("success");
          navigation.closeSheet();
          toast(t("toast.extensionSent"));
        },
        onError: (error) => toast(errorText(error, t), { tone: "error" }),
      },
    );
  };
  return (
    <>
      <SheetHead kicker={t("extension.open")} title={t("extension.title")} />
      <div className="ui-chips" role="radiogroup" aria-label={t("extension.title")}>
        {(["30m", "1h", "tomorrow", "pick"] as const).map((option) => (
          <button
            key={option}
            type="button"
            className="ui-chip"
            role="radio"
            aria-checked={choice === option}
            aria-pressed={choice === option}
            onClick={() => {
              haptic.select();
              setChoice(option);
            }}
          >
            <span>{t(MORE_LABEL[option])}</span>
          </button>
        ))}
      </div>
      {choice === "pick" && (
        <div className="plus-when">
          <input className="input num" type="date" aria-label={t("extension.date")} min={today} value={day} onChange={(event) => setDay(event.target.value)} />
          <input className="input num" type="time" aria-label={t("extension.time")} value={time} onChange={(event) => setTime(event.target.value || time)} />
        </div>
      )}
      {until && (
        <div className={valid ? "banner" : "banner banner--accent"}>
          <span className="banner-icon">
            <CalendarClock size={17} strokeWidth={2.6} />
          </span>
          <span className="num" style={{ fontWeight: 700 }}>{t("detail.extension.until", { due: formatDue(until.toISOString(), ctx, true) })}</span>
        </div>
      )}
      <div className="field">
        <label htmlFor={`${id}-note`}>{t("extension.note")}</label>
        <textarea id={`${id}-note`} className="input" rows={2} maxLength={500} value={note} onChange={(event) => setNote(event.target.value)} />
      </div>
      <p className="sheet-note sheet-note--muted">{t("extension.hint")}</p>
      <button type="button" className="btn btn-primary btn-lg btn-block" disabled={!valid || action.isPending} onClick={send}>
        {t("extension.send")}
      </button>
    </>
  );
}

// — the giver: someone else, a new time —

export function ReassignSheet({ taskId }: { taskId: number }) {
  return <WithTask taskId={taskId}>{(task) => <ReassignForm task={task} />}</WithTask>;
}

/** Hand blocked work to someone else on the branch team. */
function ReassignForm({ task }: { task: Task }) {
  const { t } = useViewContext();
  const member = useMember();
  const navigation = useNavigation();
  const toast = useToast();
  const action = useTaskAction(member.companyId);
  const members = useMembers(member.companyId, true);
  const people = (members.data ?? []).filter((person) => person.id !== task.assignee.id);
  return (
    <>
      <SheetHead kicker={t("blocker.reassign")} title={task.title} />
      {members.isPending ? (
        <div className="skeleton" style={{ height: 160 }} />
      ) : people.length === 0 ? (
        <p className="sheet-note sheet-note--muted">{members.isError ? errorText(members.error, t) : t("pick.empty")}</p>
      ) : (
        <div className="card list-card sheet-options" role="list" aria-label={t("pick.title")}>
          {people.map((person) => (
            <button
              key={person.id}
              type="button"
              role="listitem"
              className="list-item sheet-option"
              disabled={action.isPending}
              onClick={() => {
                haptic.select();
                action.mutate(
                  { taskId: task.id, action: "resolveBlocker", resolution: "reassign", assigneeId: person.id },
                  {
                    onSuccess: () => {
                      haptic.notify("success");
                      navigation.closeSheet();
                      toast(t("toast.reassigned", { name: person.name }));
                    },
                    onError: (error) => toast(errorText(error, t), { tone: "error" }),
                  },
                );
              }}
            >
              <span className="sheet-option-main">
                <Avatar name={person.name} size="sm" />
                <span className="sheet-option-text">
                  <span>{person.name}</span>
                  {person.position && <span className="sheet-option-note">{person.position}</span>}
                </span>
              </span>
            </button>
          ))}
        </div>
      )}
    </>
  );
}

export function DueSheet({ taskId, resolve = false }: { taskId: number; resolve?: boolean }) {
  return <WithTask taskId={taskId}>{(task) => <DueForm task={task} resolve={resolve} />}</WithTask>;
}

/** A new deadline: my own change (PATCH), or the giver's answer to "can't do it". */
function DueForm({ task, resolve }: { task: Task; resolve: boolean }) {
  const ctx = useViewContext();
  const { t } = ctx;
  const member = useMember();
  const navigation = useNavigation();
  const toast = useToast();
  const action = useTaskAction(member.companyId);
  const [now] = useState(() => new Date());
  const today = dayKey(now, member.timeZone);
  const start = task.due_at && new Date(task.due_at) > now ? new Date(task.due_at) : zonedInstant(addDays(today, 1), "09:00", member.timeZone);
  const [day, setDay] = useState(dayKey(start, member.timeZone));
  const [time, setTime] = useState(clock(start, member.timeZone, "en-GB"));
  const [none, setNone] = useState(false);
  const canClear = !resolve && task.kind === "personal";
  const instant = day && time ? zonedInstant(day, time, member.timeZone) : null;
  const valid = (canClear && none) || (instant !== null && instant > now);
  const save = () => {
    if (!valid || action.isPending) return;
    const dueAt = canClear && none ? null : instant!.toISOString();
    const done = {
      onSuccess: () => {
        haptic.notify("success");
        navigation.closeSheet();
        toast(dueAt ? t("toast.newDue", { due: formatDue(dueAt, ctx, true) }) : t("toast.noDeadline"));
      },
      onError: (error: unknown) => toast(errorText(error, t), { tone: "error" }),
    };
    if (resolve && dueAt) action.mutate({ taskId: task.id, action: "resolveBlocker", resolution: "new_due", dueAt }, done);
    else action.mutate({ taskId: task.id, action: "edit", changes: { due_at: dueAt } }, done);
  };
  return (
    <>
      <SheetHead kicker={t(resolve ? "blocker.newDue" : "menu.due")} title={task.title} />
      {canClear && (
        <div className="ui-chips">
          <button type="button" className="ui-chip" aria-pressed={!none} onClick={() => setNone(false)}>
            <span>{t("due.title")}</span>
          </button>
          <button type="button" className="ui-chip" aria-pressed={none} onClick={() => setNone(true)}>
            <span>{t("add.noDeadline")}</span>
          </button>
        </div>
      )}
      {!(canClear && none) && (
        <div className="plus-when">
          <input className="input num" type="date" aria-label={t("extension.date")} min={today} value={day} onChange={(event) => setDay(event.target.value)} />
          <input className="input num" type="time" aria-label={t("extension.time")} value={time} onChange={(event) => setTime(event.target.value || time)} />
        </div>
      )}
      <button type="button" className="btn btn-primary btn-lg btn-block" disabled={!valid || action.isPending} onClick={save}>
        {t("due.save")}
      </button>
    </>
  );
}

// — edit and the task menu —

export function EditSheet({ taskId }: { taskId: number }) {
  return <WithTask taskId={taskId}>{(task) => <EditForm task={task} />}</WithTask>;
}

function EditForm({ task }: { task: Task }) {
  const { t } = useViewContext();
  const member = useMember();
  const navigation = useNavigation();
  const toast = useToast();
  const action = useTaskAction(member.companyId);
  const id = useId();
  const [title, setTitle] = useState(task.title);
  const [description, setDescription] = useState(task.description);
  const changed = title.trim() !== task.title || description.trim() !== task.description.trim();
  useDraftGuard(changed);
  const save = () => {
    if (!title.trim() || !changed || action.isPending) return;
    action.mutate(
      { taskId: task.id, action: "edit", changes: { title: title.trim(), description: description.trim() } },
      {
        onSuccess: () => {
          haptic.notify("success");
          navigation.closeSheet();
          toast(t("toast.saved"));
        },
        onError: (error) => toast(errorText(error, t), { tone: "error" }),
      },
    );
  };
  return (
    <>
      <div className="heading title-sm">{t("edit.title")}</div>
      <div className="field">
        <label htmlFor={`${id}-title`}>{t("edit.name")}</label>
        <input id={`${id}-title`} className="input" value={title} maxLength={200} onChange={(event) => setTitle(event.target.value)} />
      </div>
      <div className="field">
        <label htmlFor={`${id}-description`}>{t("add.description")}</label>
        <textarea id={`${id}-description`} className="input" rows={4} maxLength={2000} value={description} onChange={(event) => setDescription(event.target.value)} />
      </div>
      <button type="button" className="btn btn-primary btn-lg btn-block" disabled={!title.trim() || !changed || action.isPending} onClick={save}>
        {t("due.save")}
      </button>
    </>
  );
}

export function TaskMenuSheet({ taskId }: { taskId: number }) {
  return <WithTask taskId={taskId}>{(task) => <TaskMenu task={task} />}</WithTask>;
}

/**
 * What I may do with the task besides working on it (audit M-3): edit it, move its deadline, and
 * delete my own task (cancel someone's work), as `task.actions` allows.
 */
function TaskMenu({ task }: { task: Task }) {
  const { t } = useViewContext();
  const member = useMember();
  const navigation = useNavigation();
  const toast = useToast();
  const action = useTaskAction(member.companyId);
  const personal = task.kind === "personal";
  const canEdit = task.actions.includes("edit");
  const canCancel = task.actions.includes("cancel");

  const remove = async () => {
    const repeating = personal && Boolean(task.repeat_weekdays?.length);
    const choice = await popup(
      personal ? t("menu.deleteConfirm", { title: task.title }) : t("blocker.cancelConfirm", { title: task.title }),
      repeating
        ? [
            { id: "once", type: "default", text: t("menu.onlyThis") },
            { id: "stop", type: "destructive", text: t("menu.stopRepeating") },
            { id: "back", type: "cancel" },
          ]
        : [
            { id: "yes", type: "destructive", text: personal ? t("menu.delete") : t("blocker.cancel") },
            { id: "back", type: "cancel" },
          ],
    );
    if (!choice || choice === "back") return;
    action.mutate(
      { taskId: task.id, action: "cancel", stopRepeating: choice === "stop" },
      {
        onSuccess: () => {
          haptic.notify("success");
          navigation.closeSheet();
          navigation.closeTask();
          toast(personal ? t("toast.deleted") : t("toast.cancelled"));
        },
        onError: (error) => toast(errorText(error, t), { tone: "error" }),
      },
    );
  };

  const rows: { key: string; label: string; icon: LucideIcon; danger?: boolean; onClick: () => void }[] = [];
  if (canEdit) {
    rows.push({ key: "edit", label: t("menu.edit"), icon: Pencil, onClick: () => navigation.openSheet({ kind: "edit", taskId: task.id }) });
    rows.push({ key: "due", label: t("menu.due"), icon: CalendarClock, onClick: () => navigation.openSheet({ kind: "due", taskId: task.id }) });
  }
  if (canCancel) {
    rows.push({ key: "cancel", label: personal ? t("menu.delete") : t("blocker.cancel"), icon: personal ? Trash2 : Ban, danger: true, onClick: () => void remove() });
  }
  return (
    <>
      <div className="heading title-sm">{task.title}</div>
      <div className="card list-card sheet-options">
        {rows.map(({ key, label, icon: Icon, danger, onClick }) => (
          <button
            key={key}
            type="button"
            className={danger ? "list-item sheet-option sheet-option--danger" : "list-item sheet-option"}
            disabled={action.isPending}
            onClick={() => {
              haptic.select();
              onClick();
            }}
          >
            <span className="sheet-option-main">
              <Icon size={20} strokeWidth={2.4} aria-hidden />
              <span>{label}</span>
            </span>
          </button>
        ))}
      </div>
    </>
  );
}
