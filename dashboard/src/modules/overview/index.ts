/**
 * The Overview (plan §6.1 "(index)", §6.2): W0's placeholder, handed to package N in Wave 3. It
 * serves `/c/:companyId` (`index: true`), hosts the `overview.hero` slot and renders every
 * module's registered widgets. Its own two widgets read W0 endpoints: branch cards
 * (`branches/today/`) and the activity stream (`stream/`).
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
    { id: "overview.activity", span: 2, order: 40, kind: "card", component: defineAsyncComponent(() => import("./widgets/ActivityWidget.vue")) },
  ],
  messages: (language) => import(`./i18n/${language}.json`),
});
