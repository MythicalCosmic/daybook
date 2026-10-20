import { Check, Hourglass, SendHorizontal, Undo2, X } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";

import {
  useAddComment,
  useComments,
  useSummary,
  useTask,
  useTaskAction,
  useToggleChecklist,
} from "../api/hooks";
import type { Comment, Task } from "../api/types";
import { LateCard, ReminderNote } from "../components/Reminders";
import { errorText, useCompleteTask } from "../lib/actions";
import { isLate, repeatLabel, type ViewContext } from "../lib/taskView";
import { clock, dayMonth, daysFromToday, weekdayShort } from "../lib/time";
import { useViewContext } from "../lib/useNow";
import { useNavigation } from "../state/navigation";
import { initials, useMember } from "../state/session";
import { useToast } from "../state/toast";
import { haptic } from "../telegram";

export function TaskDetail({ taskId }: { taskId: number }) {
  const ctx = useViewContext();
  const member = useMember();
  const task = useTask(member.companyId, taskId);
  const comments = useComments(member.companyId, taskId);

  return (
    <div className="detail-layer">
      {task.data ? (
        <Detail task={task.data} comments={comments.data ?? []} ctx={ctx} />
      ) : (
        <div className="screen screen--detail">
          <div className="skeleton" style={{ height: 40, width: "60%" }} />
          <div className="skeleton" style={{ height: 120 }} />
          <div className="skeleton" style={{ height: 180 }} />
        </div>
      )}
    </div>
  );
}

