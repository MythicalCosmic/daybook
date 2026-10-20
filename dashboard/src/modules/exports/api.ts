/**
 * Exports (plan §4.2, apps.exports): the person's own files of the last 7 days (`exports/`), what
 * they may export here (`exports/kinds/`), asking for a new one (`POST exports/` → 202 `{id}`) and
 * one export's state with a fresh signed link (`exports/{id}/`). N adds schedules in Wave 3.
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import { computed, toValue, type MaybeRefOrGetter } from "vue";

import { http, ownerPath } from "@/api/http";
import { moduleKey, qk } from "@/api/keys";
import type { ExportJob, Exporter, Page } from "@/api/types";
import { exportsApi, type ExportRequest } from "@/lib/useExport";
import { useCompanyStore } from "@/stores/company";

export const MODULE = "exports";
/** How often the list refreshes while a file is still being built. */
export const BUILDING_POLL_MS = 2000;

export function listExports(companyId: number, params: { page?: number; page_size?: number } = {}, signal?: AbortSignal): Promise<Page<ExportJob>> {
  return http.get<Page<ExportJob>>(ownerPath(companyId, "exports/"), { page: params.page ?? 1, page_size: params.page_size }, { signal });
}

export function listExporters(companyId: number, signal?: AbortSignal): Promise<Exporter[]> {
  return http.get<Exporter[]>(ownerPath(companyId, "exports/kinds/"), undefined, { signal });
}

export function createExport(companyId: number, request: ExportRequest): Promise<{ id: number }> {
  return exportsApi(companyId).create(request);
}

export function getExport(companyId: number, id: number, signal?: AbortSignal): Promise<ExportJob> {
  return exportsApi(companyId).get(id, signal);
}

export const exportKeys = {
  all: (companyId: number) => moduleKey(companyId, MODULE),
  list: (companyId: number, params: { page: number; page_size: number }) => qk(companyId, MODULE, "list", { ...params }),
  kinds: (companyId: number) => qk(companyId, MODULE, "kinds"),
};

export const isBuilding = (job: Pick<ExportJob, "status">) => job.status === "pending" || job.status === "running";

function useCompanyId() {
  const company = useCompanyStore();
  return computed(() => company.currentId ?? 0);
}

/** The list; while any file is still being built it refreshes every two seconds. */
export function useExports(params: MaybeRefOrGetter<{ page: number; page_size: number }>) {
  const companyId = useCompanyId();
  return useQuery({
    queryKey: computed(() => exportKeys.list(companyId.value, toValue(params))),
    queryFn: ({ signal }) => listExports(companyId.value, toValue(params), signal),
    enabled: computed(() => companyId.value > 0),
    placeholderData: keepPreviousData,
    refetchInterval: (query) => (query.state.data?.results.some(isBuilding) ? BUILDING_POLL_MS : false),
  });
}

export function useExporters() {
  const companyId = useCompanyId();
  return useQuery({
    queryKey: computed(() => exportKeys.kinds(companyId.value)),
    queryFn: ({ signal }) => listExporters(companyId.value, signal),
    enabled: computed(() => companyId.value > 0),
    staleTime: 5 * 60_000,
  });
}

export function useCreateExport() {
  const client = useQueryClient();
  const companyId = useCompanyId();
  return useMutation({
    mutationFn: (request: ExportRequest) => createExport(companyId.value, request),
    onSettled: () => client.invalidateQueries({ queryKey: exportKeys.all(companyId.value) }),
  });
}
