import { AtSign, Bell, CalendarClock, Check, CircleCheck, ClipboardList, Eye, MessageCircle, OctagonAlert, Undo2, type LucideIcon } from "lucide-react";

import type { Activity } from "../api/types";
import type { Key } from "../i18n";
import { clock, dayMonth, daysFromToday } from "../lib/time";
import type { ViewContext } from "../lib/taskView";

type Look = { icon: LucideIcon; background: string; color: string };

const LOOK: Record<string, Look> = {
  assigned: { icon: ClipboardList, background: "var(--color-bg)", color: "var(--color-text)" },
  review: { icon: Eye, background: "var(--color-accent-2-200)", color: "var(--color-accent-2-800)" },
  completed: { icon: CircleCheck, background: "var(--color-accent-2-200)", color: "var(--color-accent-2-800)" },
  confirmed: { icon: Check, background: "var(--color-accent-2)", color: "var(--color-bg)" },
  returned: { icon: Undo2, background: "var(--color-accent-200)", color: "var(--color-accent-800)" },
  commented: { icon: MessageCircle, background: "var(--color-bg)", color: "var(--color-text)" },
  mentioned: { icon: AtSign, background: "var(--color-bg)", color: "var(--color-accent-700)" },
  blocked: { icon: OctagonAlert, background: "var(--color-accent-200)", color: "var(--color-accent-800)" },
  extension: { icon: CalendarClock, background: "var(--color-accent-100)", color: "var(--color-accent-800)" },
};

/** Kinds the backend may add before the app knows them read as a plain update, never a crash. */
const OTHER: Look = { icon: Bell, background: "var(--color-bg)", color: "var(--color-text)" };
const KNOWN = new Set(Object.keys(LOOK));

export function ActivityRow({ item, ctx, onOpen }: { item: Activity; ctx: ViewContext; onOpen: () => void }) {
  const { icon: Icon, background, color } = LOOK[item.kind] ?? OTHER;
  const name = item.actor?.name ?? ctx.t("activity.someone");
  const title = ctx.t((KNOWN.has(item.kind) ? `activity.${item.kind}` : "activity.other") as Key, { name });
  const when =
    daysFromToday(item.created_at, ctx.now, ctx.timeZone) === 0
      ? clock(item.created_at, ctx.timeZone, ctx.locale)
      : dayMonth(item.created_at, ctx.timeZone, ctx.locale);
  return (
    <button className="row" style={{ padding: "12px 14px" }} onClick={onOpen}>
      <span className="circle" style={{ width: 40, height: 40, background, color }}>
        <Icon size={19} strokeWidth={2.4} />
      </span>
      <span className="row-main" style={{ gap: 1 }}>
        <span style={{ fontSize: 15, fontWeight: 700 }}>{title}</span>
        <span className="row-meta">{item.text || item.task.title}</span>
      </span>
      <span style={{ flex: "none", display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 6 }}>
        <span className="muted num" style={{ fontSize: 13 }}>{when}</span>
        {!item.is_read && <span style={{ width: 9, height: 9, borderRadius: "50%", background: "var(--color-accent)" }} />}
      </span>
    </button>
  );
}