function Detail({ task, comments, ctx }: { task: Task; comments: Comment[]; ctx: ViewContext }) {
  const { t } = ctx;
  const member = useMember();
  const late = isLate(task, ctx.now);
  const isMine = task.assignee.id === member.id;
  const repeat = repeatLabel(task.repeat_weekdays, ctx);
  const toggle = useToggleChecklist(member.companyId);
  const action = useTaskAction(member.companyId);
  const summary = useSummary(member.companyId);
  const toast = useToast();
  const lastComment = comments.at(-1);
  const [draftSeed, setDraftSeed] = useState<{ text: string } | null>(null);
  const quiet = summary.data?.quiet_from && summary.data.quiet_until ? summary.data : null;

  const snooze = () => {
    haptic();
    action.mutate(
      { taskId: task.id, action: "snooze" },
      {
        onSuccess: (snoozed) =>
          toast(
            t("toast.snoozed", {
              time: snoozed.reminder?.snoozed_until ? clock(snoozed.reminder.snoozed_until, ctx.timeZone, ctx.locale) : "",
            }),
          ),
        onError: (error) => toast(errorText(error, t)),
      },
    );
  };
  // Mention whoever hears about it being late, so they get the comment as a nudge.
  const askForHelp = () => {
    const name = task.reminder?.escalate_to ?? task.created_by?.name ?? "";
    setDraftSeed({ text: name ? `@${name.split(" ")[0]} ` : "" });
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
        ? t("detail.kicker.from", { name: task.created_by.name })
        : repeat
          ? t("detail.kicker.ownRepeat", { repeat })
          : t("detail.kicker.own");

  const details: [string, string][] = [
    [t("detail.due"), dueLabel(task, ctx)],
    [t("detail.repeats"), repeat ?? t("detail.no")],
    [t("detail.proof"), t(`proof.${task.proof}`)],
    [
      t("detail.check"),
      task.needs_confirmation
        ? task.kind === "assigned" && task.created_by
          ? task.created_by.name
          : t("detail.checkYes")
        : t("detail.checkNo"),
    ],
  ];
  if (!isMine) details.push([t("detail.for"), task.assignee.name]);

  const checklistDone = task.checklist.filter((item) => item.is_done).length;
  const canTick = isMine && task.actions.includes("complete");

  return (
    <>
      <div className="screen screen--detail">
        <div style={{ display: "flex", flexDirection: "column", gap: 10, padding: "0 4px" }}>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            <span className={`tag tag-${status.tone}`} style={{ fontSize: 13, padding: "4px 11px" }}>{status.label}</span>
            {task.proof !== "none" && task.status !== "done" && (
              <span className="tag tag-neutral" style={{ fontSize: 13, padding: "4px 11px" }}>{t(`proof.tag.${task.proof}`)}</span>
            )}
          </div>
          <h1 className="heading title-md" style={{ lineHeight: 1.1, textWrap: "pretty" }}>{task.title}</h1>
          <div className="num" style={{ fontSize: 15, color: "color-mix(in srgb, var(--color-text) 64%, transparent)" }}>{kicker}</div>
        </div>

        <StatusBanner task={task} lastComment={lastComment} ctx={ctx} />

        {late && task.due_at && (
          <LateCard task={task} reminder={task.reminder} ctx={ctx} onSnooze={snooze} snoozing={action.isPending} onAskHelp={askForHelp} />
        )}
        {!late && task.reminder && task.due_at && isMine && (
          <ReminderNote task={task} reminder={task.reminder} when={dueLabel(task, ctx)} ctx={ctx} />
        )}
        {late && quiet && (
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
            {task.checklist.map((item) => (
              <button
                key={item.id}
                role="checkbox"
                aria-checked={item.is_done}
                disabled={!canTick}
                onClick={() => {
                  haptic();
                  toggle.mutate(
                    { taskId: task.id, itemId: item.id, done: !item.is_done },
                    { onError: (error) => toast(errorText(error, t)) },
                  );
                }}
                className="check-item"
              >
                <span className={item.is_done ? "check-box check-box--done" : "check-box"}>
                  {item.is_done && <Check size={16} strokeWidth={3} />}
                </span>
                <span style={item.is_done ? { color: "color-mix(in srgb, var(--color-text) 58%, transparent)" } : undefined}>{item.text}</span>
              </button>
            ))}
          </div>
        )}

        {task.proof_text && (
          <div className="card" style={{ gap: 6 }}>
            <div className="card-title">{t("complete.note")}</div>
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

        <Comments task={task} comments={comments} ctx={ctx} seed={draftSeed} />
      </div>
      <ActionBar task={task} isMine={isMine} />
    </>
  );
}

function StatusBanner({ task, lastComment, ctx }: { task: Task; lastComment?: Comment; ctx: ViewContext }) {
  const { t } = ctx;
  const at = (moment: string | null) => (moment ? clock(moment, ctx.timeZone, ctx.locale) : "—");
  let banner: { tone: string; icon: ReactNode; title: string; note?: string } | null = null;
  if (task.status === "review") {
    banner = { tone: "", icon: <Hourglass size={17} strokeWidth={2.6} />, title: t("detail.banner.review", { time: at(task.completed_at) }), note: t("detail.banner.reviewNote") };
  } else if (task.status === "returned") {
    banner = {
      tone: "accent",
      icon: <Undo2 size={17} strokeWidth={2.6} />,
      title: t("detail.banner.returned", { name: lastComment?.author?.name ?? task.created_by?.name ?? "—" }),
      note: lastComment ? `“${lastComment.text}”` : undefined,
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

function Comments({ task, comments, ctx, seed }: {
  task: Task;
  comments: Comment[];
  ctx: ViewContext;
  seed: { text: string } | null;
}) {
  const { t } = ctx;
  const member = useMember();
  const add = useAddComment(member.companyId, task.id);
  const toast = useToast();
  const [draft, setDraft] = useState("");
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (!seed) return;
    setDraft(seed.text);
    input.current?.focus();
    input.current?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [seed]);
  const send = () => {
    const text = draft.trim();
    if (!text || add.isPending) return;
    add.mutate(text, {
      onSuccess: () => {
        haptic();
        setDraft("");
      },
      onError: (error) => toast(errorText(error, t)),
    });
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
        const when =
          daysFromToday(comment.created_at, ctx.now, ctx.timeZone) === 0
            ? clock(comment.created_at, ctx.timeZone, ctx.locale)
            : dayMonth(comment.created_at, ctx.timeZone, ctx.locale);
        return (
          <div key={comment.id} style={{ display: "flex", gap: 10, alignItems: "flex-end" }}>
            <div className="avatar" style={{ width: 34, height: 34, fontSize: 13 }}>{initials(first, last)}</div>
            <div style={{ flex: 1, minWidth: 0, padding: "10px 14px", borderRadius: "var(--radius-md) var(--radius-md) var(--radius-md) var(--radius-sm)", background: "var(--color-surface)" }}>
              <div style={{ display: "flex", alignItems: "baseline", gap: 6, fontSize: 13 }}>
                <span style={{ fontWeight: 700 }}>{name}</span>
                {comment.author?.position && <span className="muted">{comment.author.position}</span>}
                <span className="muted num" style={{ marginLeft: "auto" }}>{when}</span>
              </div>
              <div style={{ fontSize: 15, lineHeight: 1.45, marginTop: 2, textWrap: "pretty", whiteSpace: "pre-wrap" }}>
                <Mentions text={comment.text} />
              </div>
            </div>
          </div>
        );
      })}
      {comments.length === 0 && <div className="muted" style={{ padding: "0 4px", fontSize: 15 }}>{t("detail.noComments")}</div>}
      <div style={{ display: "flex", gap: "var(--space-2)", alignItems: "center" }}>
        <input
          ref={input}
          className="input"
          placeholder={t("detail.commentPlaceholder")}
          value={draft}
          maxLength={2000}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => event.key === "Enter" && send()}
          style={{ minHeight: 48, fontSize: 16, paddingInline: 18 }}
        />
        <button className="btn btn-primary btn-icon" aria-label={t("detail.sendComment")} disabled={!draft.trim() || add.isPending} onClick={send}>
          <SendHorizontal size={20} strokeWidth={2.5} />
        </button>
      </div>
    </div>
  );
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

function ActionBar({ task, isMine }: { task: Task; isMine: boolean }) {
  const { t } = useViewContext();
  const member = useMember();
  const navigation = useNavigation();
  const action = useTaskAction(member.companyId);
  const complete = useCompleteTask();
  const toast = useToast();
  const run = (kind: "start" | "confirm", success: string) =>
    action.mutate(
      { taskId: task.id, action: kind },
      {
        onSuccess: () => {
          haptic("success");
          toast(success);
        },
        onError: (error) => toast(errorText(error, t)),
      },
    );

  const buttons: ReactNode[] = [];
  // As in the design, Start is for assigned work (so whoever gave it sees it's underway);
  // daily and personal tasks, and anything sent back, just get done.
  if (task.actions.includes("start") && task.kind === "assigned" && task.status !== "returned") {
    buttons.push(
      <button key="start" className="btn btn-secondary btn-lg" style={{ flex: 1, fontSize: 17 }} disabled={action.isPending} onClick={() => run("start", t("toast.started"))}>
        {t("detail.start")}
      </button>,
    );
  }
  if (task.actions.includes("complete")) {
    buttons.push(
      <button key="complete" className="btn btn-primary btn-lg" style={{ flex: 2 }} disabled={action.isPending} onClick={() => complete(task)}>
        <Check size={20} strokeWidth={3} />
        <span>{task.status === "returned" ? t("detail.sendAgain") : t("detail.markDone")}</span>
      </button>,
    );
  }
  if (task.status === "review" && isMine) {
    buttons.push(
      <button key="waiting" className="btn btn-secondary btn-lg" style={{ flex: 1, fontSize: 17 }} disabled>
        {t("detail.waiting")}
      </button>,
    );
  }
  if (task.actions.includes("return")) {
    buttons.push(
      <button key="return" className="btn btn-secondary btn-lg" style={{ flex: 1, fontSize: 17 }} onClick={() => navigation.openSheet({ kind: "return", taskId: task.id })}>
        {t("detail.sendBack")}
      </button>,
    );
  }
  if (task.actions.includes("confirm")) {
    buttons.push(
      <button key="confirm" className="btn btn-primary btn-lg" style={{ flex: 2 }} disabled={action.isPending} onClick={() => run("confirm", t("toast.confirmed"))}>
        <Check size={20} strokeWidth={3} />
        <span>{t("detail.confirm")}</span>
      </button>,
    );
  }
  return buttons.length ? <div className="action-bar">{buttons}</div> : null;
}

function dueLabel(task: Task, ctx: ViewContext): string {
  if (!task.due_at) return "—";
  const time = clock(task.due_at, ctx.timeZone, ctx.locale);
  const days = daysFromToday(task.due_at, ctx.now, ctx.timeZone);
  if (days === 0) return `${ctx.t("day.today")}, ${time}`;
  if (days === 1) return `${ctx.t("day.tomorrow")}, ${time}`;
  return `${weekdayShort(task.due_at, ctx.timeZone, ctx.locale)} ${dayMonth(task.due_at, ctx.timeZone, ctx.locale)}, ${time}`;
}
