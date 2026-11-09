/**
 * Davomat's endpoints (docs/DAVOMAT.md §1) as typed functions, and the vue-query helpers the pages
 * use. Keys start with `[companyId, "davomat"]`, so the module's pulse prefix (`davomat`, in
 * index.ts) refreshes everything here. The Overview and the employee page also read Face ID's and
 * attendance's endpoints directly (`faceid/…`, `attendance/…`): modules share data through the API,
 * never through each other's code.
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import { computed, toValue, type MaybeRefOrGetter } from "vue";

import { http, ownerPath, request } from "@/api/http";
import { keys as shellKeys, moduleKey, qk } from "@/api/keys";
import type { AccessResponse } from "@/api/types";
import { refreshEdition } from "@/core/edition";
import { useCompanyId } from "@/stores/company";

import type {
  Branch,
  BranchInput,
  Department,
  Employee,
  EmployeeInput,
  EmployeeParams,
  ImportResult,
  Organization,
  Page,
  Position,
  ScheduleOption,
  SetupInput,
  TelegramLink,
  TelegramSettings,
  User,
  UserInput,
  UserPatch,
} from "./types";

export const MODULE = "davomat";

const path = (companyId: number, rest: string) => ownerPath(companyId, rest);

// ─── Sign-in and first run (public) ─────────────────────────────────────────

/** `POST auth/password/` → `{access}` and the refresh cookie; 400 wrong pair, 429 locked out. */
export const passwordLogin = (username: string, password: string) =>
  request<AccessResponse>("/owner/auth/password/", { method: "POST", json: { username, password }, anonymous: true, toast: false });

/** `POST edition/setup/` (once, while `needs_setup`): the organization and its first admin, signed in. */
export const runSetup = (input: SetupInput) => request<AccessResponse>("/owner/edition/setup/", { method: "POST", json: input, anonymous: true, toast: false });

/** `POST auth/password/change/` → 204. */
export const changePassword = (current: string, next: string) =>
  request<void>("/owner/auth/password/change/", { method: "POST", json: { current, new: next }, toast: false });

// ─── Users (§1.3) ───────────────────────────────────────────────────────────

export const listUsers = (cid: number, signal?: AbortSignal) => http.get<User[] | Page<User>>(path(cid, "users/"), { page_size: 200 }, { signal }).then(rows);
export const createUser = (cid: number, body: UserInput) => http.post<User>(path(cid, "users/"), body, { toast: false });
export const updateUser = (cid: number, id: number, body: UserPatch) => http.patch<User>(path(cid, `users/${id}/`), body, { toast: false });
export const setUserPassword = (cid: number, id: number, password: string) => http.post<void>(path(cid, `users/${id}/password/`), { password }, { toast: false });
export const deactivateUser = (cid: number, id: number) => http.delete<void>(path(cid, `users/${id}/`));
export const userTelegramLink = (cid: number, id: number) => http.post<TelegramLink>(path(cid, `users/${id}/telegram-link/`));
export const userTelegramUnlink = (cid: number, id: number) => http.delete<void>(path(cid, `users/${id}/telegram-link/`));

/** `GET roles/`: the four roles made at setup (Owner, Administrator, Manager, Viewer) and any others. */
export interface RoleOption {
  id: number;
  name: string;
  is_owner: boolean;
  is_default?: boolean;
  kind?: string;
  can_assign?: boolean;
  members_count?: number;
}
export const listRoles = (cid: number, signal?: AbortSignal) => http.get<RoleOption[]>(path(cid, "roles/"), undefined, { signal });

// ─── Employees (§1.4) ───────────────────────────────────────────────────────

function rows<T>(body: T[] | Page<T>): T[] {
  return Array.isArray(body) ? body : body.results;
}

export const listEmployees = (cid: number, params: EmployeeParams, signal?: AbortSignal) =>
  http.get<Page<Employee>>(path(cid, "employees/"), { ...params, branch: params.branch?.length ? params.branch : undefined }, { signal });
export const getEmployee = (cid: number, id: number, signal?: AbortSignal) => http.get<Employee>(path(cid, `employees/${id}/`), undefined, { signal });
export const createEmployee = (cid: number, body: EmployeeInput) => http.post<Employee>(path(cid, "employees/"), body, { toast: false });
export const updateEmployee = (cid: number, id: number, body: Partial<EmployeeInput>) => http.patch<Employee>(path(cid, `employees/${id}/`), body, { toast: false });
export function uploadEmployeePhoto(cid: number, id: number, photo: Blob): Promise<Employee> {
  const form = new FormData();
  form.append("photo", photo, "photo.jpg");
  return http.form<Employee>(path(cid, `employees/${id}/photo/`), form);
}
export const employeeLeaves = (cid: number, id: number, date: string) => http.post<Employee>(path(cid, `employees/${id}/leave/`), { left_on: date, date });
export const employeeReturns = (cid: number, id: number) => http.post<Employee>(path(cid, `employees/${id}/return/`));
export const employeeTelegramLink = (cid: number, id: number) => http.post<TelegramLink>(path(cid, `employees/${id}/telegram-link/`));
export const employeeTelegramUnlink = (cid: number, id: number) => http.delete<void>(path(cid, `employees/${id}/telegram-link/`));

