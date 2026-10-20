/**
 * Settings (plan §6.1 "settings/:panel?", §6.2, package A): one page whose panels come from the
 * registry. This module brings Company, Modules, Branches, Invite, Notifications and Sessions;
 * other modules add theirs through `settings` (attendance, sales, finance, payroll…), and they
 * appear in the same list after these. Panels load lazily.
 */
import { Bell, Building2, LayoutGrid, MapPin, MonitorSmartphone, QrCode, Settings, UserPlus } from "@lucide/vue";
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
    { id: "company", title: "settings.panel.company", order: 10, icon: Building2, component: defineAsyncComponent(() => import("./panels/CompanyPanel.vue")) },
    { id: "features", title: "settings.panel.features", order: 20, icon: LayoutGrid, perm: "company.settings", component: defineAsyncComponent(() => import("./panels/FeaturesPanel.vue")) },
    { id: "branches", title: "settings.panel.branches", order: 30, icon: MapPin, component: defineAsyncComponent(() => import("./panels/BranchesPanel.vue")) },
    { id: "invite", title: "settings.panel.invite", order: 40, icon: UserPlus, perm: "members.approve", component: defineAsyncComponent(() => import("./panels/InvitePanel.vue")) },
    { id: "notifications", title: "settings.panel.notifications", order: 50, icon: Bell, component: defineAsyncComponent(() => import("./panels/NotificationsPanel.vue")) },
    { id: "sessions", title: "settings.panel.sessions", order: 60, icon: MonitorSmartphone, component: defineAsyncComponent(() => import("./panels/SessionsPanel.vue")) },
  ],
  commands: (ctx) => [
    { id: "settings.company", title: ctx.t("settings.cmd.company"), icon: Building2, keywords: ["settings", "sozlamalar", "настройки"], run: () => ctx.go("settings/company") },
    { id: "settings.branches", title: ctx.t("settings.cmd.branches"), icon: MapPin, keywords: ["branch", "filial", "филиал"], run: () => ctx.go("settings/branches") },
    { id: "settings.addBranch", title: ctx.t("settings.cmd.addBranch"), icon: MapPin, perm: "company.settings", run: () => ctx.go("settings/branches?branch=new") },
    { id: "settings.invite", title: ctx.t("settings.cmd.invite"), icon: QrCode, perm: "members.approve", keywords: ["invite", "taklif", "пригласить", "qr"], run: () => ctx.go("settings/invite") },
    { id: "settings.modules", title: ctx.t("settings.cmd.modules"), icon: LayoutGrid, perm: "company.settings", keywords: ["modules", "modullar", "модули"], run: () => ctx.go("settings/features") },
    { id: "settings.sessions", title: ctx.t("settings.cmd.sessions"), icon: MonitorSmartphone, keywords: ["sessions", "seanslar", "сеансы", "logout"], run: () => ctx.go("settings/sessions") },
  ],
  searchResults: {
    "companies.branches": defineAsyncComponent(() => import("./components/BranchHit.vue")),
  },
  deepLinks: {
    settings: (argument) => (argument ? `settings/${argument}` : "settings"),
  },
  messages: async () => {
    const [uz, ru, en] = await Promise.all([import("./i18n/uz.json"), import("./i18n/ru.json"), import("./i18n/en.json")]);
    return { uz: uz.default, ru: ru.default, en: en.default };
  },
});
