/**
 * Maslahatchi's business reviews and "Ask the advisor" (`/api/v1/owner/companies/{cid}/briefings/…`,
 * apps.briefings): the types written by hand next to the calls, and the vue-query helpers the
 * Maslahatchi page uses. Keys start with `[companyId, "ai"]` (the AI module's), and the backend's
 * `briefings` pulse key refreshes them too (index.ts `invalidates`).
 *
 * A review answers only to readers of its own scope (the same domains and branches): the list,
 * the latest and one review never show another scope's, the server sees to it.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import { computed, toValue, type MaybeRefOrGetter } from "vue";

import { http, ownerPath } from "@/api/http";
import { qk } from "@/api/keys";
import type { Money } from "@/api/types";

import { MODULE, useCompanyId } from "./api";
import type { Conversation } from "./types";

export type BriefingKind = "weekly" | "monthly";
export type BriefingWriter = "ai" | "template";

export interface BriefingPeriod {
  kind: BriefingKind;
  start: string;
  end: string;
}

export interface BriefingSection {
  key: "went_well" | "went_wrong";
  title: string;
  bullets: string[];
  /** The signal key each bullet rests on. */
  facts: string[];
}

/** One of the (up to three) suggestions: tied to a signal and opening its page. */
export interface BriefingAction {
  text: string;
  fact: string;
  label: string;
  url: string;
}

/** A money figure with the period before and the average of the periods before (strings). */
export interface BriefingFigure {
  value: Money | null;
  previous: Money | null;
  average: Money | null;
  change: Money | null;
  change_pct: string | null;
  vs_average: Money | null;
  vs_average_pct: string | null;
}

/** A percentage (a margin, a share) and its moves in points. */
export interface BriefingShare {
  value: string;
  previous: string | null;
  average: string | null;
  change_pts: string | null;
  vs_average_pts: string | null;
}

export interface BriefingBranch {
  id: number;
  name: string;
  url: string;
  revenue: BriefingFigure;
  gross_profit: BriefingFigure;
  gross_margin: BriefingShare | null;
  expenses: BriefingFigure;
  profit: BriefingFigure;
  margin: BriefingShare | null;
}

export interface BriefingSignal {
  key: string;
  kind: string;
  tone: "good" | "bad";
  weight: number;
  subject: string | null;
  values: Record<string, unknown>;
  url: string;
}

export interface BriefingFinance {
  revenue: BriefingFigure;
  gross_profit: BriefingFigure;
  gross_margin: BriefingShare | null;
  expenses: BriefingFigure;
  profit: BriefingFigure;
  margin: BriefingShare | null;
  compared_periods: number;
  branches: BriefingBranch[];
  cash: {
    now: Money;
    low_30: { date: string; balance: Money };
    low_90: { date: string; balance: Money };
    below_zero_on: string | null;
    runway_days: number | null;
    horizon_days: number;
    url: string;
  };
  url: string;
}

export interface BriefingSales {
  net: BriefingFigure;
  receipts: { value: number; previous: number | null; average: string | null; change: number | null; vs_average_pct: string | null };
  average_receipt: BriefingFigure;
  url: string;
}

/** Every number of a review, the sections the reader may see (apps.briefings.facts). */
export interface BriefingFacts {
  version: number;
  kind: BriefingKind;
  period: BriefingPeriod;
  today: string;
  currency: string;
  domains: string[];
  every_branch: boolean;
  finance?: BriefingFinance;
  sales?: BriefingSales;
  stock?: { items: number; slow_count: number; value?: Money; days_of_cover?: number | null; url: string };
  attendance?: { late: { value: number; previous: number | null; average: string | null }; present: number; rostered: number; on_time_pct: string | null; url: string };
  people?: { headcount: number; joined_count: number; left_count: number; url: string };
  signals: BriefingSignal[];
}

export interface BriefingSummary {
  id: number;
  kind: BriefingKind;
  day: string;
  period: BriefingPeriod;
  headline: string;
  written_by: BriefingWriter;
  written_at: string | null;
  language: string;
}

export interface Briefing extends BriefingSummary {
  sections: BriefingSection[];
  actions: BriefingAction[];
  facts: BriefingFacts;
}

export interface BriefingLatest {
  review: Briefing | null;
  next: { weekly: string | null; monthly: string | null };
  writer: BriefingWriter;
  advisor_on: boolean;
  chat: boolean;
  has_data: boolean;
  can_regenerate: boolean;
  regenerations_left: number;
  can_configure: boolean;
}

export type BriefingRecipients = "owners" | "reports";

