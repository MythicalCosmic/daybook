/**
 * Shapes of the company calendar endpoints (`apps.agenda.owner_api`, `serializers.py`), written by
 * hand. All-day items carry company-local days ("2026-10-24", `end` inclusive); timed items carry
 * ISO instants in the company's timezone.
 */

export interface AgendaPerson {
  id: number;
  name: string;
  photo_url: string | null;
}

export interface CalendarSource {
  key: string;
  label: string;
}

/** One date from any module (`console.registry.CalendarItem` plus its source). */
export interface CalendarEntry {
  /** Unique across sources: "agenda.events:12-20261027". */
  id: string;
  source: string;
  kind: string;
  title: string;
  start: string;
  end: string | null;
  all_day: boolean;
  /** A design token name ("chart-3", "danger"); the client turns it into a colour. */
  color: string;
  url: string;
}

export interface CalendarResponse {
  range: { from: string; to: string };
  sources: CalendarSource[];
  items: CalendarEntry[];
}

export type EventKind = "meeting" | "training" | "inventory" | "celebration" | "deadline" | "other";
export type EventVisibility = "company" | "attendees";
export type EventRepeat = "none" | "weekly" | "monthly";
export type AttendeeResponse = "pending" | "going" | "declined";

export interface Attendee {
  member: AgendaPerson & { position: string | null };
  response: AttendeeResponse;
  responded_at: string | null;
}

export interface AgendaEvent {
  id: number;
  title: string;
  description: string;
  kind: EventKind;
  color: string;
  start: string;
  end: string | null;
  all_day: boolean;
  place: string;
  branch: { id: number; name: string } | null;
  visibility: EventVisibility;
  remind_before: number | null;
  repeat: EventRepeat;
  repeat_until: string | null;
  created_by: AgendaPerson | null;
  attendees: Attendee[];
  responses: Record<AttendeeResponse, number>;
  my_response: AttendeeResponse | null;
  cancelled: boolean;
  cancel_reason: string;
  can_edit: boolean;
  created_at: string;
  updated_at: string;
}

export interface EventInput {
  title: string;
  description: string;
  kind: EventKind;
  /** A day for all-day events, else a local moment "2026-10-24T10:00". */
  start: string;
  end: string | null;
  all_day: boolean;
  place: string;
  branch: number | null;
  visibility: EventVisibility;
  attendee_ids: number[];
  remind_before: number | null;
  repeat: EventRepeat;
  repeat_until: string | null;
}

export interface Invitee {
  id: number;
  name: string;
  photo_url: string | null;
  subtitle: string;
  position_id: number | null;
  branch_ids: number[];
}

export interface AgendaSettings {
  default_remind_before: number | null;
  notify_invites: boolean;
}

export type CalendarView = "month" | "week" | "agenda";
