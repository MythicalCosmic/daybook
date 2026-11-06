/**
 * What the person holds of the company's equipment (`/companies/<id>/assets/mine/…`,
 * backend/apps/assets/api.py) as react-query hooks. Confirming says "I have it, in the state
 * written down"; values are never sent here.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../../api/client";

export interface MineItem {
  id: number;
  asset_id: number;
  number: string;
  name: string;
  model: string;
  serial: string;
  category: string;
  icon: string;
  branch: string | null;
  issued_on: string;
  condition: string;
  note: string;
  acknowledged_at: string | null;
  photo_url: string | null;
}

export const mineKeys = { list: (company: number) => ["assets", company, "mine"] as const };

const base = (company: number) => `/companies/${company}/assets/mine`;

export function useMine(company: number, enabled = true) {
  return useQuery({ queryKey: mineKeys.list(company), queryFn: () => api<MineItem[]>(`${base(company)}/`), staleTime: 60_000, enabled });
}

/** "Qabul qildim": I have it. */
export function useAcknowledge(company: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api<MineItem>(`${base(company)}/${id}/acknowledge/`, { method: "POST" }),
    onSuccess: (item) => client.setQueryData<MineItem[]>(mineKeys.list(company), (rows) => rows?.map((row) => (row.id === item.id ? item : row))),
  });
}

export const toConfirm = (rows: MineItem[] | undefined): MineItem[] => (rows ?? []).filter((row) => !row.acknowledged_at);
