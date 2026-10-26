/**
 * People (plan §6.1–§6.2, package C): the team directory, departments with their heads (the org
 * chart), Person 360 with the tabs other modules register, join requests, roles with the
 * permission matrix, positions and the offboarding wizard.
 * Kept tiny: pages, widgets and the API load on use.
 */
import { BriefcaseBusiness, Network, ShieldCheck, UserPlus, Users } from "@lucide/vue";
import { defineAsyncComponent } from "vue";

import { defineModule } from "@/core/modules";
import { counter } from "@/core/pulse";

import { routes } from "./routes";

export default defineModule({
  id: "people",
  group: "people",
  order: 10,
  icon: Users,
  title: "people.title",
  perm: "members.view",
  hotkey: "p",
  routes,
  nav: [
    { key: "team", title: "people.nav.team", to: "people", exact: true },
    { key: "departments", title: "people.nav.departments", to: "people/departments" },
    { key: "requests", title: "people.nav.requests", to: "people/requests", perm: "members.approve", badge: counter("members.pending") },
    { key: "roles", title: "people.nav.roles", to: "people/roles", perm: "roles.manage" },
    { key: "positions", title: "people.nav.positions", to: "people/positions", perm: "positions.manage" },
  ],
  // Every members.* key (people, pending, roles, positions, departments) and time off shown on Person 360.
  invalidates: ["members", "timeoff.time_off"],
  commands: (ctx) => [
    {
      id: "people.departments",
      title: ctx.t("people.cmd.departments"),
      icon: Network,
      keywords: ["departments", "org chart", "bo‘lim", "отделы"],
      run: () => ctx.go("people/departments"),
    },
    {
      id: "people.requests",
      title: ctx.t("people.cmd.requests"),
      icon: UserPlus,
      perm: "members.approve",
      keywords: ["join", "approve", "so‘rov", "заявки"],
      run: () => ctx.go("people/requests"),
    },
    {
      id: "people.roles",
      title: ctx.t("people.cmd.roles"),
      icon: ShieldCheck,
      perm: "roles.manage",
      keywords: ["permissions", "ruxsat", "права"],
      run: () => ctx.go("people/roles"),
    },
    {
      id: "people.positions",
      title: ctx.t("people.cmd.positions"),
      icon: BriefcaseBusiness,
      perm: "positions.manage",
      keywords: ["job", "lavozim", "должности"],
      run: () => ctx.go("people/positions"),
    },
  ],
  searchResults: {
    "members.person": defineAsyncComponent(() => import("./components/PersonHit.vue")),
  },
  widgets: [
    {
      id: "people.team",
      span: 1,
      order: 60,
      kind: "card",
      perm: "members.view",
      component: defineAsyncComponent(() => import("./widgets/TeamWidget.vue")),
    },
  ],
  deepLinks: {
    person: (id) => (/^\d+$/.test(id) ? `people/${id}` : "people"),
    requests: () => "people/requests",
  },
  messages: (language) => import(`./i18n/${language}.json`),
});
