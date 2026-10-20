/**
 * Saved views (plan §4.2: CRUD `saved-views/?module=`): the person's own views of a list and the
 * ones colleagues shared, plus the `overview` layout. Built-in views are the page's own constants;
 * this composable only talks to the server for the saved ones. Only your own views can be changed
 * or deleted (the server answers 404 for anyone else's).
 *
 *   const views = useSavedViews("tasks");
 *   const tabs = computed(() => [...builtins, ...views.tabs.value]);       // for SavedViewsTabs
 *   await views.create.mutateAsync({ name, state: filters.params.value, is_shared: false });
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import { computed } from "vue";

import { http, ownerPath } from "@/api/http";
import { qk } from "@/api/keys";
import type { PersonRef } from "@/api/types";
import { useCompanyStore } from "@/stores/company";

/** One row of `GET saved-views/` (apps.console.owner_api.SavedViewSerializer). */
export interface SavedView {
  id: number;
  module: string;
  name: string;
  /** Filters, ordering, columns, or a layout: whatever the page stores. */
  state: Record<string, unknown>;
  is_shared: boolean;
  order: number;
  owner: PersonRef;
  /** The caller owns it (may rename, share and delete). */
  is_mine: boolean;
}

export interface SavedViewInput {
  name: string;
  state: Record<string, unknown>;
  is_shared?: boolean;
  order?: number;
}

/** What SavedViewsTabs shows for a view (built-in views are written in this shape directly). */
export interface SavedViewTab {
  id: number | string;
  name: string;
  shared?: boolean;
  mine?: boolean;
  builtin?: boolean;
  count?: number;
}

export function savedViewTab(view: SavedView): SavedViewTab {
  return { id: view.id, name: view.name, shared: view.is_shared, mine: view.is_mine };
}

export function savedViewsApi(companyId: number) {
  return {
    list: (module: string) => http.get<SavedView[]>(ownerPath(companyId, "saved-views/"), { module }),
    create: (module: string, input: SavedViewInput) => http.post<SavedView>(ownerPath(companyId, "saved-views/"), { module, is_shared: false, ...input }),
    update: (id: number, input: Partial<SavedViewInput>) => http.patch<SavedView>(ownerPath(companyId, `saved-views/${id}/`), input),
    remove: (id: number) => http.delete(ownerPath(companyId, `saved-views/${id}/`)),
  };
}

export function useSavedViews(module: string) {
  const company = useCompanyStore();
  const client = useQueryClient();
  const companyId = computed(() => company.currentId ?? 0);
  // The shell refetches these when the `console.saved_views` pulse key moves (a colleague shared one).
  const key = computed(() => qk(companyId.value, "shell", "saved-views", { module }));
  const api = computed(() => savedViewsApi(companyId.value));
  const refresh = () => client.invalidateQueries({ queryKey: key.value });

  const list = useQuery({
    queryKey: key,
    queryFn: () => api.value.list(module),
    enabled: computed(() => companyId.value > 0),
    staleTime: 5 * 60_000,
  });
  const tabs = computed<SavedViewTab[]>(() => (list.data.value ?? []).map(savedViewTab));
  const find = (id: SavedViewTab["id"]) => (list.data.value ?? []).find((view) => view.id === id);

  const create = useMutation({ mutationFn: (input: SavedViewInput) => api.value.create(module, input), onSettled: refresh });
  const update = useMutation({
    mutationFn: ({ id, ...input }: Partial<SavedViewInput> & { id: number }) => api.value.update(id, input),
    onSettled: refresh,
  });
  const remove = useMutation({
    mutationFn: (id: number) => api.value.remove(id),
    onMutate: async (id) => {
      await client.cancelQueries({ queryKey: key.value });
      const previous = client.getQueryData<SavedView[]>(key.value);
      if (previous) client.setQueryData(key.value, previous.filter((view) => view.id !== id));
      return { previous };
    },
    onError: (_error, _id, context) => context?.previous && client.setQueryData(key.value, context.previous),
    onSettled: refresh,
  });

  return { list, tabs, find, create, update, remove };
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
