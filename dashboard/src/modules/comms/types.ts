/**
 * Shapes of the announcements endpoints (plan §4.6, apps.announcements.owner_api), written by
 * hand from the serializers. `text` is Telegram HTML; instants are ISO strings.
 */
import type { BranchRef, PersonRef } from "@/api/types";

export type AnnouncementStatus = "draft" | "scheduled" | "sent" | "cancelled";

export interface Named {
  id: number;
  name: string;
}

/** One row of `GET announcements/` and `announcements/{id}/`. */
export interface Announcement {
  id: number;
  title: string;
  text: string;
  status: AnnouncementStatus;
  author: PersonRef | null;
  positions: Named[];
  branches: BranchRef[];
  created_at: string;
  scheduled_for: string | null;
  sent_at: string | null;
  pinned_until: string | null;
  expires_at: string | null;
  is_pinned: boolean;
  is_expired: boolean;
  recipients_count: number;
  read_count: number;
  /** "75.0" or null before anyone got it. */
  read_rate: string | null;
}

export interface AnnouncementParams {
  status?: AnnouncementStatus[];
  q?: string;
  pinned?: string;
  page?: number;
  page_size?: number;
}

export interface PublishInput {
  text_html: string;
  position_ids: number[];
  branch_ids: number[];
  scheduled_for: string | null;
  pinned_until: string | null;
  expires_at: string | null;
}

/** One row of `GET announcements/{id}/receipts/`. */
export interface Receipt {
  id: number;
  member: PersonRef;
  position: string | null;
  home_branch: BranchRef | null;
  read_at: string | null;
  reminded_at: string | null;
}

export interface AudienceCount {
  count: number;
  sample: Named[];
}

export interface AnnouncementStats {
  sent_30d: number;
  read_rate_30d: string | null;
  scheduled: number;
  pinned: number;
  unread_people_30d: number;
}
