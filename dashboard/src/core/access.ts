/** Who may see what: the one place the shell decides visibility of modules, routes and items. */
import type { RouteLocationNormalizedLoaded, RouteRecordNormalized } from "vue-router";

import type { Company } from "@/api/types";
import { hasFeature, type CompanyFeature } from "@/core/features";
import { findModule, type DashboardModule } from "@/core/modules";
import { hasPerm, type PermRequirement } from "@/core/perms";

export interface Gated {
  perm?: PermRequirement;
  feature?: CompanyFeature;
}

/** Permission and feature switch both allow it. */
export function allowed(company: Company | null | undefined, item: Gated): boolean {
  return !!company && hasPerm(company, item.perm) && hasFeature(company, item.feature);
}

export function isModuleVisible(module: DashboardModule, company: Company | null | undefined): boolean {
  return allowed(company, module);
}

export function visibleModules(list: readonly DashboardModule[], company: Company | null | undefined): DashboardModule[] {
  return list.filter((m) => isModuleVisible(m, company));
}

/**
 * Every matched record's `meta.perm` and `meta.feature`, and the owning module's own gate, must pass.
 * Routes outside a module (shell pages) only check their own meta.
 */
export function canAccessRecords(records: readonly RouteRecordNormalized[], company: Company | null | undefined): boolean {
  for (const record of records) {
    const meta = record.meta;
    if (meta.public || meta.companyless) continue;
    const module = findModule(meta.module);
    if (module && !isModuleVisible(module, company)) return false;
    if (!allowed(company, { perm: meta.perm, feature: meta.feature })) return false;
  }
  return true;
}

export function canAccessRoute(route: RouteLocationNormalizedLoaded, company: Company | null | undefined): boolean {
  return canAccessRecords(route.matched, company);
}

/**
 * Why a route is closed when it is the company's switch, not the person's role: the module (or
 * page) whose feature is off, so the page can say "Sales is off" rather than "your role doesn't
 * include it". Null when a switch isn't the reason (or the route is open).
 */
export function switchedOff(records: readonly RouteRecordNormalized[], company: Company | null | undefined): { feature: CompanyFeature; module: DashboardModule | null } | null {
  if (!company) return null;
  for (const record of records) {
    const meta = record.meta;
    if (meta.public || meta.companyless) continue;
    const module = findModule(meta.module) ?? null;
    if (module?.feature && !hasFeature(company, module.feature)) return { feature: module.feature, module };
    if (meta.feature && !hasFeature(company, meta.feature)) return { feature: meta.feature, module };
  }
  return null;
}
