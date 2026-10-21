/**
 * The Overview (plan §6.1 "(index)", §6.2): W0's placeholder, handed to package N in Wave 3. It
 * serves `/c/:companyId` (`index: true`), hosts the `overview.hero` slot and renders every
 * module's registered widgets. Its own widgets: branch cards (`branches/today/`), today's routine
 * work (`routines/day/`) and the activity stream (`stream/`).
 */
import { LayoutDashboard } from "@lucide/vue";
import { defineAsyncComponent } from "vue";

import { defineModule } from "@/core/modules";

export default defineModule({
  id: "overview",
  group: "overview",
  order: 10,
  icon: LayoutDashboard,
  title: "overview.title",
  hotkey: "o",
  index: true,
  routes: [
    {
      path: "",
      name: "overview.today",
      component: () => import("./pages/OverviewPage.vue"),
      meta: { title: "overview.title" },
    },
  ],
  // Branch facts come from these apps; any change in them refreshes the cards.
  invalidates: ["sales", "attendance", "tasks", "finance"],
  widgets: [
    { id: "overview.branches", span: 4, order: 10, kind: "card", component: defineAsyncComponent(() => import("./widgets/BranchesWidget.vue")) },
    // Routine work beside the one-off task tiles (`routines/day/`, the Routines page's Today).
    { id: "overview.routines", span: 1, order: 13, kind: "kpi", perm: "tasks.view_all", component: defineAsyncComponent(() => import("./widgets/RoutinesTodayWidget.vue")) },
    { id: "overview.activity", span: 2, order: 40, kind: "card", component: defineAsyncComponent(() => import("./widgets/ActivityWidget.vue")) },
  ],
  messages: (language) => import(`./i18n/${language}.json`),
});
