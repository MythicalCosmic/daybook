/**
 * The knowledge base's endpoints (`/api/v1/owner/companies/{cid}/knowledge/…`) as typed functions,
 * and the vue-query helpers the pages use. Keys start with `[companyId, "knowledge"]`, so the
 * `knowledge.pages` pulse refreshes everything here, and switching company never leaks a page.
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import { computed, toValue, type MaybeRefOrGetter } from "vue";

import { http, ownerPath } from "@/api/http";
import { moduleKey, qk } from "@/api/keys";
import type { Page } from "@/api/types";
import { useCompanyStore } from "@/stores/company";

import type {
  KbRef,
  KnowledgeSettings,
  Overview,
  PageCreateInput,
  PageDetail,
  PageLink,
  PageListParams,
  PageRow,
  PageSaveInput,
  PageVersion,
  PageVersionDetail,
  Readers,
  ReaderStatus,
  Space,
  SpaceInput,
  Target,
  TreeNodeData,
  UploadedImage,
  LinkTarget,
} from "./types";

export const MODULE = "knowledge";
const path = (companyId: number, rest: string) => ownerPath(companyId, `knowledge/${rest}`);

// ─── Endpoints ──────────────────────────────────────────────────────────────

export const knowledgeApi = {
  overview: (cid: number, signal?: AbortSignal) => http.get<Overview>(path(cid, "overview/"), undefined, { signal }),
  spaces: (cid: number, archived = false, signal?: AbortSignal) =>
    http.get<Space[]>(path(cid, "spaces/"), archived ? { archived: true } : undefined, { signal }),
  createSpace: (cid: number, input: SpaceInput) => http.post<Space>(path(cid, "spaces/"), input),
  updateSpace: (cid: number, id: number, input: Partial<SpaceInput>) => http.patch<Space>(path(cid, `spaces/${id}/`), input),
  archiveSpace: (cid: number, id: number) => http.post<Space>(path(cid, `spaces/${id}/archive/`)),
  restoreSpace: (cid: number, id: number) => http.post<Space>(path(cid, `spaces/${id}/restore/`)),
  reorderSpaces: (cid: number, ids: number[]) => http.post<void>(path(cid, "spaces/reorder/"), { ids }),
  tree: (cid: number, spaceId: number, signal?: AbortSignal) => http.get<TreeNodeData[]>(path(cid, `spaces/${spaceId}/tree/`), undefined, { signal }),
  pages: (cid: number, params: PageListParams, signal?: AbortSignal) =>
    http.get<Page<PageRow>>(path(cid, "pages/"), { ...params, require_ack: params.require_ack ? true : undefined }, { signal }),
  page: (cid: number, id: number, signal?: AbortSignal) => http.get<PageDetail>(path(cid, `pages/${id}/`), undefined, { signal }),
  createPage: (cid: number, input: PageCreateInput) => http.post<PageDetail>(path(cid, "pages/"), input),
  savePage: (cid: number, id: number, input: PageSaveInput) => http.patch<PageDetail>(path(cid, `pages/${id}/`), input),
  publish: (cid: number, id: number, notify = true) => http.post<PageDetail>(path(cid, `pages/${id}/publish/`), { notify }),
  unpublish: (cid: number, id: number) => http.post<PageDetail>(path(cid, `pages/${id}/unpublish/`)),
  move: (cid: number, id: number, body: { space?: number | null; parent: number | null; index: number }) =>
    http.post<PageDetail>(path(cid, `pages/${id}/move/`), body),
  archive: (cid: number, id: number) => http.post<PageDetail>(path(cid, `pages/${id}/archive/`)),
  restore: (cid: number, id: number) => http.post<PageDetail>(path(cid, `pages/${id}/restore/`)),
  ack: (cid: number, id: number) => http.post<{ version: number; at: string }>(path(cid, `pages/${id}/ack/`)),
  versions: (cid: number, id: number, signal?: AbortSignal) => http.get<PageVersion[]>(path(cid, `pages/${id}/versions/`), undefined, { signal }),
  version: (cid: number, id: number, version: number, signal?: AbortSignal) =>
    http.get<PageVersionDetail>(path(cid, `pages/${id}/versions/${version}/`), undefined, { signal }),
  restoreVersion: (cid: number, id: number, version: number) => http.post<PageDetail>(path(cid, `pages/${id}/versions/${version}/restore/`)),
  readers: (cid: number, id: number, status?: ReaderStatus | null, signal?: AbortSignal) =>
    http.get<Readers>(path(cid, `pages/${id}/readers/`), { status: status ?? undefined }, { signal }),
  remind: (cid: number, id: number) => http.post<{ reminded: number }>(path(cid, `pages/${id}/remind/`)),
  link: (cid: number, id: number, target_type: LinkTarget, target_id: number) =>
    http.post<PageLink>(path(cid, `pages/${id}/links/`), { target_type, target_id }),
  unlink: (cid: number, linkId: number) => http.delete(path(cid, `links/${linkId}/`)),
  linked: (cid: number, target_type: LinkTarget, target_id: number, signal?: AbortSignal) =>
    http.get<PageLink[]>(path(cid, "pages/linked/"), { target_type, target_id }, { signal }),
  targets: (cid: number, q: string, signal?: AbortSignal) => http.get<Target[]>(path(cid, "link-targets/"), { q }, { signal }),
  positions: (cid: number, signal?: AbortSignal) => http.get<KbRef[]>(path(cid, "positions/"), undefined, { signal }),
  upload: (cid: number, file: File, pageId?: number | null) => {
    const form = new FormData();
    form.append("file", file);
    if (pageId) form.append("page", String(pageId));
    return http.form<UploadedImage>(path(cid, "images/"), form);
  },
  settings: (cid: number, signal?: AbortSignal) => http.get<KnowledgeSettings>(path(cid, "settings/"), undefined, { signal }),
  saveSettings: (cid: number, input: Partial<KnowledgeSettings>) => http.patch<KnowledgeSettings>(path(cid, "settings/"), input),
};

// ─── Keys ───────────────────────────────────────────────────────────────────

export const kbKeys = {
  all: (cid: number) => moduleKey(cid, MODULE),
  overview: (cid: number) => qk(cid, MODULE, "overview"),
  spaces: (cid: number, archived = false) => qk(cid, MODULE, "spaces", { archived }),
  tree: (cid: number, spaceId: number) => qk(cid, MODULE, "tree", { spaceId }),
  trees: (cid: number) => [cid, MODULE, "tree"] as const,
  pages: (cid: number, params: PageListParams) => qk(cid, MODULE, "pages", { ...params }),
  page: (cid: number, id: number) => qk(cid, MODULE, "page", { id }),
  versions: (cid: number, id: number) => qk(cid, MODULE, "versions", { id }),
  version: (cid: number, id: number, version: number) => qk(cid, MODULE, "version", { id, version }),
  readers: (cid: number, id: number) => qk(cid, MODULE, "readers", { id }),
  linked: (cid: number, type: LinkTarget, id: number) => qk(cid, MODULE, "linked", { type, id }),
  targets: (cid: number, q: string) => qk(cid, MODULE, "targets", { q }),
  positions: (cid: number) => qk(cid, MODULE, "positions"),
  settings: (cid: number) => qk(cid, MODULE, "settings"),
};

// ─── Queries ────────────────────────────────────────────────────────────────

export function useCompanyId() {
  const company = useCompanyStore();
  return computed(() => company.currentId ?? 0);
}

export function useOverview() {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => kbKeys.overview(cid.value)),
    queryFn: ({ signal }) => knowledgeApi.overview(cid.value, signal),
    enabled: computed(() => cid.value > 0),
    staleTime: 15_000,
  });
}

export function useSpaces(archived: MaybeRefOrGetter<boolean> = false, enabled: MaybeRefOrGetter<boolean> = true) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => kbKeys.spaces(cid.value, toValue(archived))),
    queryFn: ({ signal }) => knowledgeApi.spaces(cid.value, toValue(archived), signal),
    enabled: computed(() => cid.value > 0 && toValue(enabled)),
    staleTime: 30_000,
  });
}

export function useTree(spaceId: MaybeRefOrGetter<number | null>) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => kbKeys.tree(cid.value, toValue(spaceId) ?? 0)),
    queryFn: ({ signal }) => knowledgeApi.tree(cid.value, toValue(spaceId)!, signal),
    enabled: computed(() => cid.value > 0 && !!toValue(spaceId)),
    staleTime: 30_000,
  });
}

export function usePages(params: MaybeRefOrGetter<PageListParams>, enabled: MaybeRefOrGetter<boolean> = true) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => kbKeys.pages(cid.value, toValue(params))),
    queryFn: ({ signal }) => knowledgeApi.pages(cid.value, toValue(params), signal),
    enabled: computed(() => cid.value > 0 && toValue(enabled)),
    placeholderData: keepPreviousData,
    staleTime: 15_000,
  });
}

export function usePage(id: MaybeRefOrGetter<number | null>) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => kbKeys.page(cid.value, toValue(id) ?? 0)),
    queryFn: ({ signal }) => knowledgeApi.page(cid.value, toValue(id)!, signal),
    enabled: computed(() => cid.value > 0 && !!toValue(id)),
    staleTime: 15_000,
  });
}

export function useVersions(id: MaybeRefOrGetter<number | null>, enabled: MaybeRefOrGetter<boolean> = true) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => kbKeys.versions(cid.value, toValue(id) ?? 0)),
    queryFn: ({ signal }) => knowledgeApi.versions(cid.value, toValue(id)!, signal),
    enabled: computed(() => cid.value > 0 && !!toValue(id) && toValue(enabled)),
  });
}

export function useVersion(id: MaybeRefOrGetter<number | null>, version: MaybeRefOrGetter<number | null>) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => kbKeys.version(cid.value, toValue(id) ?? 0, toValue(version) ?? 0)),
    queryFn: ({ signal }) => knowledgeApi.version(cid.value, toValue(id)!, toValue(version)!, signal),
    enabled: computed(() => cid.value > 0 && !!toValue(id) && !!toValue(version)),
  });
}

export function useReaders(id: MaybeRefOrGetter<number | null>, enabled: MaybeRefOrGetter<boolean> = true) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => kbKeys.readers(cid.value, toValue(id) ?? 0)),
    queryFn: ({ signal }) => knowledgeApi.readers(cid.value, toValue(id)!, null, signal),
    enabled: computed(() => cid.value > 0 && !!toValue(id) && toValue(enabled)),
    staleTime: 15_000,
  });
}

export function useLinked(type: MaybeRefOrGetter<LinkTarget | null>, id: MaybeRefOrGetter<number | null>) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => kbKeys.linked(cid.value, toValue(type) ?? "task", toValue(id) ?? 0)),
    queryFn: ({ signal }) => knowledgeApi.linked(cid.value, toValue(type)!, toValue(id)!, signal),
    enabled: computed(() => cid.value > 0 && !!toValue(type) && !!toValue(id)),
    staleTime: 60_000,
  });
}

export function useTargets(q: MaybeRefOrGetter<string>, enabled: MaybeRefOrGetter<boolean>) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => kbKeys.targets(cid.value, toValue(q))),
    queryFn: ({ signal }) => knowledgeApi.targets(cid.value, toValue(q), signal),
    enabled: computed(() => cid.value > 0 && toValue(enabled)),
    placeholderData: keepPreviousData,
  });
}

export function usePositions(enabled: MaybeRefOrGetter<boolean>) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => kbKeys.positions(cid.value)),
    queryFn: ({ signal }) => knowledgeApi.positions(cid.value, signal),
    enabled: computed(() => cid.value > 0 && toValue(enabled)),
    staleTime: 5 * 60_000,
  });
}

export function useKnowledgeSettings() {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => kbKeys.settings(cid.value)),
    queryFn: ({ signal }) => knowledgeApi.settings(cid.value, signal),
    enabled: computed(() => cid.value > 0),
  });
}

// ─── Mutations ──────────────────────────────────────────────────────────────

/** Everything the knowledge base shows, refreshed after a change. */
export function useRefresh() {
  const client = useQueryClient();
  const cid = useCompanyId();
  return () => client.invalidateQueries({ queryKey: kbKeys.all(cid.value) });
}

/** A page answer replaces the cached page at once (the editor and the view agree). */
export function usePutPage() {
  const client = useQueryClient();
  const cid = useCompanyId();
  return (page: PageDetail) => client.setQueryData(kbKeys.page(cid.value, page.id), page);
}

/** "I've read it": the page shows as read at once and rolls back if the server refuses. */
export function useAck() {
  const client = useQueryClient();
  const cid = useCompanyId();
  const refresh = useRefresh();
  return useMutation({
    mutationFn: (id: number) => knowledgeApi.ack(cid.value, id),
    onMutate: async (id) => {
      const key = kbKeys.page(cid.value, id);
      await client.cancelQueries({ queryKey: key });
      const before = client.getQueryData<PageDetail>(key);
      if (before) client.setQueryData<PageDetail>(key, { ...before, my_ack: { version: before.version, at: new Date().toISOString(), current: true } });
      return { before, key };
    },
    onError: (_error, _id, context) => {
      if (context?.before) client.setQueryData(context.key, context.before);
    },
    onSettled: () => void refresh(),
  });
}
