/**
 * The calendar's endpoints (`/api/v1/owner/companies/{cid}/calendar/…`) and vue-query helpers.
 * `calendar/` brings every source the person may see for a window of days; toggling sources only
 * filters on the client, so it is instant. Keys start with `[companyId, "agenda"]`.
 */
import { keepPreviousData, useQuery } from "@tanstack/vue-query";
import { computed, toValue, type MaybeRefOrGetter } from "vue";

import { http, ownerPath } from "@/api/http";
import { moduleKey, qk } from "@/api/keys";
import type { Page } from "@/api/types";
import { useCompanyStore } from "@/stores/company";

import type { AgendaEvent, AgendaSettings, Attendee, AttendeeResponse, CalendarResponse, EventInput, Invitee } from "./types";

export const MODULE = "agenda";
const path = (cid: number, rest = "") => ownerPath(cid, `calendar/${rest}`);

export const agendaApi = {
  calendar: (cid: number, range: { from: string; to: string }, signal?: AbortSignal) =>
    http.get<CalendarResponse>(path(cid), { from: range.from, to: range.to }, { signal }),
  events: (cid: number, params: { when?: string; q?: string; page?: number; page_size?: number }, signal?: AbortSignal) =>
    http.get<Page<AgendaEvent>>(path(cid, "events/"), params, { signal }),
  event: (cid: number, id: number, signal?: AbortSignal) => http.get<AgendaEvent>(path(cid, `events/${id}/`), undefined, { signal }),
  create: (cid: number, input: EventInput) => http.post<AgendaEvent>(path(cid, "events/"), input),
  update: (cid: number, id: number, input: Partial<EventInput>) => http.patch<AgendaEvent>(path(cid, `events/${id}/`), input),
  cancel: (cid: number, id: number, reason: string) => http.post<AgendaEvent>(path(cid, `events/${id}/cancel/`), { reason }),
  remind: (cid: number, id: number) => http.post<{ reminded: number }>(path(cid, `events/${id}/remind/`)),
  respond: (cid: number, id: number, response: Exclude<AttendeeResponse, "pending">) =>
    http.post<Attendee>(path(cid, `events/${id}/respond/`), { response }),
  people: (cid: number, signal?: AbortSignal) => http.get<Invitee[]>(path(cid, "people/"), undefined, { signal }),
  settings: (cid: number, signal?: AbortSignal) => http.get<AgendaSettings>(path(cid, "settings/"), undefined, { signal }),
  saveSettings: (cid: number, input: Partial<AgendaSettings>) => http.patch<AgendaSettings>(path(cid, "settings/"), input),
};

export const agendaKeys = {
  all: (cid: number) => moduleKey(cid, MODULE),
  calendar: (cid: number, from: string, to: string) => qk(cid, MODULE, "calendar", { from, to }),
  event: (cid: number, id: number) => qk(cid, MODULE, "event", { id }),
  people: (cid: number) => qk(cid, MODULE, "people"),
  settings: (cid: number) => qk(cid, MODULE, "settings"),
};

export function useCompanyId() {
  const company = useCompanyStore();
  return computed(() => company.currentId ?? 0);
}

export function useCalendar(range: MaybeRefOrGetter<{ from: string; to: string }>) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => {
      const value = toValue(range);
      return agendaKeys.calendar(cid.value, value.from, value.to);
    }),
    queryFn: ({ signal }) => agendaApi.calendar(cid.value, toValue(range), signal),
    enabled: computed(() => cid.value > 0),
    placeholderData: keepPreviousData,
    staleTime: 30_000,
  });
}

export function useEvent(id: MaybeRefOrGetter<number | null>) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => agendaKeys.event(cid.value, toValue(id) ?? 0)),
    queryFn: ({ signal }) => agendaApi.event(cid.value, toValue(id)!, signal),
    enabled: computed(() => cid.value > 0 && !!toValue(id)),
    staleTime: 15_000,
  });
}

export function useInvitees(enabled: MaybeRefOrGetter<boolean>) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => agendaKeys.people(cid.value)),
    queryFn: ({ signal }) => agendaApi.people(cid.value, signal),
    enabled: computed(() => cid.value > 0 && toValue(enabled)),
    staleTime: 5 * 60_000,
  });
}

export function useAgendaSettings() {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => agendaKeys.settings(cid.value)),
    queryFn: ({ signal }) => agendaApi.settings(cid.value, signal),
    enabled: computed(() => cid.value > 0),
  });
}
