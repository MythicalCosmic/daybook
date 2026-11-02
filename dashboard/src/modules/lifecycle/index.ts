/**
 * The people lifecycle (plan §13.4, package S's dashboard): disciplinary records with the pharmacy
 * categories (§14.14) and an optional fine proposed to payroll, and suspensions; the org chart,
 * terminations, job changes, equipment and reviews come later. Adds the "Record" tab to Person 360
 * and "Warn" / "Suspend" to its header (`people.profile.actions`).
 */
import { Gavel, Pause, ShieldAlert } from "@lucide/vue";
import { defineAsyncComponent } from "vue";

import { defineModule } from "@/core/modules";
import { counter } from "@/core/pulse";

import { routes } from "./routes";

export default defineModule({
  id: "lifecycle",
  group: "people",
  order: 50,
  icon: ShieldAlert,
  title: "lifecycle.title",
  perm: ["hr.view", "hr.discipline", "hr.suspend", "hr.terminate", "assets.manage", "reviews.manage"],
  feature: "hr",
  routes,
  nav: [
    { key: "discipline", title: "lifecycle.nav.discipline", to: "lifecycle/discipline", perm: ["hr.discipline", "hr.view"] },
    { key: "suspensions", title: "lifecycle.nav.suspensions", to: "lifecycle/suspensions", perm: ["hr.suspend", "hr.view"] },
    { key: "org", title: "lifecycle.nav.org", to: "lifecycle/org", perm: "hr.view" },
    { key: "terminations", title: "lifecycle.nav.terminations", to: "lifecycle/terminations", perm: ["hr.terminate", "hr.view"], badge: counter("lifecycle.resignations") },
    { key: "changes", title: "lifecycle.nav.changes", to: "lifecycle/job-changes", perm: ["hr.manage", "hr.view"], badge: counter("lifecycle.job_changes") },
    { key: "equipment", title: "lifecycle.nav.equipment", to: "lifecycle/equipment", perm: ["assets.manage", "hr.manage"] },
    { key: "reviews", title: "lifecycle.nav.reviews", to: "lifecycle/reviews", perm: "reviews.manage" },
  ],
  invalidates: ["lifecycle"],
  commands: (ctx) => [
    {
      id: "lifecycle.warn",
      title: ctx.t("lifecycle.cmd.warn"),
      icon: Gavel,
      perm: "hr.discipline",
      keywords: ["warning", "ogohlantirish", "hayfsan", "предупреждение", "выговор", "discipline", "intizom"],
      run: () => ctx.go("lifecycle/discipline?new=1"),
    },
    {
      id: "lifecycle.suspend",
      title: ctx.t("lifecycle.cmd.suspend"),
      icon: Pause,
      perm: "hr.suspend",
      keywords: ["suspend", "to‘xtatish", "приостановить", "отстранить"],
      run: () => ctx.go("lifecycle/suspensions?new=1"),
    },
  ],
  personTabs: [
    {
      id: "record",
      title: "lifecycle.tab",
      perm: ["hr.discipline", "hr.suspend", "hr.view"],
      order: 70,
      component: defineAsyncComponent(() => import("./components/PersonRecordTab.vue")),
    },
  ],
  extensions: {
    "people.profile.actions": [defineAsyncComponent(() => import("./components/ProfileActions.vue"))],
  },
  deepLinks: {
    record: (id) => (/^\d+$/.test(id) ? `lifecycle/discipline?record=${id}` : "lifecycle/discipline"),
  },
  messages: (language) => import(`./i18n/${language}.json`),
});
