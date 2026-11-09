/**
 * The recognition endpoints of the mini app (`/api/v1/companies/{id}/recognition/…`,
 * docs/PLAN-LEARNING.md §13 R), with types written by hand next to them (the generated schema is
 * regenerated only at integration). Every key starts with ["recognition", company], so one
 * invalidation refreshes the chip, the achievements, the leaderboard and the feeds together.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../../api/client";

export type Tier = "bronze" | "silver" | "gold";

export type RecognitionLevel = {
  number: number;
  name: string;
  starts_at: number;
  next_at: number | null;
  /** The next level's name; null at the top. */
  next_name?: string | null;
};

export type EarnedBadge = {
  key: string;
  /** The topic id or the month ("2026-11") of a badge that comes again; else "". */
  ref: string;
  name: string;
  description: string;
  /** A lucide icon name. */
  icon: string;
  tier: Tier;
  awarded_at: string;
};

export type LockedBadge = { key: string; name: string; description: string; icon: string; tier: Tier };

export type HistoryRow = { id: number; points: number; reason: string; label: string; detail: string; at: string };

export type UnseenLevel = { type: "level"; number: number; name: string; starts_at: number; next_at: number | null };
export type UnseenBadge = { type: "badge" } & EarnedBadge;
export type Unseen = UnseenLevel | UnseenBadge;

export type Person = { id: number; name: string; avatar_url: string | null; position: string | null };

export type KudosBadge = "thanks" | "teamwork" | "fast" | "careful" | "helpful" | "star";

export type Kudos = {
  id: number;
  from: Person;
  to: Person;
  badge: KudosBadge;
  badge_label: string;
  message: string;
  task: { id: number; title: string } | null;
  at: string;
  seen: boolean;
  /** The viewer sent it. */
  mine: boolean;
};

export type RecognitionMe = {
  /** Points are on in the company (off: no chip, no levels). */
  enabled: boolean;
  points: number;
  week_points: number;
  level: RecognitionLevel;
  streak: number;
  best_streak: number;
  badges: EarnedBadge[];
  locked: LockedBadge[];
  recent: HistoryRow[];
  unseen: Unseen[];
  kudos_enabled: boolean;
  kudos_left: number;
  /** Thanks received today, newest first. */
  kudos_today: Kudos[];
  /** The person may open the leaderboard. */
  leaderboard: boolean;
};

export type Period = "week" | "month" | "all";
export type BoardScope = "company" | "branch";

export type BoardRow = { place: number; member: Person; points: number; level: { number: number; name: string } };

export type Leaderboard = {
  visible: boolean;
  period: Period;
  scope: BoardScope;
  start: string | null;
  end: string | null;
  rows: BoardRow[];
  me: { place: number | null; points: number };
};

export type Colleague = Person & { branch: string | null };
export type Colleagues = { per_day: number; left: number; results: Colleague[] };

export type SendKudos = { to: number; badge: KudosBadge; message: string; task?: number | null };

const base = (company: number) => `/companies/${company}/recognition`;

export const recognitionKeys = {
  all: (company: number) => ["recognition", company] as const,
  me: (company: number) => ["recognition", company, "me"] as const,
  board: (company: number, period: Period, scope: BoardScope) => ["recognition", company, "board", period, scope] as const,
  kudos: (company: number, box: "received" | "given") => ["recognition", company, "kudos", box] as const,
  colleagues: (company: number, q: string) => ["recognition", company, "colleagues", q] as const,
};

export function useRecognitionMe(company: number, enabled = true) {
  return useQuery({
    queryKey: recognitionKeys.me(company),
    queryFn: () => api<RecognitionMe>(`${base(company)}/me/`),
    enabled,
    staleTime: 30_000,
  });
}

export function useLeaderboard(company: number, period: Period, scope: BoardScope) {
  return useQuery({
    queryKey: recognitionKeys.board(company, period, scope),
    queryFn: () => api<Leaderboard>(`${base(company)}/leaderboard/?period=${period}&scope=${scope}`),
    staleTime: 30_000,
    placeholderData: (previous) => previous,
  });
}

export function useKudosBox(company: number, box: "received" | "given") {
  return useQuery({
    queryKey: recognitionKeys.kudos(company, box),
    queryFn: () => api<Kudos[]>(`${base(company)}/kudos/?box=${box}`),
    staleTime: 15_000,
  });
}

/** Colleagues to thank; `include` lists one more first (who thanked me, from another branch too). */
export function useColleagues(company: number, q: string, include: number | null = null) {
  const query = new URLSearchParams();
  if (q) query.set("q", q);
  if (include) query.set("include", String(include));
  const search = query.toString();
  return useQuery({
    queryKey: [...recognitionKeys.colleagues(company, q), include] as const,
    queryFn: () => api<Colleagues>(`${base(company)}/kudos/colleagues/${search ? `?${search}` : ""}`),
    staleTime: 60_000,
    placeholderData: (previous) => previous,
  });
}

export function useSendKudos(company: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: SendKudos) => api<Kudos>(`${base(company)}/kudos/`, { method: "POST", json: body }),
    onSuccess: () => void client.invalidateQueries({ queryKey: recognitionKeys.all(company) }),
  });
}

/** The app showed the new levels and badges (and, with `kudos`, the thanks received). */
export function useMarkSeen(company: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { kudos?: boolean } = {}) => api<void>(`${base(company)}/seen/`, { method: "POST", json: body }),
    onSuccess: () => void client.invalidateQueries({ queryKey: recognitionKeys.me(company) }),
  });
}
