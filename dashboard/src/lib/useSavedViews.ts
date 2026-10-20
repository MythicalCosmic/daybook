/**
 * Saved views (plan §4.2: CRUD `saved-views/?module=`): the person's own views of a list and the
 * ones colleagues shared, plus the `overview` layout. Built-in views are the page's own constants;
 * this composable only talks to the server for the saved ones.
 *
 *   const views = useSavedViews("tasks");
 *   views.list.data.value  → SavedView[]
 *   await views.create.mutateAsync({ name, params: filters.params.value, shared: false });
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import { computed } from "vue";

import { http, ownerPath } from "@/api/http";
import { qk } from "@/api/keys";
import type { Page } from "@/api/types";
import { useCompanyStore } from "@/stores/company";

export interface SavedView {
  id: number | string;
  module: string;
  name: string;
  /** Filters, ordering, columns, or a layout: whatever the page stores. */
  params: Record<string, unknown>;
  shared: boolean;
  /** The caller owns it (may rename, share and delete). */
  mine: boolean;
  /** Page constants, never sent to the server. */
  builtin?: boolean;
  created_at?: string;
}

export interface SavedViewInput {
  name: string;
  params: Record<string, unknown>;
  shared?: boolean;
}

function rows<T>(body: Page<T> | T[]): T[] {
  return Array.isArray(body) ? body : body.results;
}

export function savedViewsApi(companyId: number) {
  return {
    list: (module: string) => http.get<Page<SavedView> | SavedView[]>(ownerPath(companyId, "saved-views/"), { module }).then(rows),
    create: (module: string, input: SavedViewInput) => http.post<SavedView>(ownerPath(companyId, "saved-views/"), { module, shared: false, ...input }),
    update: (id: SavedView["id"], input: Partial<SavedViewInput>) => http.patch<SavedView>(ownerPath(companyId, `saved-views/${id}/`), input),
    remove: (id: SavedView["id"]) => http.delete(ownerPath(companyId, `saved-views/${id}/`)),
  };
}

export function useSavedViews(module: string) {
  const company = useCompanyStore();
  const client = useQueryClient();
  const companyId = computed(() => company.currentId ?? 0);
  const key = computed(() => qk(companyId.value, "shell", "saved-views", { module }));
  const api = computed(() => savedViewsApi(companyId.value));
  const refresh = () => client.invalidateQueries({ queryKey: key.value });

  const list = useQuery({
    queryKey: key,
    queryFn: () => api.value.list(module),
    enabled: computed(() => companyId.value > 0),
    staleTime: 5 * 60_000,
  });

  const create = useMutation({ mutationFn: (input: SavedViewInput) => api.value.create(module, input), onSettled: refresh });
  const update = useMutation({
    mutationFn: ({ id, ...input }: Partial<SavedViewInput> & { id: SavedView["id"] }) => api.value.update(id, input),
    onSettled: refresh,
  });
  const remove = useMutation({
    mutationFn: (id: SavedView["id"]) => api.value.remove(id),
    onMutate: async (id) => {
      await client.cancelQueries({ queryKey: key.value });
      const previous = client.getQueryData<SavedView[]>(key.value);
      if (previous) client.setQueryData(key.value, previous.filter((view) => view.id !== id));
      return { previous };
    },
    onError: (_error, _id, context) => context?.previous && client.setQueryData(key.value, context.previous),
    onSettled: refresh,
  });

  return { list, create, update, remove };
}

/** Whether the current params differ from a view's (key order and empty values don't count). */
export function paramsDiffer(current: Record<string, unknown>, saved: Record<string, unknown>): boolean {
  const clean = (params: Record<string, unknown>) =>
    JSON.stringify(
      Object.keys(params)
        .filter((k) => {
          const v = params[k];
          return v !== undefined && v !== null && v !== "" && !(Array.isArray(v) && v.length === 0);
        })
        .sort()
        .map((k) => [k, Array.isArray(params[k]) ? [...(params[k] as unknown[])].map(String).sort() : String(params[k])]),
    );
  return clean(current) !== clean(saved);
}
