/** Permission and feature checks for the current company, for templates and scripts. */
import { computed, type ComputedRef } from "vue";

import type { CompanyFeature } from "@/core/features";
import type { PermRequirement } from "@/core/perms";
import { useCompanyStore } from "@/stores/company";

export function usePermission() {
  const company = useCompanyStore();
  return {
    /** Holds the permission, or any of the listed ones (owners hold all). */
    can: (perm?: PermRequirement) => company.can(perm),
    /** Holds every listed permission. */
    canAll: (perms: PermRequirement) => (typeof perms === "string" ? [perms] : perms).every((p) => company.can(p)),
    enabled: (feature?: CompanyFeature) => company.enabled(feature),
    isOwner: computed(() => company.current?.is_owner ?? false),
  };
}

/** `const canExport = useCan("data.export")` */
export function useCan(perm: PermRequirement): ComputedRef<boolean> {
  const company = useCompanyStore();
  return computed(() => company.can(perm));
}
