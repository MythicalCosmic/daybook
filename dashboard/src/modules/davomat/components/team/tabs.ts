/**
 * The Team pages' tabs (Employees · Departments · Positions · Locations), under each page's title:
 * the sidebar row lists them too, the phone has only this.
 */
import { BriefcaseBusiness, MapPin, Network, Users } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import type { PageTab } from "@/components/PageHeader.vue";
import { useCompanyStore } from "@/stores/company";

export function useTeamTabs() {
  const { t } = useI18n();
  const company = useCompanyStore();
  return computed<PageTab[]>(() => {
    const base = `/c/${company.currentId}/team`;
    return [
      { id: "employees", label: t("davomat.nav.employees"), to: base, icon: Users },
      { id: "departments", label: t("davomat.nav.departments"), to: `${base}/departments`, icon: Network },
      { id: "positions", label: t("davomat.nav.positions"), to: `${base}/positions`, icon: BriefcaseBusiness },
      { id: "branches", label: t("davomat.nav.branches"), to: `${base}/branches`, icon: MapPin },
    ];
  });
}