/** `POST employees/import/` with the file; `dryRun` only checks and previews. */
export function importEmployees(cid: number, file: File, dryRun: boolean): Promise<ImportResult> {
  const form = new FormData();
  form.append("file", file);
  return http.form<ImportResult>(path(cid, "employees/import/"), form, { query: dryRun ? { dry_run: 1 } : undefined, toast: false });
}

/** `GET employees/export/` as a file download (the browser's own save). */
export async function exportEmployees(cid: number, params: EmployeeParams = {}): Promise<void> {
  const response = await request<Response>(path(cid, "employees/export/"), { query: { ...params, branch: params.branch?.length ? params.branch : undefined }, raw: true, toast: true });
  const blob = await response.blob();
  const disposition = response.headers.get("Content-Disposition") ?? "";
  const named = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(disposition)?.[1];
  saveBlob(blob, named ? decodeURIComponent(named) : "employees.xlsx");
}

export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 30_000);
}

// ─── Telegram (§1.5) ────────────────────────────────────────────────────────

export const getTelegram = (cid: number, signal?: AbortSignal) => http.get<TelegramSettings>(path(cid, "telegram/"), undefined, { signal });
export const saveTelegramToken = (cid: number, token: string) => http.put<TelegramSettings>(path(cid, "telegram/"), { token }, { toast: false });
export const testTelegram = (cid: number) => http.post<{ detail?: string } | void>(path(cid, "telegram/test/"), {}, { toast: false });

// ─── Organization and shared lists (existing endpoints) ─────────────────────

export const getOrganization = (cid: number, signal?: AbortSignal) => http.get<Organization>(path(cid, "settings/"), undefined, { signal });
export const saveOrganization = (cid: number, body: Partial<Pick<Organization, "name" | "timezone" | "default_language">>) =>
  http.patch<Organization>(path(cid, "settings/"), body, { toast: false });
export function uploadLogo(cid: number, file: Blob): Promise<Organization> {
  const form = new FormData();
  form.append("logo", file, "logo.png");
  return http.form<Organization>(path(cid, "settings/logo/"), form);
}
export const removeLogo = (cid: number) => http.delete<Organization>(path(cid, "settings/logo/"));

export const listBranches = (cid: number, signal?: AbortSignal) => http.get<Branch[]>(path(cid, "branches/"), undefined, { signal });
export const createBranch = (cid: number, body: BranchInput) => http.post<Branch>(path(cid, "branches/"), body, { toast: false });
export const updateBranch = (cid: number, id: number, body: Partial<BranchInput>) => http.patch<Branch>(path(cid, `branches/${id}/`), body, { toast: false });
export const deactivateBranch = (cid: number, id: number) => http.post<Branch>(path(cid, `branches/${id}/deactivate/`));
export const activateBranch = (cid: number, id: number) => http.post<Branch>(path(cid, `branches/${id}/activate/`));

export const listDepartments = (cid: number, signal?: AbortSignal) => http.get<Department[]>(path(cid, "departments/"), undefined, { signal });
export const createDepartment = (cid: number, name: string) => http.post<Department>(path(cid, "departments/"), { name }, { toast: false });
export const renameDepartment = (cid: number, id: number, name: string) => http.patch<Department>(path(cid, `departments/${id}/`), { name }, { toast: false });
export const deleteDepartment = (cid: number, id: number) => http.delete<void>(path(cid, `departments/${id}/`));

export const listPositions = (cid: number, signal?: AbortSignal) => http.get<Position[]>(path(cid, "positions/"), undefined, { signal });
export const createPosition = (cid: number, name: string) => http.post<Position>(path(cid, "positions/"), { name }, { toast: false });
export const renamePosition = (cid: number, id: number, name: string) => http.patch<Position>(path(cid, `positions/${id}/`), { name }, { toast: false });
export const deletePosition = (cid: number, id: number) => http.delete<void>(path(cid, `positions/${id}/`));

export const listSchedules = (cid: number, signal?: AbortSignal) => http.get<ScheduleOption[]>(path(cid, "attendance/schedules/"), undefined, { signal });

// ─── Keys ───────────────────────────────────────────────────────────────────

