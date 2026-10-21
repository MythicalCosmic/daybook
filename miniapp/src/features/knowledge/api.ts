/**
 * The knowledge base endpoints of the mini app (`/api/v1/companies/{id}/knowledge/…`), with types
 * written by hand next to them (the generated schema is regenerated only at integration).
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../../api/client";

export type KbSpace = {
  id: number;
  name: string;
  icon: string;
  description: string;
  audience_all: boolean;
  positions: { id: number; name: string }[];
  counts: { pages: number };
};

export type KbPageRow = {
  id: number;
  title: string;
  emoji: string;
  space: { id: number; name: string; icon: string };
  parent_id: number | null;
  require_ack: boolean;
  version: number;
  updated_at: string;
  updated_by: { id: number; name: string } | null;
  excerpt: string;
};

export type KbTreeNode = { id: number; title: string; emoji: string; require_ack: boolean; children: KbTreeNode[] };

export type KbPage = KbPageRow & {
  body: string;
  ack_version: number;
  breadcrumbs: { id: number; title: string; emoji: string }[];
  children: { id: number; title: string; emoji: string }[];
  my_ack: { version: number; at: string; current: boolean } | null;
};

export type KbHome = { spaces: KbSpace[]; to_read: KbPageRow[]; recent: KbPageRow[] };

const base = (company: number) => `/companies/${company}/knowledge`;

export const kbKeys = {
  all: (company: number) => ["knowledge", company] as const,
  home: (company: number) => ["knowledge", company, "home"] as const,
  space: (company: number, id: number) => ["knowledge", company, "space", id] as const,
  page: (company: number, id: number) => ["knowledge", company, "page", id] as const,
  search: (company: number, q: string) => ["knowledge", company, "search", q] as const,
};

export function useKbHome(company: number, enabled = true) {
  return useQuery({ queryKey: kbKeys.home(company), queryFn: () => api<KbHome>(`${base(company)}/`), enabled, staleTime: 30_000 });
}

export function useKbSpace(company: number, id: number) {
  return useQuery({
    queryKey: kbKeys.space(company, id),
    queryFn: () => api<{ space: KbSpace; pages: KbTreeNode[] }>(`${base(company)}/spaces/${id}/`),
  });
}

export function useKbPage(company: number, id: number) {
  return useQuery({ queryKey: kbKeys.page(company, id), queryFn: () => api<KbPage>(`${base(company)}/pages/${id}/`) });
}

export function useKbSearch(company: number, q: string) {
  const text = q.trim();
  return useQuery({
    queryKey: kbKeys.search(company, text),
    queryFn: () => api<KbPageRow[]>(`${base(company)}/search/?q=${encodeURIComponent(text)}`),
    enabled: text.length >= 2,
    placeholderData: (previous) => previous,
  });
}

/** "I've read it": the page shows as read at once; it goes back if the server refuses. */
export function useAcknowledge(company: number, id: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => api<{ version: number; at: string }>(`${base(company)}/pages/${id}/ack/`, { method: "POST" }),
    onMutate: async () => {
      const key = kbKeys.page(company, id);
      await client.cancelQueries({ queryKey: key });
      const before = client.getQueryData<KbPage>(key);
      if (before) client.setQueryData<KbPage>(key, { ...before, my_ack: { version: before.version, at: new Date().toISOString(), current: true } });
      return { before };
    },
    onError: (_error, _vars, context) => {
      if (context?.before) client.setQueryData(kbKeys.page(company, id), context.before);
    },
    onSettled: () => client.invalidateQueries({ queryKey: kbKeys.all(company) }),
  });
}

/** Pages a tree holds, top to bottom, with their depth. */
export function flattenTree(nodes: readonly KbTreeNode[], depth = 0): { node: KbTreeNode; depth: number }[] {
  return nodes.flatMap((node) => [{ node, depth }, ...flattenTree(node.children, depth + 1)]);
}
