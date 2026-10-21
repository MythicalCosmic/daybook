/**
 * Settings (plan §6.1 "settings/:panel?", §6.2, package A): one page whose panels come from the
 * registry. This module brings Company, Modules, Branches, Invite, Notifications and Sessions;
 * other modules add theirs through `settings` (attendance, sales, finance, payroll…), and they
 * appear in the same list after these. Panels load lazily; their icons live in the page, so
 * this entry (part of the first bundle) stays small.
 */
import { Settings } from "@lucide/vue";
import { defineAsyncComponent } from "vue";

import { defineModule } from "@/core/modules";

import { routes } from "./routes";

export default defineModule({
  id: "settings",
  group: "company",
  order: 10,
  icon: Settings,
  title: "settings.title",
  hotkey: ",",
  routes,
  nav: [{ key: "panels", title: "settings.title", to: "settings" }],
  // apps.companies' "companies.settings" / "companies.branches" / "companies.setup" keys.
  invalidates: ["companies"],
  settings: [
    { id: "company", title: "settings.panel.company", order: 10, component: defineAsyncComponent(() => import("./panels/CompanyPanel.vue")) },
    { id: "features", title: "settings.panel.features", order: 20, perm: "company.settings", component: defineAsyncComponent(() => import("./panels/FeaturesPanel.vue")) },
    { id: "branches", title: "settings.panel.branches", order: 30, component: defineAsyncComponent(() => import("./panels/BranchesPanel.vue")) },
    { id: "invite", title: "settings.panel.invite", order: 40, perm: "members.approve", component: defineAsyncComponent(() => import("./panels/InvitePanel.vue")) },
    { id: "notifications", title: "settings.panel.notifications", order: 50, component: defineAsyncComponent(() => import("./panels/NotificationsPanel.vue")) },
    { id: "sessions", title: "settings.panel.sessions", order: 60, component: defineAsyncComponent(() => import("./panels/SessionsPanel.vue")) },
  ],
  commands: (ctx) => [
    { id: "settings.company", title: ctx.t("settings.cmd.company"), keywords: ["sozlamalar", "настройки"], run: () => ctx.go("settings/company") },
    { id: "settings.branches", title: ctx.t("settings.cmd.branches"), keywords: ["filial", "филиал"], run: () => ctx.go("settings/branches") },
    { id: "settings.addBranch", title: ctx.t("settings.cmd.addBranch"), perm: "company.settings", run: () => ctx.go("settings/branches?branch=new") },
    { id: "settings.invite", title: ctx.t("settings.cmd.invite"), perm: "members.approve", keywords: ["taklif", "пригласить", "qr"], run: () => ctx.go("settings/invite") },
    { id: "settings.modules", title: ctx.t("settings.cmd.modules"), perm: "company.settings", run: () => ctx.go("settings/features") },
    { id: "settings.sessions", title: ctx.t("settings.cmd.sessions"), keywords: ["logout"], run: () => ctx.go("settings/sessions") },
  ],
  searchResults: {
    "companies.branches": defineAsyncComponent(() => import("./components/BranchHit.vue")),
  },
  deepLinks: {
    settings: (argument) => (argument ? `settings/${argument}` : "settings"),
  },
  messages: (language) => import(`./i18n/${language}.json`),
});
