/**
 * Data behind PersonPicker, PositionPicker and BranchPicker. People and positions are read once per
 * company and cached (a business has tens or a few hundred of them), so every picker can show the
 * names of already chosen ids and filter instantly. Keys live under the owning module ("people"),
 * so that module's pulse refreshes the pickers too.
 */
import { useQuery } from "@tanstack/vue-query";
import { computed, type ComputedRef } from "vue";

import { http, ownerPath } from "@/api/http";
import { qk } from "@/api/keys";
import type { BranchRef, Page } from "@/api/types";
import { useCompanyStore } from "@/stores/company";

import type { SelectOption } from "./options";

/** What a picker needs about a person. */
export interface PersonOption {
  id: number;
  name: string;
  photo_url?: string | null;
  /** Position or role shown under the name. */
  subtitle?: string;
  branch?: string | null;
}

export interface PositionOption {
  id: number;
  name: string;
  color?: string | null;
}

type Named = { name?: string | null } | string | null | undefined;

const nameOf = (value: Named): string | null => (typeof value === "string" ? value : (value?.name ?? null));

/** Reads a row of `GET people/` (package C) liberally: `full_name` or `name`, position as text or object. */
export function toPersonOption(row: Record<string, unknown>): PersonOption {
  const position = nameOf(row.position as Named);
  const branch = nameOf((row.home_branch ?? row.branch) as Named);
  return {
    id: Number(row.id),
    name: String(row.full_name ?? row.name ?? `#${String(row.id)}`),
    photo_url: (row.photo_url as string | null | undefined) ?? null,
    subtitle: [position, branch].filter(Boolean).join(" · ") || undefined,
    branch,
  };
}

function rows<T>(body: Page<T> | T[]): T[] {
  return Array.isArray(body) ? body : body.results;
}

export function useCompanyPeople(enabled: ComputedRef<boolean>, filters: ComputedRef<Record<string, string | number | boolean | readonly (string | number)[] | undefined>>) {
  const company = useCompanyStore();
  return useQuery({
    queryKey: computed(() => qk(company.currentId ?? 0, "people", "picker", filters.value)),
    queryFn: async ({ signal }) => {
      const body = await http.get<Page<Record<string, unknown>> | Array<Record<string, unknown>>>(
        ownerPath(company.currentId!, "people/"),
        { page_size: 500, ...filters.value },
        { signal },
      );
      return rows(body).map(toPersonOption);
    },
    enabled: computed(() => enabled.value && company.currentId !== null),
    staleTime: 5 * 60_000,
  });
}

export function useCompanyPositions(enabled: ComputedRef<boolean>) {
  const company = useCompanyStore();
  return useQuery({
    queryKey: computed(() => qk(company.currentId ?? 0, "people", "positions-picker")),
    queryFn: async ({ signal }) => {
      const body = await http.get<Page<PositionOption> | PositionOption[]>(ownerPath(company.currentId!, "positions/"), { page_size: 500 }, { signal });
      return rows(body).map((row) => ({ id: Number(row.id), name: row.name, color: row.color ?? null }));
    },
    enabled: computed(() => enabled.value && company.currentId !== null),
    staleTime: 10 * 60_000,
  });
}

/** Branches the caller may see in the current company (from `me`, no request). */
export function useScopedBranches(): ComputedRef<BranchRef[]> {
  const company = useCompanyStore();
  return computed(() => {
    const current = company.current;
    if (!current) return [];
    const scope = current.branch_scope;
    return scope === null ? current.branches : current.branches.filter((b) => scope.includes(b.id));
  });
}

export const personToOption = (person: PersonOption): SelectOption<number> => ({
  value: person.id,
  label: person.name,
  description: person.subtitle,
  avatar: { name: person.name, src: person.photo_url ?? null },
});

export const positionToOption = (position: PositionOption): SelectOption<number> => ({
  value: position.id,
  label: position.name,
  color: position.color ?? undefined,
});

export const branchToOption = (branch: BranchRef): SelectOption<number> => ({
  value: branch.id,
  label: branch.name,
  description: branch.code,
  keywords: [branch.code],
});
