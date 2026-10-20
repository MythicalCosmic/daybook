/**
 * "Get started" and "New company" (plan §6.1–§6.2, §13.2, package A). No sidebar row: the
 * progress pill sits at the top of the sidebar (`shell.nav.top`) until the checklist is done or
 * dismissed, an Overview card shows the next step, and the switcher's "New company" dialog body is
 * `shell.company.create`. Steps come from the backend's setup registry (`setup/`).
 */
import { Rocket } from "@lucide/vue";
import { defineAsyncComponent } from "vue";

import { defineModule } from "@/core/modules";

export default defineModule({
  id: "setup",
  group: "overview",
  order: 90,
  icon: Rocket,
  title: "setup.title",
  routes: [
    {
      path: "get-started",
      name: "setup.page",
      component: () => import("./pages/GetStartedPage.vue"),
      meta: { title: "setup.title" },
    },
  ],
  nav: [],
  // A step turns done when settings, branches, modules or groups change (any dashboard).
  invalidates: ["companies", "groups"],
  extensions: {
    "shell.nav.top": [defineAsyncComponent(() => import("./components/SetupPill.vue"))],
    "shell.company.create": [defineAsyncComponent(() => import("./components/NewCompanyForm.vue"))],
  },
  widgets: [
    {
      id: "setup.progress",
      span: 2,
      order: 5,
      kind: "card",
      component: defineAsyncComponent(() => import("./widgets/SetupWidget.vue")),
    },
  ],
  // "New company" is the shell's own palette action (it opens this module's dialog body).
  commands: (ctx) => [
    { id: "setup.open", title: ctx.t("setup.cmd.open"), icon: Rocket, keywords: ["setup", "boshlash", "начало", "checklist"], run: () => ctx.go("get-started") },
  ],
  deepLinks: {
    setup: () => "get-started",
  },
  messages: async () => {
    const [uz, ru, en] = await Promise.all([import("./i18n/uz.json"), import("./i18n/ru.json"), import("./i18n/en.json")]);
    return { uz: uz.default, ru: ru.default, en: en.default };
  },
});
