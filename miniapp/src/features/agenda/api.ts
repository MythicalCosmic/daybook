/** The calendar endpoints of the mini app (`/api/v1/companies/{id}/calendar/…`), typed by hand. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../../api/client";

export type CalendarEntry = {
  id: string;
  source: string;
  kind: string;
  title: string;
  start: string;
  end: string | null;
  all_day: boolean;
  color: string;
  url: string;
  /** Where a company event happens; empty for other calendars. */
  subtitle?: string;
};

export type CalendarData = {
  range: { from: string; to: string };
  sources: { key: string; label: string }[];
  items: CalendarEntry[];
  /** Ids of the items that are events the person is invited to. */
  mine: string[];
  /** The person's answer to each event in `items` they are invited to. */
  answers?: Record<string, "pending" | "going" | "declined">;
};

export type Answer = "pending" | "going" | "declined";

export type AgendaEvent = {
  id: number;
  title: string;
  description: string;
  kind: "meeting" | "training" | "inventory" | "celebration" | "deadline" | "other";
  color: string;
  start: string;
  end: string | null;
  all_day: boolean;
  place: string;
  branch: { id: number; name: string } | null;
  repeat: "none" | "weekly" | "monthly";
  repeat_until: string | null;
  remind_before: number | null;
  created_by: { id: number; name: string } | null;
  attendees: { member: { id: number; name: string; position: string | null }; response: Answer }[];
  responses: Record<Answer, number>;
  my_response: Answer | null;
  cancelled: boolean;
  cancel_reason: string;
};

const base = (company: number) => `/companies/${company}/calendar`;

export const agendaKeys = {
  all: (company: number) => ["agenda", company] as const,
  window: (company: number, from: string, to: string) => ["agenda", company, "window", from, to] as const,
  event: (company: number, id: number) => ["agenda", company, "event", id] as const,
};

export function useCalendar(company: number, from: string, to: string) {
  return useQuery({
    queryKey: agendaKeys.window(company, from, to),
    queryFn: () => api<CalendarData>(`${base(company)}/?from=${from}&to=${to}`),
    placeholderData: (previous) => previous,
    staleTime: 30_000,
  });
}

export function useEvent(company: number, id: number) {
  return useQuery({ queryKey: agendaKeys.event(company, id), queryFn: () => api<AgendaEvent>(`${base(company)}/events/${id}/`) });
}

/** I'll come / Can't come: the answer shows at once and goes back if the server refuses. */
export function useAnswer(company: number, id: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (response: Exclude<Answer, "pending">) =>
      api(`${base(company)}/events/${id}/respond/`, { method: "POST", json: { response } }),
    onMutate: async (response) => {
      const key = agendaKeys.event(company, id);
      await client.cancelQueries({ queryKey: key });
      const before = client.getQueryData<AgendaEvent>(key);
      if (before) client.setQueryData<AgendaEvent>(key, { ...before, my_response: response });
      return { before };
    },
    onError: (_error, _response, context) => {
      if (context?.before) client.setQueryData(agendaKeys.event(company, id), context.before);
    },
    onSettled: () => client.invalidateQueries({ queryKey: agendaKeys.all(company) }),
  });
}

/** The company event an item stands for ("agenda.events:12-20261027" → 12), or null. */
export function eventIdOf(entry: Pick<CalendarEntry, "id" | "kind">): number | null {
  if (entry.kind !== "agenda.event") return null;
  const id = Number((entry.id.split(":", 2)[1] ?? "").split("-", 1)[0]);
  return Number.isFinite(id) && id > 0 ? id : null;
}

/** The first and last company-local day an item covers. */
export function itemDays(entry: CalendarEntry, dayOf: (iso: string) => string): { first: string; last: string } {
  if (entry.all_day) {
    const first = entry.start.slice(0, 10);
    const last = (entry.end ?? entry.start).slice(0, 10);
    return { first, last: last < first ? first : last };
  }
  const first = dayOf(entry.start);
  return { first, last: first };
}
