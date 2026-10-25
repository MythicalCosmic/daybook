/**
 * What the company switcher shows (plan §13.1), shared by its button (in the first load) and its
 * menu (CompanySwitcherMenu.vue, loaded on first use with the other menus, see lazyPart.ts).
 */
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import { pathInCompany } from "@/app/navigation";
import { lazyPart } from "@/components/lazyPart";
import { hasExtension } from "@/core/extensions";
import { useCompanyStore } from "@/stores/company";
import { useSessionStore } from "@/stores/session";

export type SwitcherVariant = "sidebar" | "rail" | "compact";

/** The switcher's menu: reka-ui's dropdown, out of the first load like DropdownMenu's. */
export const companyMenu = lazyPart(() => import("./CompanySwitcherMenu.vue"));

export function useCompanySwitcher() {
  const { t } = useI18n();
  const route = useRoute();
  const router = useRouter();
  const company = useCompanyStore();
  const session = useSessionStore();

  const companyless = computed(() => route.matched.some((record) => record.meta.companyless));
  const onPortfolio = computed(() => route.name === "portfolio");
  const hasPortfolio = computed(() => router.hasRoute("portfolio"));
  const canCreate = computed(() => hasExtension("shell.company.create", company.current ?? company.companies[0]));
  const current = computed(() => (companyless.value ? null : company.current));
  const label = computed(() => current.value?.name ?? (onPortfolio.value ? t("shell.company.portfolio") : t("shell.company.switch")));
  /** What waits for the person in their other companies (this one's is the Inbox badge). */
  const elsewhere = computed(() => company.companies.filter((item) => item.id !== current.value?.id).reduce((sum, item) => sum + Math.max(0, item.pending ?? 0), 0));

  function openCompany(id: number): void {
    if (id === company.currentId && !companyless.value) return;
    void router.push(companyless.value ? `/c/${id}` : pathInCompany(router, route, id));
    // A pick here (not a link to another company's page) moves the bot to that company as well;
    // best effort, the dashboard works in the picked company either way.
    session.setBotCompany(id);
  }

  return { company, companyless, onPortfolio, hasPortfolio, canCreate, current, label, elsewhere, openCompany };
}
