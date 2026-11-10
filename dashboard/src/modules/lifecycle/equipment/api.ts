/**
 * Equipment's endpoints (`lifecycle/equipment/…`) as typed functions and vue-query hooks. Keys start
 * with `[companyId, "lifecycle"]`: the `lifecycle.equipment` pulse key (bumped by every change in
 * assets, a confirmation in the app included) refreshes them. A change also refreshes the people
 * pages (Person 360, the offboarding wizard), the asset register and payroll (a deduction).
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import { computed, toValue, type MaybeRefOrGetter } from "vue";

import { http, ownerPath } from "@/api/http";
import { qk } from "@/api/keys";
import { useCompanyId, useCompanyStore } from "@/stores/company";

import { MODULE } from "../api";
import type {
  AddItemsInput,
  CategoryInput,
  DeductionInput,
  EquipmentCategories,
  EquipmentPeople,
  EquipmentPersonPage,
  Holder,
  IssueInput,
  ReturnInput,
  StockItem,
} from "./types";

const path = (cid: number, rest: string) => ownerPath(cid, `lifecycle/${rest}`);

function form(values: Record<string, unknown>): FormData {
  const out = new FormData();
  for (const [key, value] of Object.entries(values)) {
    if (value === undefined || value === null || value === "") continue;
    if (Array.isArray(value)) for (const each of value) out.append(key, String(each));
    else if (value instanceof Blob) out.append(key, value);
    else out.append(key, String(value));
  }
  return out;
}

export const equipmentApi = {
  people: (cid: number, branch: number | null, signal?: AbortSignal) => http.get<EquipmentPeople>(path(cid, "equipment/"), branch ? { branch } : undefined, { signal }),
  items: (cid: number, status: "stock" | "out" | "all", signal?: AbortSignal) => http.get<StockItem[]>(path(cid, "equipment/items/"), { status }, { signal }),
  categories: (cid: number, signal?: AbortSignal) => http.get<EquipmentCategories>(path(cid, "equipment/categories/"), undefined, { signal }),
  person: (cid: number, memberId: number, signal?: AbortSignal) => http.get<EquipmentPersonPage>(path(cid, `people/${memberId}/equipment/`), undefined, { signal }),
  addCategory: (cid: number, input: CategoryInput) => http.post<EquipmentCategories>(path(cid, "equipment/categories/"), input),
  addItems: (cid: number, input: AddItemsInput) => http.post<{ items: StockItem[] }>(path(cid, "equipment/items/"), input),
  /** Give one or more things to someone, with an optional photo (multipart when there is one). */
  issue: (cid: number, input: IssueInput) =>
    input.photo ? http.form<Holder>(path(cid, "equipment/issue/"), form({ ...input })) : http.post<Holder>(path(cid, "equipment/issue/"), { ...input, photo: undefined }),
  /** It came back (with its condition and a photo), or it is lost; optionally a deduction with it. */
  giveBack: (cid: number, assignmentId: number, input: ReturnInput) =>
    input.photo
      ? http.form<Holder>(path(cid, `equipment/handouts/${assignmentId}/return/`), form({ ...input }))
      : http.post<Holder>(path(cid, `equipment/handouts/${assignmentId}/return/`), { ...input, photo: undefined }),
  deduct: (cid: number, assignmentId: number, input: DeductionInput) => http.post<Holder>(path(cid, `equipment/handouts/${assignmentId}/deduction/`), input),
};

export const equipmentKeys = {
  people: (cid: number, branch: number | null) => qk(cid, MODULE, "equipment", { branch }),
  items: (cid: number, status: string) => qk(cid, MODULE, "equipment-items", { status }),
  categories: (cid: number) => qk(cid, MODULE, "equipment-categories"),
  person: (cid: number, memberId: number) => qk(cid, MODULE, "equipment-person", { memberId }),
};

/** Equipment needs the assets module (the app's "My equipment" and the register live there). */
export function useAssetsOn() {
  const company = useCompanyStore();
  return computed(() => company.enabled("assets"));
}

export function useEquipment(branch: MaybeRefOrGetter<number | null> = null) {
  const cid = useCompanyId();
  const on = useAssetsOn();
  return useQuery({
    queryKey: computed(() => equipmentKeys.people(cid.value, toValue(branch))),
    queryFn: ({ signal }) => equipmentApi.people(cid.value, toValue(branch), signal),
    enabled: computed(() => cid.value > 0 && on.value),
    placeholderData: keepPreviousData,
    staleTime: 15_000,
  });
}

export function useStock(status: MaybeRefOrGetter<"stock" | "out" | "all"> = "stock", enabled: MaybeRefOrGetter<boolean> = true) {
  const cid = useCompanyId();
  const on = useAssetsOn();
  return useQuery({
    queryKey: computed(() => equipmentKeys.items(cid.value, toValue(status))),
    queryFn: ({ signal }) => equipmentApi.items(cid.value, toValue(status), signal),
    enabled: computed(() => cid.value > 0 && on.value && toValue(enabled)),
    staleTime: 15_000,
  });
}

export function useCategories(enabled: MaybeRefOrGetter<boolean> = true) {
  const cid = useCompanyId();
  const on = useAssetsOn();
  return useQuery({
    queryKey: computed(() => equipmentKeys.categories(cid.value)),
    queryFn: ({ signal }) => equipmentApi.categories(cid.value, signal),
    enabled: computed(() => cid.value > 0 && on.value && toValue(enabled)),
    staleTime: 30_000,
  });
}

export function useEquipmentPerson(memberId: MaybeRefOrGetter<number | null>) {
  const cid = useCompanyId();
  const on = useAssetsOn();
  return useQuery({
    queryKey: computed(() => equipmentKeys.person(cid.value, toValue(memberId) ?? 0)),
    queryFn: ({ signal }) => equipmentApi.person(cid.value, toValue(memberId)!, signal),
    enabled: computed(() => cid.value > 0 && on.value && !!toValue(memberId)),
    staleTime: 15_000,
  });
}

/** Lifecycle (this page, the leaving drawer), people (Person 360, the wizard), assets, payroll, the shell. */
export function useEquipmentRefresh() {
  const client = useQueryClient();
  const cid = useCompanyId();
  return () => {
    for (const module of [MODULE, "people", "assets", "payroll", "shell"]) void client.invalidateQueries({ queryKey: [cid.value, module] });
  };
}

export function useEquipmentMutation<I, O>(run: (cid: number, input: I) => Promise<O>) {
  const cid = useCompanyId();
  const refresh = useEquipmentRefresh();
  return useMutation({ mutationFn: (input: I) => run(cid.value, input), onSettled: refresh });
}
