/**
 * The attendance endpoints (`/companies/<id>/attendance/…`, backend/apps/attendance/urls.py) as
 * react-query hooks. Every key starts with ["attendance", company], so one invalidation after a
 * check-in, a request or an answer refreshes the card, the month, the shifts and the swaps.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, apiForm } from "../../api/client";
import type { AttendanceRecord, Candidate, CheckResult, Correction, MyDay, MyMonth, MySwaps, OpenShift, Shift, Swap } from "./types";

export const attendanceKeys = {
  all: (company: number) => ["attendance", company] as const,
  today: (company: number) => ["attendance", company, "today"] as const,
  month: (company: number, month: string) => ["attendance", company, "month", month] as const,
  shifts: (company: number) => ["attendance", company, "shifts"] as const,
  record: (company: number, id: number) => ["attendance", company, "record", id] as const,
  corrections: (company: number) => ["attendance", company, "corrections"] as const,
  swaps: (company: number) => ["attendance", company, "swaps"] as const,
  openShifts: (company: number) => ["attendance", company, "openShifts"] as const,
  candidates: (company: number, shift: number) => ["attendance", company, "candidates", shift] as const,
};

const base = (company: number) => `/companies/${company}/attendance`;

/** The check-in card: refreshed every minute so "late by" and "so far" keep up. */
export function useToday(company: number, enabled = true) {
  return useQuery({
    queryKey: attendanceKeys.today(company),
    queryFn: () => api<MyDay>(`${base(company)}/today/`),
    refetchInterval: 60_000,
    enabled,
  });
}

export function useMonth(company: number, month: string) {
  return useQuery({
    queryKey: attendanceKeys.month(company, month),
    queryFn: () => api<MyMonth>(`${base(company)}/?month=${month}`),
    placeholderData: (previous) => previous,
  });
}

export function useMyShifts(company: number) {
  return useQuery({ queryKey: attendanceKeys.shifts(company), queryFn: () => api<Shift[]>(`${base(company)}/shifts/`) });
}

export function useRecord(company: number, id: number | null) {
  return useQuery({
    queryKey: attendanceKeys.record(company, id ?? 0),
    queryFn: () => api<AttendanceRecord>(`${base(company)}/records/${id}/`),
    enabled: id !== null,
  });
}

export function useCorrections(company: number) {
  return useQuery({ queryKey: attendanceKeys.corrections(company), queryFn: () => api<Correction[]>(`${base(company)}/corrections/`) });
}

export function useSwaps(company: number) {
  return useQuery({ queryKey: attendanceKeys.swaps(company), queryFn: () => api<MySwaps>(`${base(company)}/swaps/`) });
}

export function useOpenShifts(company: number) {
  return useQuery({ queryKey: attendanceKeys.openShifts(company), queryFn: () => api<OpenShift[]>(`${base(company)}/open-shifts/`) });
}

export function useCandidates(company: number, shift: number) {
  return useQuery({
    queryKey: attendanceKeys.candidates(company, shift),
    queryFn: () => api<Candidate[]>(`${base(company)}/swaps/candidates/?shift_id=${shift}`),
  });
}

/** Where the tap happened. Coordinates go with six decimals (about 10 cm), as the server stores them. */
export type Tap = { lat: number; lng: number; accuracy: number | null } | null;

const coordinate = (value: number) => value.toFixed(6);

function tapFields(tap: Tap) {
  if (!tap) return {};
  return { lat: coordinate(tap.lat), lng: coordinate(tap.lng), accuracy: tap.accuracy === null ? null : Math.round(tap.accuracy) };
}

function useInvalidate(company: number) {
  const client = useQueryClient();
  return () => client.invalidateQueries({ queryKey: attendanceKeys.all(company) });
}

export function useCheck(company: number) {
  const invalidate = useInvalidate(company);
  return useMutation({
    mutationFn: ({ direction, tap, photo }: { direction: "in" | "out"; tap: Tap; photo?: File | null }) => {
      const path = `${base(company)}/check-${direction}/`;
      if (direction === "in" && photo) return apiForm<CheckResult>(path, { ...tapFields(tap), photo });
      return api<CheckResult>(path, { method: "POST", json: tapFields(tap) });
    },
    onSettled: invalidate,
  });
}

export type CorrectionDraft = {
  date: string;
  check_in_at: string | null;
  check_out_at: string | null;
  record_id: number | null;
  reason: string;
};

export function useRequestCorrection(company: number) {
  const invalidate = useInvalidate(company);
  return useMutation({
    mutationFn: (draft: CorrectionDraft) => api<Correction>(`${base(company)}/corrections/`, { method: "POST", json: draft }),
    onSuccess: invalidate,
  });
}

export type SwapDraft = {
  shift_id: number;
  kind: "cover" | "swap";
  other_shift_id: number | null;
  target_id: number | null;
  note: string;
};

export function useRequestSwap(company: number) {
  const invalidate = useInvalidate(company);
  return useMutation({
    mutationFn: (draft: SwapDraft) => api<Swap>(`${base(company)}/swaps/`, { method: "POST", json: draft }),
    onSuccess: invalidate,
  });
}

export function useSwapAction(company: number) {
  const invalidate = useInvalidate(company);
  return useMutation({
    mutationFn: ({ id, verb }: { id: number; verb: "accept" | "decline" | "cancel" }) =>
      api<Swap>(`${base(company)}/swaps/${id}/${verb}/`, { method: "POST" }),
    onSettled: invalidate,
  });
}

export function useClaim(company: number) {
  const invalidate = useInvalidate(company);
  return useMutation({
    mutationFn: (shift: number) => api<Swap>(`${base(company)}/open-shifts/${shift}/claim/`, { method: "POST" }),
    onSettled: invalidate,
  });
}
