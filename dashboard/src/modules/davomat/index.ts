/**
 * Davomat (docs/DAVOMAT.md): the standalone Face ID and attendance edition's own pages, in the
 * `davomat` edition only. It brings the password sign-in and the first-run setup wizard (public
 * routes), the Overview live board (the home), Team (employees with their faces, departments,
 * positions, branches) and Settings (organization, users and roles, Telegram, the attendance and
 * Face ID rules other modules register, your account). Face ID and attendance are their own
 * modules, in this edition too. Kept tiny: pages and the API load on use.
 */
import { LayoutDashboard, Send, Settings, Upload, UserPlus, Users } from "@lucide/vue";
import { defineAsyncComponent } from "vue";
import type { RouteRecordRaw } from "vue-router";

import { defineModule } from "@/core/modules";

const publicRoutes: RouteRecordRaw[] = [
  { path: "/login", name: "login", component: () => import("./pages/LoginPage.vue"), meta: { title: "davomat.login.title" } },
  { path: "/setup", name: "setup", component: () => import("./pages/SetupPage.vue"), meta: { title: "davomat.setup.title" } },
];

const routes: RouteRecordRaw[] = [
  { path: "", name: "davomat.overview", component: () => import("./pages/OverviewPage.vue"), meta: { title: "davomat.nav.overview", perm: "attendance.view" } },
  { path: "team", name: "davomat.employees", component: () => import("./pages/EmployeesPage.vue"), meta: { title: "davomat.nav.employees", perm: "members.view" } },
  { path: "team/departments", name: "davomat.departments", component: () => import("./pages/DepartmentsPage.vue"), meta: { title: "davomat.nav.departments", perm: "members.view" } },
  { path: "team/positions", name: "davomat.positions", component: () => import("./pages/PositionsPage.vue"), meta: { title: "davomat.nav.positions", perm: "members.view" } },
  { path: "team/branches", name: "davomat.branches", component: () => import("./pages/BranchesPage.vue"), meta: { title: "davomat.nav.branches", perm: "members.view" } },
  { path: "team/:employeeId(\\d+)", name: "davomat.employee", component: () => import("./pages/EmployeePage.vue"), meta: { title: "davomat.employee.title", perm: "members.view" } },
  // Links the shared components make to a person (PersonCell, Face ID, attendance) land on their page here.
  { path: "people/:employeeId(\\d+)/:tab?", name: "davomat.person", redirect: (to) => ({ name: "davomat.employee", params: { companyId: to.params.companyId, employeeId: to.params.employeeId } }) },
  { path: "settings/:panel?", name: "davomat.settings", component: () => import("./pages/SettingsPage.vue"), meta: { title: "davomat.nav.settings" } },
];

export default defineModule({
  id: "davomat",
  editions: ["davomat"],
  group: "overview",
  order: 10,
  icon: LayoutDashboard,
  title: "davomat.nav.overview",
  index: true,
  hotkey: "o",
  routes,
  publicRoutes,
  nav: [
    { key: "overview", title: "davomat.nav.overview", to: "", exact: true, perm: "attendance.view" },
    {
      key: "employees",
      title: "davomat.nav.employees",
      to: "team",
      exact: true,
      perm: "members.view",
      row: { key: "davomat.team", title: "davomat.nav.team", icon: Users, group: "people", order: 25, hotkey: "e" },
    },
    { key: "departments", title: "davomat.nav.departments", to: "team/departments", perm: "members.view" },
    { key: "positions", title: "davomat.nav.positions", to: "team/positions", perm: "members.view" },
    { key: "branches", title: "davomat.nav.branches", to: "team/branches", perm: "members.view" },
    { key: "settings", title: "davomat.nav.settings", to: "settings", row: { key: "davomat.settings", title: "davomat.nav.settings", icon: Settings, group: "company", order: 10, hotkey: "," } },
  ],
  // apps/davomat (users, employees, telegram), people and company changes (members, companies).
  invalidates: ["davomat", "members", "companies"],
  commands: (ctx) => [
    {
      id: "davomat.addEmployee",
      title: ctx.t("davomat.cmd.addEmployee"),
      icon: UserPlus,
      keywords: ["employee", "xodim", "сотрудник", "add"],
      perm: "members.manage",
      run: () => ctx.go("team?employee=new"),
    },
    {
      id: "davomat.import",
      title: ctx.t("davomat.cmd.import"),
      icon: Upload,
      keywords: ["excel", "csv", "import", "yuklash", "импорт"],
      perm: "members.manage",
      run: () => ctx.go("team?import=1"),
    },
    {
      id: "davomat.users",
      title: ctx.t("davomat.cmd.users"),
      icon: Users,
      keywords: ["users", "login", "parol", "пароль", "foydalanuvchi", "пользователи"],
      perm: "roles.manage",
      run: () => ctx.go("settings/users"),
    },
    {
      id: "davomat.telegram",
      title: ctx.t("davomat.cmd.telegram"),
      icon: Send,
      keywords: ["telegram", "bot", "бот"],
      perm: "company.settings",
      run: () => ctx.go("settings/telegram"),
    },
  ],
  settings: [
    { id: "organization", title: "davomat.settings.organization.title", order: 10, component: defineAsyncComponent(() => import("./panels/OrganizationPanel.vue")) },
    { id: "users", title: "davomat.settings.users.title", order: 20, perm: "roles.manage", component: defineAsyncComponent(() => import("./panels/UsersPanel.vue")) },
    { id: "telegram", title: "davomat.settings.telegram.title", order: 30, perm: "company.settings", component: defineAsyncComponent(() => import("./panels/TelegramPanel.vue")) },
    { id: "account", title: "davomat.settings.account.title", order: 90, component: defineAsyncComponent(() => import("./panels/AccountPanel.vue")) },
  ],
  deepLinks: {
    team: () => "team",
    employee: (id) => (/^\d+$/.test(id) ? `team/${id}` : "team"),
  },
  // The base dictionary plus the Team and Settings parts (merged into one file before hand-off).
  messages: (language) =>
    Promise.all([import(`./i18n/${language}.json`), import(`./i18n/parts/team.${language}.json`), import(`./i18n/parts/settings.${language}.json`)]).then(
      (loaded) => Object.assign({}, ...loaded.map((part) => part.default)) as Record<string, string>,
    ),
});
