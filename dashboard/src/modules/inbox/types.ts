/**
 * Shapes of the inbox endpoints (plan §4.2, owned by W0-L's apps.inbox and apps.console). Written
 * by hand from the serializers, like every module's types.ts: money and dates are strings.
 *
 * The queue and notification rows are shared with the shell's inbox drawer, so they live in
 * @/api/types; this file adds what only the inbox page needs.
 */
import type { Notification, QueueAction, QueueItem, QueueKind, QueueResponse, Severity, UnreadCount } from "@/api/types";

export type { Notification, QueueAction, QueueItem, QueueKind, QueueResponse, Severity, UnreadCount };

export type InboxTab = "needs" | "notifications";
export type NotificationTab = "unread" | "all";

/** `GET O inbox/?tab=&page=&page_size=` */
export interface NotificationParams {
  tab: NotificationTab;
  page_size?: number;
}

/** `GET O queue/counts/` */
export interface QueueCounts {
  total: number;
  kinds: QueueKind[];
}

/** A queue item's stable identity across kinds (ids repeat between kinds). */
export function queueKey(item: Pick<QueueItem, "kind" | "id">): string {
  return `${item.kind}:${item.id}`;
}