export interface BriefingSettings {
  weekly_enabled: boolean;
  monthly_enabled: boolean;
  /** 0 is Monday. */
  weekday: number;
  /** "08:00" */
  send_at: string;
  recipients: BriefingRecipients;
}

const path = (cid: number, rest = "") => ownerPath(cid, `briefings/${rest}`);

export const briefingsApi = {
  list: (cid: number, kind: BriefingKind, signal?: AbortSignal) => http.get<{ results: BriefingSummary[] }>(path(cid), { kind }, { signal }).then((body) => body.results),
  latest: (cid: number, kind: BriefingKind, signal?: AbortSignal) => http.get<BriefingLatest>(path(cid, "latest/"), { kind }, { signal }),
  one: (cid: number, id: number, signal?: AbortSignal) => http.get<Briefing>(path(cid, `${id}/`), undefined, { signal }),
  /** 200 with the review written again from the templates, or 202 `{queued}` while Claude writes it. */
  regenerate: (cid: number, kind: BriefingKind) => http.post<Briefing | { queued: true }>(path(cid, "regenerate/"), { kind }),
  settings: (cid: number, signal?: AbortSignal) => http.get<BriefingSettings>(path(cid, "settings/"), undefined, { signal }),
  saveSettings: (cid: number, patch: Partial<BriefingSettings>) => http.patch<BriefingSettings>(path(cid, "settings/"), patch),
  conversations: (cid: number, signal?: AbortSignal) => http.get<Conversation[]>(path(cid, "advisor/conversations/"), undefined, { signal }),
  newConversation: (cid: number) => http.post<Conversation>(path(cid, "advisor/conversations/"), {}),
};

export const briefingKeys = {
  list: (cid: number, kind: BriefingKind) => qk(cid, MODULE, "briefings", { kind }),
  latest: (cid: number, kind: BriefingKind) => qk(cid, MODULE, "briefing-latest", { kind }),
  one: (cid: number, id: number) => qk(cid, MODULE, "briefing", { id }),
  settings: (cid: number) => qk(cid, MODULE, "briefing-settings"),
  conversations: (cid: number) => qk(cid, MODULE, "advisor-conversations"),
};

/** While Claude writes a review again, the latest is asked for every few seconds. */
export const REWRITE_POLL_MS = 3000;

export function useLatestBriefing(kind: MaybeRefOrGetter<BriefingKind>, waiting: MaybeRefOrGetter<boolean> = false) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => briefingKeys.latest(cid.value, toValue(kind))),
    queryFn: ({ signal }) => briefingsApi.latest(cid.value, toValue(kind), signal),
    enabled: computed(() => cid.value > 0),
    staleTime: 30_000,
    refetchInterval: () => (toValue(waiting) ? REWRITE_POLL_MS : false),
  });
}

export function useBriefings(kind: MaybeRefOrGetter<BriefingKind>) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => briefingKeys.list(cid.value, toValue(kind))),
    queryFn: ({ signal }) => briefingsApi.list(cid.value, toValue(kind), signal),
    enabled: computed(() => cid.value > 0),
    staleTime: 60_000,
  });
}

/** One review of the history (null: none chosen, the latest shows). */
export function useBriefing(id: MaybeRefOrGetter<number | null>) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => briefingKeys.one(cid.value, toValue(id) ?? 0)),
    queryFn: ({ signal }) => briefingsApi.one(cid.value, toValue(id)!, signal),
    enabled: computed(() => cid.value > 0 && !!toValue(id)),
    staleTime: 5 * 60_000,
  });
}

export function useBriefingSettings(enabled: MaybeRefOrGetter<boolean> = true) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => briefingKeys.settings(cid.value)),
    queryFn: ({ signal }) => briefingsApi.settings(cid.value, signal),
    enabled: computed(() => cid.value > 0 && toValue(enabled)),
    staleTime: 60_000,
  });
}

/** One setting saved at once; the page's next times follow. */
export function useSaveBriefingSettings() {
  const cid = useCompanyId();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (patch: Partial<BriefingSettings>) => briefingsApi.saveSettings(cid.value, patch),
    onSuccess: (row) => {
      client.setQueryData(briefingKeys.settings(cid.value), row);
      void client.invalidateQueries({ queryKey: qk(cid.value, MODULE, "briefing-latest") });
      void client.invalidateQueries({ queryKey: qk(cid.value, MODULE, "agent", { key: "advisor" }) });
    },
  });
}

export function useAdvisorConversations(enabled: MaybeRefOrGetter<boolean>) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => briefingKeys.conversations(cid.value)),
    queryFn: ({ signal }) => briefingsApi.conversations(cid.value, signal),
    enabled: computed(() => cid.value > 0 && toValue(enabled)),
    staleTime: 30_000,
  });
}
