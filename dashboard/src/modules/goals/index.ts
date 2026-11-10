/**
 * Business goals (v11 K, `apps.goals`): "1.5 bln revenue this quarter, a third pharmacy, staff
 * turnover under 10 %", measured from the company's own data, with progress, a forecast to the
 * period's end and on-track states. In Money, after payroll. Seeing goals needs reports.view
 * (each goal also its numbers' permission, checked by the server); setting them is the owners'.
 */
import { Target } from "@lucide/vue";

import { defineModule } from "@/core/modules";

import { routes } from "./routes";

export default defineModule({
  id: "goals",
  group: "money",
  order: 45,
  icon: Target,
  title: "goals.title",
  perm: "reports.view",
  routes,
  nav: [{ key: "list", title: "goals.title", to: "goals", perm: "reports.view" }],
  // Goals change on their own pulse; their numbers come from the ledger, sales and people.
  invalidates: ["goals", "finance"],
  commands: (ctx) => [
    {
      id: "goals.open",
      title: ctx.t("goals.cmd.open"),
      icon: Target,
      keywords: ["maqsad", "цель", "goal", "target", "kpi", "reja"],
      perm: "reports.view",
      run: () => ctx.go("goals"),
    },
  ],
  deepLinks: {
    goal: (id) => (/^\d+$/.test(id) ? `goals?goal=${id}` : "goals"),
    goals: () => "goals",
  },
  messages: (language) => import(`./i18n/${language}.json`),
});
