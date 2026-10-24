import {
  AtSign,
  CalendarClock,
  Check,
  Ellipsis,
  Flag,
  Gift,
  Hourglass,
  OctagonAlert,
  Play,
  SendHorizontal,
  Timer,
  Undo2,
  X,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { api, ApiError } from "../api/client";
import {
  useActivity,
  useAddComment,
  useComments,
  useMembers,
  useReviewQueue,
  useSummary,
  useTask,
  useTaskAction,
  useToggleChecklist,
} from "../api/hooks";
import type { Activity, Comment, MemberBrief, Task } from "../api/types";
import { LateCard, ReminderNote } from "../components/Reminders";
import { FeatureSlot } from "../features/FeatureSlot";
import { useI18n } from "../i18n";
import { errorText, useCompleteTask, useConfirmTasks } from "../lib/actions";
import { formatMoney } from "../lib/money";
import {
  duration,
  formatDue,
  isLate,
  isOpen,
  priorityLevel,
  repeatLabel,
  seenLabel,
  shortMoment,
  type ViewContext,
} from "../lib/taskView";
import { clock } from "../lib/time";
import { useDraftGuard } from "../lib/useDraftGuard";
import { useViewContext } from "../lib/useNow";
import { useNavigation } from "../state/navigation";
import { initials, useMember, useSession } from "../state/session";
import { useToast } from "../state/toast";
import { haptic } from "../telegram";
import { BottomBar, LoadError, ScreenSkeleton, type BottomAction } from "../ui";

export function TaskDetail({ taskId }: { taskId: number }) {
  const ctx = useViewContext();
  const member = useMember();
  const task = useTask(member.companyId, taskId);
  const comments = useComments(member.companyId, taskId);
  const navigation = useNavigation();
  const searching = useTaskInOtherCompany(taskId, task.error);

  return (
    <div className="detail-layer">
      {task.data ? (
        <Detail task={task.data} comments={comments.data ?? []} ctx={ctx} />
      ) : task.isError && !searching ? (
        // A task that's gone (or isn't mine to see) says so, instead of a skeleton that never ends.
        <div className="screen screen--detail">
          <LoadError error={task.error} onRetry={() => void task.refetch()} onBack={navigation.pop} />
        </div>
      ) : (
        <div className="screen screen--detail">
          <ScreenSkeleton variant="detail" delay={150} />
        </div>
      )}
    </div>
  );
}

/**
 * A bot link to a task in my other company (an owner of a pharmacy and its distributor): when the
 * task isn't in the company on screen, look in the others and switch to the one that has it, so
 * the link opens the task rather than "This page isn't here". True while looking.
 */
function useTaskInOtherCompany(taskId: number, error: unknown): boolean {
  const session = useSession();
  const member = useMember();
  const [searching, setSearching] = useState(false);
  const searched = useRef<number | null>(null);
  const latest = useRef({ session, companyId: member.companyId });
  latest.current = { session, companyId: member.companyId };
  const missing = error instanceof ApiError && (error.status === 404 || error.status === 403);
  useEffect(() => {
    const { session: now, companyId } = latest.current;
    const others = now.companies.filter((company) => company.company.id !== companyId);
    if (!missing || searched.current === taskId || others.length === 0) return;
    searched.current = taskId;
    setSearching(true);
    let live = true;
    void (async () => {
      for (const other of others) {
        try {
          await api<Task>(`/companies/${other.company.id}/tasks/${taskId}/`);
          if (live) latest.current.session.switchCompany(other.company.id);
          break;
        } catch {
          // Not in this one either.
        }
      }
      if (live) setSearching(false);
    })();
    return () => {
      live = false;
    };
  }, [missing, taskId]);
  return searching;
}

function Detail({ task, comments, ctx }: { task: Task; comments: Comment[]; ctx: ViewContext }) {
  const { t } = ctx;
  const { lang } = useI18n();
  const member = useMember();
  const navigation = useNavigation();
  const late = isLate(task, ctx.now);
  const isMine = task.assignee.id === member.id;
  const gaveIt = task.created_by?.id === member.id && !isMine;
  const repeat = repeatLabel(task.repeat_weekdays, ctx);
  const toggle = useToggleChecklist(member.companyId);
  const action = useTaskAction(member.companyId);
  const summary = useSummary(member.companyId);
  const activity = useActivity(member.companyId);
  const toast = useToast();
  const [draftSeed, setDraftSeed] = useState<{ text: string; mention?: MemberBrief } | null>(null);
  const quiet = summary.data?.quiet_from && summary.data.quiet_until ? summary.data : null;
  const prio = priorityLevel(task);
  const people = taskPeople(task, comments, member.id);
  const canManage = task.actions.includes("edit") || task.actions.includes("cancel");

  // Snooze choices where the backend has them (it then sends `snoozed_until`); the policy's one
  // length otherwise.
  const snooze = () => {
    haptic();
    if (task.snoozed_until !== undefined) {
      navigation.openSheet({ kind: "snooze", taskId: task.id });
      return;
    }
    action.mutate(
      { taskId: task.id, action: "snooze" },
      {
        onSuccess: (snoozed) =>
          toast(
            snoozed.reminder?.snoozed_until
              ? t("toast.snoozed", { time: clock(snoozed.reminder.snoozed_until, ctx.timeZone, ctx.locale) })
              : t("toast.snoozedPlain"),
          ),
        onError: (error) => toast(errorText(error, t), { tone: "error" }),
      },
    );
  };
  // Mention whoever hears about it being late (when they're someone on the task), else the giver:
  // the comment then reaches them in the bot.
  const askForHelp = () => {
    const name = task.reminder?.escalate_to ?? task.created_by?.name ?? "";
    const mention = people.find((person) => person.name === name) ?? (task.created_by && task.created_by.id !== member.id ? task.created_by : undefined);
    const label = (mention?.name ?? name).split(" ")[0];
    setDraftSeed({ text: label ? `@${label} ` : "", mention });
  };

  const status = late
    ? { label: t("status.late"), tone: "accent" }
    : task.status === "done" && task.confirmed_by
      ? { label: t("status.checked"), tone: "sage" }
      : {
          label: t(`status.${task.status}`),
          tone: { todo: "neutral", in_progress: "sage", review: "neutral", returned: "accent", done: "sage", cancelled: "neutral" }[task.status],
        };

  const kicker =
    task.kind === "daily"
      ? repeat && task.due_at
        ? t("detail.kicker.daily", { repeat, time: clock(task.due_at, ctx.timeZone, ctx.locale) })
        : t("detail.kicker.dailyPlain")
      : task.kind === "assigned" && task.created_by
        ? gaveIt
          ? t("detail.kicker.byYou", { name: task.assignee.name })
          : t("detail.kicker.from", { name: task.created_by.name })
        : repeat
          ? t("detail.kicker.ownRepeat", { repeat })
          : t("detail.kicker.own");

  const details: [string, ReactNode][] = [
    [t("detail.due"), dueLine(task, ctx)],
    [t("detail.repeats"), repeat ?? t("detail.no")],
    [t("detail.proof"), t(`proof.${task.proof}`)],
    [t("detail.check"), checker(task, member.id, t)],
  ];
  if (task.reward) details.push([t("detail.reward"), formatMoney(task.reward, "UZS", lang, { sign: "always" })]);
  if (!isMine) {
    const seen = seenLabel(task, ctx);
    details.push([
      t("detail.for"),
      seen ? (
        <span className="detail-value-stack">
          <span>{task.assignee.name}</span>
          <span className={task.seen_at ? "detail-seen" : "detail-seen detail-seen--not"}>{seen}</span>
        </span>
      ) : (
        task.assignee.name
      ),
    ]);
  }

  const checklistDone = task.checklist.filter((item) => item.is_done).length;
  const canTick = isMine && task.actions.includes("complete");
  const tick = (itemId: number, done: boolean, text: string) => {
    haptic.select();
    toggle.mutate(
      { taskId: task.id, itemId, done },
      {
        onSuccess: () => {
          // A tick is easy to slip on: say what was ticked, and offer to take it back.
          if (!done) return;
          toast(t("toast.stepDone", { step: text }), {
            action: { label: t("ui.toast.undo"), onPress: () => toggle.mutate({ taskId: task.id, itemId, done: false }) },
          });
        },
        onError: (error) => toast(errorText(error, t), { tone: "error" }),
      },
    );
  };

  // Ask for more time or say it can't be done: assigned and routine work, open, where the backend
  // knows these requests (it then sends `blocker` / `extension`, null when there's none).
  const canAskTime = isMine && isOpen(task) && task.kind !== "personal" && task.due_at !== null && task.extension === null && !task.blocker;
  const canBlock = isMine && isOpen(task) && task.kind !== "personal" && task.blocker === null;

  return (
    <>
      <div className="screen screen--detail">
        <div style={{ display: "flex", flexDirection: "column", gap: 10, padding: "0 4px" }}>
          <div className="detail-tags">
            <span className={`tag tag-${status.tone}`} style={{ fontSize: 13, padding: "4px 11px" }}>{status.label}</span>
            {prio && (
              <span className={prio === "urgent" ? "tag tag-urgent" : "tag tag-neutral"} style={{ fontSize: 13, padding: "4px 11px" }}>
                <Flag size={13} strokeWidth={2.8} aria-hidden />
                {t(`priority.${prio}`)}
              </span>
            )}
            {/* The proof it needs, while it's still to do: once sent, the proof is there. */}
            {task.proof !== "none" && isOpen(task) && (
              <span className="tag tag-neutral" style={{ fontSize: 13, padding: "4px 11px" }}>{t(`proof.tag.${task.proof}`)}</span>
            )}
            {task.reward && (
              <span className="tag tag-sage" style={{ fontSize: 13, padding: "4px 11px" }}>
                <Gift size={13} strokeWidth={2.6} aria-hidden />
                {formatMoney(task.reward, "UZS", lang, { sign: "always" })}
              </span>
            )}
            {canManage && (
              <button type="button" className="btn btn-ghost btn-icon detail-more" aria-label={t("menu.more")} onClick={() => navigation.openSheet({ kind: "taskMenu", taskId: task.id })}>
                <Ellipsis size={22} strokeWidth={2.5} />
              </button>
            )}
          </div>
          <h1 className="heading title-md" style={{ lineHeight: 1.1, textWrap: "pretty" }}>{task.title}</h1>
          <div className="num" style={{ fontSize: 15, color: "color-mix(in srgb, var(--color-text) 64%, transparent)" }}>{kicker}</div>
        </div>

        <StatusBanner task={task} comments={comments} activity={activity.data} ctx={ctx} />
        <RequestBanners task={task} isMine={isMine} ctx={ctx} />

        {late && task.due_at && !task.blocker && (
          <LateCard task={task} reminder={task.reminder} ctx={ctx} onSnooze={snooze} snoozing={action.isPending} onAskHelp={askForHelp} />
        )}
        {!late && task.reminder && task.due_at && isMine && !task.blocker && <ReminderNote task={task} reminder={task.reminder} ctx={ctx} />}
        {late && quiet && !task.blocker && (
          <div className="muted num" style={{ fontSize: 13.5, padding: "0 4px", marginTop: -6 }}>
            {t("detail.quiet", { from: quiet.quiet_from!.slice(0, 5), until: quiet.quiet_until!.slice(0, 5) })}
          </div>
        )}

        {task.description && (
          <div className="card" style={{ gap: 6 }}>
            <div className="card-title">{t("detail.whatToDo")}</div>
            <p style={{ margin: 0, fontSize: 16, lineHeight: 1.55, textWrap: "pretty", whiteSpace: "pre-wrap" }}>{task.description}</p>
          </div>
        )}

        {task.checklist.length > 0 && (
          <div className="card" style={{ padding: 8, gap: 0 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "10px 12px 6px" }}>
              <span className="card-title">{t("detail.checklist")}</span>
              <span className="tag tag-sage" style={{ fontSize: 13, padding: "3px 10px" }}>
                {t("detail.checklistCount", { done: checklistDone, total: task.checklist.length })}
              </span>
            </div>
            {task.checklist.map((item) =>
              canTick ? (
                <button key={item.id} role="checkbox" aria-checked={item.is_done} onClick={() => tick(item.id, !item.is_done, item.text)} className="check-item">
                  <span className={item.is_done ? "check-box check-box--done" : "check-box"}>{item.is_done && <Check size={16} strokeWidth={3} />}</span>
                  <span style={item.is_done ? { color: "color-mix(in srgb, var(--color-text) 58%, transparent)" } : undefined}>{item.text}</span>
                </button>
              ) : (
                // Whoever can't tick reads the steps: no box that looks tappable (audit M-15).
                <div key={item.id} role="checkbox" aria-checked={item.is_done} aria-disabled className="check-item check-item--read">
                  <span className={item.is_done ? "check-mark check-mark--done" : "check-mark"} aria-hidden>
                    {item.is_done && <Check size={14} strokeWidth={3} />}
                  </span>
                  <span>{item.text}</span>
                </div>
              ),
            )}
          </div>
        )}

        {/* Feature blocks for this task: "How to do this" (knowledge), the project timer. */}
        <FeatureSlot name="task.actions" task={task} />

        {task.proof_text && (
          <div className="card" style={{ gap: 6 }}>
            <div className="card-title">{t("detail.report")}</div>
            <p style={{ margin: 0, fontSize: 16, lineHeight: 1.55, whiteSpace: "pre-wrap" }}>{task.proof_text}</p>
          </div>
        )}
        {task.proof_photo && (
          <img src={task.proof_photo} alt="" style={{ width: "100%", borderRadius: "var(--radius-lg)", objectFit: "cover", maxHeight: 320 }} />
        )}

        <div className="card" style={{ padding: "6px 20px", gap: 0 }}>
          {details.map(([key, value]) => (
            <div key={key} className="detail-line">
              <span className="muted">{key}</span>
              <span style={{ textAlign: "right", fontWeight: 600 }} className="num">{value}</span>
            </div>
          ))}
        </div>

        {(canAskTime || canBlock) && (
          <div className="detail-problem">
            <span className="detail-problem-title">{t("detail.problem")}</span>
            <div className="detail-problem-actions">
              {canAskTime && (
                <button type="button" className="btn btn-secondary" onClick={() => navigation.openSheet({ kind: "extension", taskId: task.id })}>
                  <Timer size={17} strokeWidth={2.6} aria-hidden />
                  <span>{t("extension.open")}</span>
                </button>
              )}
              {canBlock && (
                <button type="button" className="btn btn-secondary" onClick={() => navigation.openSheet({ kind: "blocker", taskId: task.id })}>
                  <OctagonAlert size={17} strokeWidth={2.6} aria-hidden />
                  <span>{t("blocker.open")}</span>
                </button>
              )}
            </div>
          </div>
        )}

        <Comments task={task} comments={comments} people={people} ctx={ctx} seed={draftSeed} />
      </div>
      <ActionBar task={task} isMine={isMine} />
    </>
  );
}

/** The deadline as a value, with how long is left when it's today ("Bugun, 18:00 · 2 soat qoldi"). */
function dueLine(task: Task, ctx: ViewContext): string {
  if (!task.due_at) return ctx.t("detail.noDue");
  const label = formatDue(task.due_at, ctx);
  const left = Math.floor((+new Date(task.due_at) - +ctx.now) / 60_000);
  return isOpen(task) && left > 0 && left < 12 * 60 ? `${label} · ${ctx.t("due.left", { duration: duration(left, ctx.t) })}` : label;
}

/**
 * Who sent it back and why: the return itself (the feed's "sent back" entry carries the reason),
 * never simply the latest comment, which may be the worker's own reply (audit M-1). Without the
 * entry (the reviewer's own view), the latest comment by someone other than the worker.
 */
export function returnInfo(task: Task, comments: Comment[], activity: Activity[] | undefined): { name: string; reason: string | null } {
  const entry = activity?.find((item) => item.kind === "returned" && item.task.id === task.id);
  if (entry) return { name: entry.actor?.name ?? task.created_by?.name ?? "", reason: entry.text || null };
  const byReviewer = [...comments].reverse().find((comment) => comment.author && comment.author.id !== task.assignee.id);
  return { name: byReviewer?.author?.name ?? task.created_by?.name ?? "", reason: byReviewer?.text ?? null };
}

function StatusBanner({ task, comments, activity, ctx }: { task: Task; comments: Comment[]; activity: Activity[] | undefined; ctx: ViewContext }) {
  const { t } = ctx;
  const at = (moment: string | null) => (moment ? clock(moment, ctx.timeZone, ctx.locale) : "—");
  let banner: { tone: string; icon: ReactNode; title: string; note?: string } | null = null;
  if (task.status === "review") {
    // Whoever checks it hears who finished it and what to do; whoever did it, that it's on its way.
    banner = task.actions.includes("confirm")
      ? { tone: "", icon: <Hourglass size={17} strokeWidth={2.6} />, title: t("detail.banner.reviewBy", { name: task.assignee.name, time: at(task.completed_at) }), note: t(task.proof === "none" ? "detail.banner.reviewByNoteBare" : "detail.banner.reviewByNote") }
      : { tone: "", icon: <Hourglass size={17} strokeWidth={2.6} />, title: t("detail.banner.review", { time: at(task.completed_at) }), note: t("detail.banner.reviewNote") };
  } else if (task.status === "returned") {
    const { name, reason } = returnInfo(task, comments, activity);
    banner = {
      tone: "accent",
      icon: <Undo2 size={17} strokeWidth={2.6} />,
      title: t("detail.banner.returned", { name: name || "—" }),
      note: reason ? t("routines.quoted", { text: reason }) : undefined,
    };
  } else if (task.status === "done") {
    banner = {
      tone: "sage",
      icon: <Check size={17} strokeWidth={3} />,
      title: task.confirmed_by
        ? t("detail.banner.checked", { name: task.confirmed_by.name, time: at(task.confirmed_at) })
        : t("detail.banner.done", { time: at(task.completed_at) }),
    };
  } else if (task.status === "cancelled") {
    banner = { tone: "", icon: <X size={17} strokeWidth={2.6} />, title: t("detail.banner.cancelled") };
  }
  if (!banner) return null;
  return (
    <div className={banner.tone ? `banner banner--${banner.tone}` : "banner"} style={{ alignItems: banner.note ? "flex-start" : "center" }}>
      <span className="banner-icon">{banner.icon}</span>
      <span style={{ display: "flex", flexDirection: "column", gap: 2 }}>
        <span className="num" style={{ fontSize: 15, fontWeight: 700 }}>{banner.title}</span>
        {banner.note && <span style={{ fontSize: 15, lineHeight: 1.45 }}>{banner.note}</span>}
      </span>
    </div>
  );
}

/**
 * "Can't do it" and "Need more time", as each side reads them: the worker sees what they asked
 * and that it's waiting; the giver sees the request with what they can do about it.
 */
function RequestBanners({ task, isMine, ctx }: { task: Task; isMine: boolean; ctx: ViewContext }) {
  const { t } = ctx;
  const member = useMember();
  const navigation = useNavigation();
  const toast = useToast();
  const action = useTaskAction(member.companyId);
  const canDecide = !isMine && (task.actions.includes("edit") || task.actions.includes("cancel"));
  const cancel = () =>
    action.mutate(
      { taskId: task.id, action: "resolveBlocker", resolution: "cancel" },
      {
        onSuccess: () => {
          haptic.notify("success");
          toast(t("toast.cancelled"));
        },
        onError: (error) => toast(errorText(error, t), { tone: "error" }),
      },
    );
  const decide = (approve: boolean) =>
    action.mutate(
      { taskId: task.id, action: "decideExtension", approve, until: task.extension?.until },
      {
        onSuccess: (decided) => {
          haptic.notify("success");
          toast(approve && decided.due_at ? t("toast.extensionApproved", { due: formatDue(decided.due_at, ctx, true) }) : t("toast.extensionDeclined"));
        },
        onError: (error) => toast(errorText(error, t), { tone: "error" }),
      },
    );

  return (
    <>
      {task.blocker && (
        <div className="banner banner--accent request-banner" role="status">
          <span className="banner-icon">
            <OctagonAlert size={17} strokeWidth={2.6} />
          </span>
          <span className="request-banner-main">
            <span className="request-banner-title">
              {isMine
                ? t("detail.blocked.mine", { reason: t(`blocker.reason.${task.blocker.reason_code}`).toLocaleLowerCase() })
                : t("detail.blocked.giver", { name: task.assignee.name, reason: t(`blocker.reason.${task.blocker.reason_code}`).toLocaleLowerCase() })}
            </span>
            {task.blocker.note && <span className="request-banner-note">{t("routines.quoted", { text: task.blocker.note })}</span>}
            <span className="request-banner-meta num">{isMine ? t("detail.blocked.mineNote") : shortMoment(task.blocker.at, ctx)}</span>
            {canDecide && (
              <span className="request-banner-actions">
                <button type="button" className="btn btn-secondary" disabled={action.isPending} onClick={() => navigation.openSheet({ kind: "reassign", taskId: task.id })}>
                  {t("blocker.reassign")}
                </button>
                <button type="button" className="btn btn-secondary" disabled={action.isPending} onClick={() => navigation.openSheet({ kind: "due", taskId: task.id, resolve: true })}>
                  {t("blocker.newDue")}
                </button>
                <button type="button" className="btn btn-ghost request-banner-danger" disabled={action.isPending} onClick={cancel}>
                  {t("blocker.cancel")}
                </button>
              </span>
            )}
          </span>
        </div>
      )}
      {task.extension && (
        <div className="banner request-banner" role="status">
          <span className="banner-icon" style={{ color: "var(--color-accent-700)" }}>
            <CalendarClock size={17} strokeWidth={2.6} />
          </span>
          <span className="request-banner-main">
            <span className="request-banner-title num">
              {isMine
                ? t("detail.extension.mine", { due: formatDue(task.extension.until, ctx, true) })
                : t("detail.extension.giver", { name: task.assignee.name })}
            </span>
            {!isMine && <span className="request-banner-note num">{t("detail.extension.until", { due: formatDue(task.extension.until, ctx, true) })}</span>}
            {task.extension.note && <span className="request-banner-note">{t("routines.quoted", { text: task.extension.note })}</span>}
            {isMine && <span className="request-banner-meta">{t("detail.extension.mineNote")}</span>}
            {canDecide && (
              <span className="request-banner-actions">
                <button type="button" className="btn btn-primary" disabled={action.isPending} onClick={() => decide(true)}>
                  <Check size={17} strokeWidth={2.8} aria-hidden />
                  <span>{t("extension.approve")}</span>
                </button>
                <button type="button" className="btn btn-secondary" disabled={action.isPending} onClick={() => decide(false)}>
                  {t("extension.decline")}
                </button>
              </span>
            )}
          </span>
        </div>
      )}
    </>
  );
}

/**
 * The people on the task, for @: the assignee, whoever gave it, whoever checked it, and anyone
 * who commented. Never me.
 */
type Person = MemberBrief & { role?: "assignee" | "giver" | "checker" };

export function taskPeople(task: Task, comments: Comment[], me: number): Person[] {
  const seen = new Map<number, Person>();
  const add = (person: MemberBrief | null | undefined, role?: "assignee" | "giver" | "checker") => {
    if (!person || person.id === me || seen.has(person.id)) return;
    seen.set(person.id, { ...person, role });
  };
  add(task.assignee, "assignee");
  add(task.created_by, "giver");
  add(task.confirmed_by, "checker");
  for (const comment of comments) add(comment.author);
  return [...seen.values()];
}

const ROLE_LABEL = { assignee: "detail.role.assignee", giver: "detail.role.giver", checker: "detail.role.checker" } as const;

/** The name an @ inserts: the first name, as people say it. */
const handle = (person: MemberBrief) => person.name.split(" ")[0] || person.name;

/** The "@que" being typed right before the caret, if any. */
function mentionQuery(text: string, caret: number): { start: number; query: string } | null {
  const match = /(^|\s)@([\p{L}\p{N}_]*)$/u.exec(text.slice(0, caret));
  return match ? { start: caret - match[2].length - 1, query: match[2] } : null;
}

const fold = (text: string) => text.toLocaleLowerCase().normalize("NFKD").replace(/[̀-ͯ]/g, "").replace(/[‘’ʻʼ'`]/g, "");

function Comments({ task, comments, people, ctx, seed }: {
  task: Task;
  comments: Comment[];
  people: Person[];
  ctx: ViewContext;
  seed: { text: string; mention?: MemberBrief } | null;
}) {
  const { t } = ctx;
  const member = useMember();
  const add = useAddComment(member.companyId, task.id);
  const toast = useToast();
  // Managers can mention anyone on their team; everyone else, the people on the task.
  const canSeeTeam = member.permissions.includes("tasks.assign") || member.permissions.includes("members.view");
  const team = useMembers(member.companyId, canSeeTeam);
  const draftKey = `daybook.comment.${member.companyId}.${task.id}`;
  const [draft, setDraft] = useState(() => readDraft(draftKey));
  const [mentioned, setMentioned] = useState<Map<number, string>>(() => new Map());
  const [query, setQuery] = useState<{ start: number; query: string } | null>(null);
  const [active, setActive] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  useDraftGuard(Boolean(draft.trim()));

  useEffect(() => saveDraft(draftKey, draft), [draftKey, draft]);
  useEffect(() => {
    if (!seed) return;
    setDraft(seed.text);
    if (seed.mention) setMentioned((map) => new Map(map).set(seed.mention!.id, handle(seed.mention!)));
    input.current?.focus();
    input.current?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [seed]);

  const candidates = useMemo(() => {
    const extra = (team.data ?? []).filter((person) => person.id !== member.id && !people.some((known) => known.id === person.id));
    const all: Person[] = [...people, ...extra];
    if (!query) return all;
    const q = fold(query.query);
    return all.filter((person) => person.name.split(/\s+/).some((part) => fold(part).startsWith(q)));
  }, [people, team.data, member.id, query]);

  const listOpen = query !== null;
  const names = [...mentioned.entries()].filter(([, name]) => draft.includes(`@${name}`));

  const pick = (person: MemberBrief) => {
    if (!query) return;
    const name = handle(person);
    const next = `${draft.slice(0, query.start)}@${name} ${draft.slice(query.start + 1 + query.query.length)}`;
    haptic.select();
    setDraft(next);
    setMentioned((map) => new Map(map).set(person.id, name));
    setQuery(null);
    requestAnimationFrame(() => {
      const caret = query.start + name.length + 2;
      input.current?.focus();
      input.current?.setSelectionRange(caret, caret);
    });
  };

  const onType = (text: string, caret: number) => {
    setDraft(text);
    setQuery(mentionQuery(text, caret));
    setActive(0);
  };

  const send = () => {
    const text = draft.trim();
    if (!text || add.isPending) return;
    const mentions = names.map(([id]) => id);
    add.mutate(
      { text, mentions },
      {
        onSuccess: () => {
          haptic();
          setDraft("");
          setMentioned(new Map());
          setQuery(null);
        },
        onError: (error) => toast(errorText(error, t), { tone: "error" }),
      },
    );
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12, paddingTop: "var(--space-2)" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "0 4px" }}>
        <span style={{ fontSize: 17, fontWeight: 700 }}>{t("detail.comments")}</span>
        <span className="tag tag-neutral tag-small">{comments.length}</span>
      </div>
      {comments.map((comment) => {
        const name = comment.author?.name ?? t("activity.someone");
        const [first = "", last = ""] = name.split(" ");
        return (
          <div key={comment.id} style={{ display: "flex", gap: 10, alignItems: "flex-end" }}>
            <div className="avatar" style={{ width: 34, height: 34, fontSize: 13 }}>{initials(first, last)}</div>
            <div style={{ flex: 1, minWidth: 0, padding: "10px 14px", borderRadius: "var(--radius-md) var(--radius-md) var(--radius-md) var(--radius-sm)", background: "var(--color-surface)" }}>
              <div style={{ display: "flex", alignItems: "baseline", gap: 6, fontSize: 13 }}>
                <span style={{ fontWeight: 700 }}>{name}</span>
                {comment.author?.position && <span className="muted">{comment.author.position}</span>}
                <span className="muted num" style={{ marginLeft: "auto" }}>{shortMoment(comment.created_at, ctx)}</span>
              </div>
              <div style={{ fontSize: 15, lineHeight: 1.45, marginTop: 2, textWrap: "pretty", whiteSpace: "pre-wrap" }}>
                <Mentions text={comment.text} />
              </div>
            </div>
          </div>
        );
      })}
      {comments.length === 0 && <div className="muted" style={{ padding: "0 4px", fontSize: 15 }}>{t("detail.noComments")}</div>}
      <div className="comment-box">
        {listOpen && (
          <div className="mention-list" role="listbox" aria-label={t("detail.mention")}>
            {candidates.length === 0 ? (
              <div className="mention-empty">{t("detail.mentionNone")}</div>
            ) : (
              candidates.slice(0, 6).map((person, index) => (
                <button
                  key={person.id}
                  type="button"
                  role="option"
                  aria-selected={index === active}
                  className="mention-option"
                  // Keep the field focused (and the keyboard up) while picking.
                  onMouseDown={(event) => event.preventDefault()}
                  onClick={() => pick(person)}
                >
                  <span className="avatar" style={{ width: 30, height: 30, fontSize: 12 }}>{nameInitials(person.name)}</span>
                  <span className="mention-option-text">
                    <span className="mention-option-name">{person.name}</span>
                    <span className="mention-option-role">{person.role ? t(ROLE_LABEL[person.role]) : person.position ?? ""}</span>
                  </span>
                </button>
              ))
            )}
          </div>
        )}
        <div style={{ display: "flex", gap: "var(--space-2)", alignItems: "center" }}>
          <button
            type="button"
            className="btn btn-ghost btn-icon comment-at"
            aria-label={t("detail.mention")}
            onMouseDown={(event) => event.preventDefault()}
            onClick={() => {
              const field = input.current;
              const caret = field?.selectionStart ?? draft.length;
              const before = draft.slice(0, caret);
              const spacer = before && !/\s$/.test(before) ? " " : "";
              const next = `${before}${spacer}@${draft.slice(caret)}`;
              setDraft(next);
              setQuery({ start: caret + spacer.length, query: "" });
              requestAnimationFrame(() => {
                field?.focus();
                field?.setSelectionRange(caret + spacer.length + 1, caret + spacer.length + 1);
              });
            }}
          >
            <AtSign size={20} strokeWidth={2.4} />
          </button>
          <input
            ref={input}
            className="input"
            placeholder={t("detail.commentPlaceholder")}
            value={draft}
            maxLength={2000}
            role="combobox"
            aria-expanded={listOpen}
            aria-autocomplete="list"
            onChange={(event) => onType(event.target.value, event.target.selectionStart ?? event.target.value.length)}
            onKeyDown={(event) => {
              if (listOpen && candidates.length) {
                if (event.key === "ArrowDown") {
                  event.preventDefault();
                  setActive((active + 1) % Math.min(candidates.length, 6));
                  return;
                }
                if (event.key === "ArrowUp") {
                  event.preventDefault();
                  setActive((active - 1 + Math.min(candidates.length, 6)) % Math.min(candidates.length, 6));
                  return;
                }
                if (event.key === "Enter") {
                  event.preventDefault();
                  pick(candidates[active]);
                  return;
                }
              }
              if (event.key === "Escape" && listOpen) {
                event.preventDefault();
                setQuery(null);
                return;
              }
              if (event.key === "Enter") send();
            }}
            onBlur={() => setQuery(null)}
            style={{ minHeight: 48, fontSize: 16, paddingInline: 18 }}
          />
          <button className="btn btn-primary btn-icon" aria-label={t("detail.sendComment")} disabled={!draft.trim() || add.isPending} onClick={send}>
            <SendHorizontal size={20} strokeWidth={2.5} />
          </button>
        </div>
        {names.length > 0 && (
          <div className="comment-hint">{t("detail.mentionHint", { names: names.map(([id]) => candidatesName(id, people, team.data)).join(", ") })}</div>
        )}
      </div>
    </div>
  );
}

function nameInitials(name: string): string {
  const [first = "", last = ""] = name.split(" ");
  return initials(first, last);
}

function candidatesName(id: number, people: MemberBrief[], team: MemberBrief[] | undefined): string {
  return people.find((person) => person.id === id)?.name ?? team?.find((person) => person.id === id)?.name ?? "";
}

/** A comment typed and not sent yet survives leaving the task (and a reload) in this session. */
function readDraft(key: string): string {
  try {
    return window.sessionStorage.getItem(key) ?? "";
  } catch {
    return "";
  }
}

function saveDraft(key: string, text: string): void {
  try {
    if (text.trim()) window.sessionStorage.setItem(key, text);
    else window.sessionStorage.removeItem(key);
  } catch {
    // Only a convenience.
  }
}

/** Highlights @names the way the design does. */
function Mentions({ text }: { text: string }) {
  return (
    <>
      {text.split(/(@[\p{L}\p{N}_]+)/u).map((part, index) =>
        part.startsWith("@") ? (
          <span key={index} style={{ color: "var(--color-accent-700)", fontWeight: 700 }}>{part}</span>
        ) : (
          <span key={index}>{part}</span>
        ),
      )}
    </>
  );
}

/**
 * The task's actions in the bottom bar, like every page's: Telegram's main button for the one that
 * finishes the step (Mark as done, Send again, Confirm) and its secondary button beside it (Start,
 * Send back). Outside Telegram, or on an older client, the same two buttons sit in the page.
 */
function ActionBar({ task, isMine }: { task: Task; isMine: boolean }) {
  const { t } = useViewContext();
  const member = useMember();
  const navigation = useNavigation();
  const action = useTaskAction(member.companyId);
  const complete = useCompleteTask();
  const confirmTasks = useConfirmTasks();
  const queue = useReviewQueue(member.companyId, task.actions.includes("confirm"));
  const toast = useToast();
  const start = () =>
    action.mutate(
      { taskId: task.id, action: "start" },
      {
        onSuccess: () => {
          haptic("success");
          toast(t("toast.started"));
        },
        onError: (error) => toast(errorText(error, t), { tone: "error" }),
      },
    );
  // Confirm goes out after a moment with Undo; meanwhile the next thing to check opens (audit M-9).
  const confirm = () => {
    const next = (queue.data ?? []).find((other) => other.id !== task.id);
    confirmTasks([task]);
    if (next) navigation.openTask(next.id);
    else navigation.closeTask();
  };

  let primary: BottomAction | null = null;
  let secondary: BottomAction | undefined;
  if (task.actions.includes("confirm")) {
    primary = { text: t("detail.confirm"), icon: Check, onClick: confirm };
  } else if (task.actions.includes("complete")) {
    primary = {
      text: task.status === "returned" ? t("detail.sendAgain") : t("detail.markDone"),
      icon: Check,
      disabled: action.isPending,
      onClick: () => complete(task),
    };
  } else if (task.status === "review" && isMine) {
    primary = { text: t("detail.waiting"), icon: Hourglass, disabled: true, onClick: () => undefined };
  }
  if (task.actions.includes("return")) {
    secondary = { text: t("detail.sendBack"), icon: Undo2, onClick: () => navigation.openSheet({ kind: "return", taskId: task.id }) };
  } else if (task.actions.includes("start") && task.kind === "assigned" && task.status !== "returned") {
    // As in the design, Start is for assigned work (so whoever gave it sees it's underway);
    // daily and personal tasks, and anything sent back, just get done.
    secondary = { text: t("detail.start"), icon: Play, disabled: action.isPending, onClick: start };
  }
  if (!primary && secondary) [primary, secondary] = [secondary, undefined];
  return primary ? <BottomBar primary={primary} secondary={secondary} /> : null;
}

/**
 * Who checks the task, as the person looking reads it: whoever confirmed it once it's checked,
 * "You" for the one who checks it (not "Your manager" to the manager), the giver of assigned work,
 * else "Your manager".
 */
export function checker(task: Task, me: number, t: ViewContext["t"]): string {
  if (!task.needs_confirmation) return t("detail.checkNo");
  if (task.confirmed_by) return task.confirmed_by.id === me ? t("detail.checkYou") : task.confirmed_by.name;
  if (task.actions.includes("confirm") || task.created_by?.id === me) return t("detail.checkYou");
  if (task.kind === "assigned" && task.created_by) return task.created_by.name;
  return t("detail.checkYes");
}
