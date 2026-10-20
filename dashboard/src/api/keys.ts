/**
 * vue-query keys. Every server-state key starts with the company id and the module id
 * (`[companyId, moduleId, resource, params]`), so switching company changes the prefix and nothing
 * from one company is ever shown in another; a pulse change invalidates `[companyId, moduleId]`.
 */
export type QueryParams = Record<string, unknown>;

export type ModuleKey = readonly [companyId: number, moduleId: string];
export type ResourceKey = readonly [companyId: number, moduleId: string, resource: string, params: QueryParams];

/** `qk(12, "finance", "transactions", { page: 2 })` */
export function qk(companyId: number, moduleId: string, resource: string, params: QueryParams = {}): ResourceKey {
  return [companyId, moduleId, resource, params] as const;
}

/** Prefix that matches every query of one module in one company. */
export function moduleKey(companyId: number, moduleId: string): ModuleKey {
  return [companyId, moduleId] as const;
}

/** Shell-owned keys. */
export const keys = {
  me: ["me"] as const,
  permissions: ["permissions"] as const,
  pulse: (companyId: number) => qk(companyId, "shell", "pulse"),
  queue: (companyId: number, kind?: string) => qk(companyId, "shell", "queue", kind ? { kind } : {}),
  inbox: (companyId: number, tab: "unread" | "all") => qk(companyId, "shell", "inbox", { tab }),
  unread: (companyId: number) => qk(companyId, "shell", "unread"),
  search: (companyId: number, q: string) => qk(companyId, "shell", "search", { q }),
};
