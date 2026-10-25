import { AlarmClock, BellRing, Clock3 } from "lucide-react";

import type { ReminderInfo, Task } from "../api/types";
import { duration, lateBy, type ViewContext } from "../lib/taskView";
import { clock } from "../lib/time";
import { initials } from "../state/session";

type Node = { key: string; mark: string; time: string; caption: string; state: "sent" | "next" | "future" | "escalation" };

const MINUTE = 60_000;

/** The design's late card: how many reminders went out, when the next one comes, and
 * who hears about it after that. */
export function LateCard({
  task,
  reminder,
  ctx,
  onSnooze,
  snoozing,
  onAskHelp,
}: {
  task: Task;
  reminder: ReminderInfo | null;
  ctx: ViewContext;
  onSnooze: () => void;
  snoozing: boolean;
  onAskHelp: () => void;
}) {
  const { t } = ctx;
  const at = (moment: string | Date) => clock(moment, ctx.timeZone, ctx.locale);
  const nodes = reminder ? timeline(task, reminder, ctx) : [];
  // How many reminders go out at most (0: until it's done), not when the manager hears (audit M-5).
  const total = reminder?.max_reminders ?? 0;
  const snoozedAt = task.snoozed_until ?? reminder?.snoozed_until ?? null;
  const snoozed = snoozedAt && new Date(snoozedAt) > ctx.now ? snoozedAt : null;
  // Without a name, "your manager" reads inside a sentence; one that starts with it has its own text.
  const named = reminder?.escalate_to ?? null;
  const manager = named ?? t("detail.reminders.manager");
  const escalation = nodes.find((node) => node.state === "escalation");

  let subtitle = t("detail.late.body", { time: at(task.due_at!) });
  if (snoozed) subtitle = t("detail.reminders.snoozed", { time: at(snoozed) });
  else if (reminder && total > 0 && reminder.sent >= total) subtitle = t("detail.reminders.allSent", { total });
  else if (reminder?.next_at && reminder.sent > 0)
    subtitle =
      total > 0
        ? t("detail.reminders.progress", { sent: reminder.sent, total, time: at(nextReminder(reminder.next_at, ctx.now)) })
        : t("detail.reminders.sentSoFar", { sent: reminder.sent, time: at(nextReminder(reminder.next_at, ctx.now)) });
  else if (reminder?.next_at) subtitle = t("detail.reminders.first", { time: at(nextReminder(reminder.next_at, ctx.now)) });

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16, padding: 18, borderRadius: "var(--radius-lg)", background: "var(--color-accent-100)", color: "var(--color-accent-900)" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <span className="circle" style={{ width: 42, height: 42, background: "var(--color-accent)", color: "var(--color-bg)" }}>
          <AlarmClock size={21} strokeWidth={2.4} />
        </span>
        <div style={{ display: "flex", flexDirection: "column" }}>
          <span className="num" style={{ fontSize: 18, fontWeight: 700 }}>
            {t("detail.late.title", { duration: duration(lateBy(task, ctx.now), t) })}
          </span>
          <span className="num" style={{ fontSize: 14 }}>{subtitle}</span>
        </div>
      </div>

      {nodes.length > 0 && (
        <div style={{ display: "flex" }}>
          {nodes.map((node, index) => (
            // A little room at the sides: two "Отправлено" side by side at 360 px never run together.
            <div key={node.key} style={{ flex: 1, minWidth: 0, padding: "0 2px", position: "relative", display: "flex", flexDirection: "column", alignItems: "center", gap: 4 }}>
              {index < nodes.length - 1 && (
                <span style={{ position: "absolute", top: 15, left: "50%", width: "100%", height: 3, borderRadius: 3, background: "color-mix(in srgb, var(--color-accent) 30%, transparent)" }} />
              )}
              <NodeDot node={node} />
              <span className="num" style={{ fontSize: 13.5, fontWeight: 700 }}>{node.time}</span>
              <span style={{ fontSize: 11.5, marginTop: -4, maxWidth: "100%", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {node.caption}
              </span>
            </div>
          ))}
        </div>
      )}

      {reminder && (
        <div style={{ fontSize: 15, lineHeight: 1.5, textWrap: "pretty" }}>
          {t("detail.reminders.every", { every: reminder.every_minutes })}{" "}
          {reminder.escalated_at
            ? named
              ? t("detail.reminders.escalated", { name: named })
              : t("detail.reminders.escalatedManager")
            : escalation
              ? t("detail.reminders.escalateAt", { time: escalation.time, name: manager })
              : null}
        </div>
      )}

      {reminder && task.actions.includes("complete") && (
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <button
            className="btn btn-secondary"
            disabled={reminder.snoozes_left === 0 || snoozing}
            onClick={onSnooze}
            style={{ minHeight: 44, padding: "0 16px", fontFamily: "var(--font-body)", fontWeight: 700, fontSize: 14.5, background: "var(--color-bg)", borderColor: "transparent" }}
          >
            <Clock3 size={17} strokeWidth={2.6} />
            <span>
              {reminder.snoozes_left === 0
                ? t("detail.noSnooze")
                : task.snoozed_until !== undefined
                  ? t("detail.snoozeChoices", { left: reminder.snoozes_left })
                  : t("detail.snooze", { minutes: reminder.snooze_minutes, left: reminder.snoozes_left })}
            </span>
          </button>
          <button className="btn btn-ghost" onClick={onAskHelp} style={{ minHeight: 44, padding: "0 14px", color: "var(--color-accent-800)" }}>
            {t("detail.askHelp")}
          </button>
        </div>
      )}
    </div>
  );
}

/** For open tasks that aren't late yet: what the bot will do at the deadline (shown just above). */
export function ReminderNote({ task, reminder, ctx }: { task: Task; reminder: ReminderInfo; ctx: ViewContext }) {
  const text =
    task.kind === "personal"
      ? ctx.t("detail.reminders.once")
      : ctx.t("detail.reminders.upcoming", { every: reminder.every_minutes });
  return (
    <div className="banner" style={{ alignItems: "center" }}>
      <span className="banner-icon" style={{ color: "var(--color-accent-700)" }}>
        <BellRing size={17} strokeWidth={2.6} />
      </span>
      <span className="num" style={{ fontSize: 15, lineHeight: 1.45, textWrap: "pretty" }}>{text}</span>
    </div>
  );
}

/**
 * When the next reminder goes: never a moment already gone. A reminder run that is behind (the
 * server catches up within a minute) would otherwise promise "next at 04:47" at 05:06, and an
 * escalation time in the past.
 */
function nextReminder(nextAt: string, now: Date): Date {
  return new Date(Math.max(Date.parse(nextAt), +now));
}

function timeline(task: Task, reminder: ReminderInfo, ctx: ViewContext): Node[] {
  const total = reminder.escalate_after;
  if (total === 0 || !task.due_at) return [];
  const at = (moment: number) => clock(new Date(moment), ctx.timeZone, ctx.locale);
  const due = Date.parse(task.due_at);
  const every = reminder.every_minutes * MINUTE;
  const next = reminder.next_at ? +nextReminder(reminder.next_at, ctx.now) : null;
  // Past reminders went out roughly on the interval; upcoming ones count from the next.
  const moment = (step: number) =>
    step <= reminder.sent ? due + (step - 1) * every : next !== null ? next + (step - reminder.sent - 1) * every : null;

  const nodes: Node[] = [];
  const sentTimes = reminder.sent_times ?? [];
  for (let step = 1; step <= total; step += 1) {
    const when = moment(step);
    const state = step <= reminder.sent ? "sent" : step === reminder.sent + 1 && next !== null ? "next" : "future";
    // A reminder that went out shows when it really did (the server's log); never a computed
    // "22:51", which quiet hours and snoozes would make up (audit M-5). Coming ones count from the next.
    const sentAt = state === "sent" ? sentTimes[step - 1] : undefined;
    nodes.push({
      key: String(step),
      mark: String(step),
      time: sentAt ? at(Date.parse(sentAt)) : when === null || state === "sent" ? "" : at(when),
      caption: state === "sent" ? ctx.t("detail.node.sent") : state === "next" ? ctx.t("detail.node.next") : "",
      state,
    });
  }
  const name = reminder.escalate_to;
  const [first = "", last = ""] = (name ?? "").split(" ");
  const escalatedAt = reminder.escalated_at ? Date.parse(reminder.escalated_at) : moment(total);
  nodes.push({
    key: "escalation",
    mark: name ? initials(first, last) : "M",
    time: escalatedAt === null ? "" : at(escalatedAt),
    // A caption under the dot, capitalised like "Sent" and "Next" beside it.
    caption: first || ctx.t("detail.node.manager"),
    state: "escalation",
  });
  return nodes;
}

function NodeDot({ node }: { node: Node }) {
  const base = { position: "relative" as const, width: 32, height: 32, borderRadius: "50%", display: "grid", placeItems: "center", fontSize: 14, fontWeight: 700 };
  if (node.state === "sent") {
    return (
      <span style={{ ...base, background: "var(--color-accent)", color: "var(--color-bg)" }}>
        <BellRing size={15} strokeWidth={2.6} />
      </span>
    );
  }
  if (node.state === "next") {
    return (
      <span style={{ position: "relative", width: 32, height: 32 }}>
        <span className="pulse" style={{ background: "var(--color-accent-300)" }} />
        <span style={{ ...base, position: "absolute", inset: 0, background: "var(--color-bg)", boxShadow: "inset 0 0 0 3px var(--color-accent)", color: "var(--color-accent-700)" }}>
          {node.mark}
        </span>
      </span>
    );
  }
  if (node.state === "escalation") {
    return <span style={{ ...base, fontSize: 12, background: "var(--color-accent-2-200)", color: "var(--color-accent-2-800)" }}>{node.mark}</span>;
  }
  return (
    <span style={{ ...base, background: "var(--color-bg)", boxShadow: "inset 0 0 0 2px color-mix(in srgb, var(--color-accent) 40%, transparent)", color: "var(--color-accent-700)" }}>
      {node.mark}
    </span>
  );
}