export const davomatKeys = {
  all: (cid: number) => moduleKey(cid, MODULE),
  users: (cid: number) => qk(cid, MODULE, "users"),
  roles: (cid: number) => qk(cid, MODULE, "roles"),
  employees: (cid: number, params: EmployeeParams) => qk(cid, MODULE, "employees", { ...params }),
  employee: (cid: number, id: number) => qk(cid, MODULE, "employee", { id }),
  telegram: (cid: number) => qk(cid, MODULE, "telegram"),
  organization: (cid: number) => qk(cid, MODULE, "organization"),
  branches: (cid: number) => qk(cid, MODULE, "branches"),
  departments: (cid: number) => qk(cid, MODULE, "departments"),
  positions: (cid: number) => qk(cid, MODULE, "positions"),
  schedules: (cid: number) => qk(cid, MODULE, "schedules"),
};

// ─── Queries ────────────────────────────────────────────────────────────────

export function useUsers() {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => davomatKeys.users(cid.value)),
    queryFn: ({ signal }) => listUsers(cid.value, signal),
    enabled: computed(() => cid.value > 0),
  });
}

export function useRoles() {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => davomatKeys.roles(cid.value)),
    queryFn: ({ signal }) => listRoles(cid.value, signal),
    enabled: computed(() => cid.value > 0),
    staleTime: 5 * 60_000,
  });
}

export function useEmployees(params: MaybeRefOrGetter<EmployeeParams>, enabled: MaybeRefOrGetter<boolean> = true) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => davomatKeys.employees(cid.value, toValue(params))),
    queryFn: ({ signal }) => listEmployees(cid.value, toValue(params), signal),
    enabled: computed(() => cid.value > 0 && toValue(enabled)),
    placeholderData: keepPreviousData,
    // "Today" moves as people arrive: the pulse refreshes it; this catches a missed one.
    refetchInterval: 60_000,
  });
}

export function useEmployee(id: MaybeRefOrGetter<number | null>) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => davomatKeys.employee(cid.value, toValue(id) ?? 0)),
    queryFn: ({ signal }) => getEmployee(cid.value, toValue(id)!, signal),
    enabled: computed(() => cid.value > 0 && !!toValue(id)),
  });
}

export function useTelegram(enabled: MaybeRefOrGetter<boolean> = true) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => davomatKeys.telegram(cid.value)),
    queryFn: ({ signal }) => getTelegram(cid.value, signal),
    enabled: computed(() => cid.value > 0 && toValue(enabled)),
  });
}

export function useOrganization() {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => davomatKeys.organization(cid.value)),
    queryFn: ({ signal }) => getOrganization(cid.value, signal),
    enabled: computed(() => cid.value > 0),
  });
}

export function useBranches() {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => davomatKeys.branches(cid.value)),
    queryFn: ({ signal }) => listBranches(cid.value, signal),
    enabled: computed(() => cid.value > 0),
    staleTime: 60_000,
  });
}

export function useDepartments() {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => davomatKeys.departments(cid.value)),
    queryFn: ({ signal }) => listDepartments(cid.value, signal),
    enabled: computed(() => cid.value > 0),
    staleTime: 60_000,
  });
}

export function usePositions() {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => davomatKeys.positions(cid.value)),
    queryFn: ({ signal }) => listPositions(cid.value, signal),
    enabled: computed(() => cid.value > 0),
    staleTime: 60_000,
  });
}

export function useSchedules(enabled: MaybeRefOrGetter<boolean> = true) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => davomatKeys.schedules(cid.value)),
    queryFn: ({ signal }) => listSchedules(cid.value, signal),
    enabled: computed(() => cid.value > 0 && toValue(enabled)),
    staleTime: 5 * 60_000,
  });
}

// ─── Refresh after a write ──────────────────────────────────────────────────

/**
 * Everything of this module, the shell's `me` (company names, logos and branches live there),
 * the pulse, and Face ID's and attendance's lists that show people (names, photos, numbers).
 */
export function useRefresh() {
  const client = useQueryClient();
  const cid = useCompanyId();
  return () => {
    void client.invalidateQueries({ queryKey: davomatKeys.all(cid.value) });
    void client.invalidateQueries({ queryKey: moduleKey(cid.value, "faceid") });
    void client.invalidateQueries({ queryKey: moduleKey(cid.value, "attendance") });
    void client.invalidateQueries({ queryKey: shellKeys.pulse(cid.value) });
  };
}

/** After the organization's name, logo or bot changed: the edition (sign-in page, title) asks again. */
export function useBrandRefresh() {
  const refresh = useRefresh();
  return async () => {
    refresh();
    await refreshEdition();
  };
}

export function useEmployeeSave() {
  const cid = useCompanyId();
  const refresh = useRefresh();
  return useMutation({
    mutationFn: ({ id, body }: { id: number | null; body: EmployeeInput }) => (id ? updateEmployee(cid.value, id, body) : createEmployee(cid.value, body)),
    onSuccess: refresh,
  });
}
