/** Team reports (plan §6.1, package B): team KPIs over any range, grouped and compared, and routine compliance. */
import { ChartColumn, Repeat } from "@lucide/vue";

import { defineModule } from "@/core/modules";

import { routes } from "./routes";

export default defineModule({
  id: "reports",
  group: "insights",
  order: 10,
  icon: ChartColumn,
  title: "reports.title",
  perm: "reports.view",
  routes,
  nav: [
    { key: "team", title: "reports.tabs.team", to: "reports/team" },
    { key: "routines", title: "reports.tabs.routines", to: "reports/routines" },
  ],
  invalidates: ["tasks.tasks"],
  commands: (ctx) => [
    {
      id: "reports.team",
      title: ctx.t("reports.cmd.team"),
      icon: ChartColumn,
      keywords: ["kpi", "results", "natijalar", "итоги", "on time"],
      run: () => ctx.go("reports/team"),
    },
    {
      id: "reports.routines",
      title: ctx.t("reports.cmd.routines"),
      icon: Repeat,
      keywords: ["compliance", "routine", "kundalik", "ежедневн"],
      run: () => ctx.go("reports/routines"),
    },
  ],
  messages: (language) => import(`./i18n/${language}.json`),
});
