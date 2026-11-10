/**
 * Egasi paneli, the owner's cockpit (v11, apps.insights): first in the sidebar for owners and
 * those who may see finance or reports, and the owner's landing page after sign-in (the route's
 * `ownerLanding`). One page, `owner`, built from `GET cockpit/`; the Insights settings panel.
 * Telegram's "Open" on an urgent insight lands here with `?insight=<id>`.
 */
import { Crown, Sparkles } from "@lucide/vue";
import { defineAsyncComponent } from "vue";

import { defineModule } from "@/core/modules";

const READ = ["finance.view", "reports.view"] as const;

export default defineModule({
  id: "cockpit",
  group: "overview",
  order: 5,
  icon: Crown,
  title: "cockpit.title",
  perm: [...READ],
  hotkey: "e",
  routes: [
    {
      path: "owner",
      name: "cockpit.owner",
      component: () => import("./pages/CockpitPage.vue"),
      meta: { title: "cockpit.title", perm: [...READ], ownerLanding: true },
    },
  ],
  // Money, decisions and insights: any of their apps moving refreshes the page.
  invalidates: ["insights", "finance", "console.queue", "members.pending", "timeoff", "attendance", "payroll", "inventory", "sales", "companies.branches"],
  settings: [
    {
      id: "insights",
      title: "cockpit.settings.title",
      perm: ["ai.configure", "company.settings"],
      order: 59,
      icon: Sparkles,
      component: defineAsyncComponent(() => import("./components/InsightSettingsPanel.vue")),
    },
  ],
  deepLinks: { owner: () => "owner" },
  messages: (language) => import(`./i18n/${language}.json`),
});
