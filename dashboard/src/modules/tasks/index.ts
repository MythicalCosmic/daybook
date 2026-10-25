/**
 * Tasks (plan §6.1, package B): every task as a table, board and calendar, reviews with large
 * proof photos, the photo wall, the Person 360 tab and the Overview widgets. Kept tiny: pages,
 * widgets and the API load on use.
 */
import { AlarmClock, Camera, ClipboardCheck, ListChecks, Plus } from "@lucide/vue";
import { defineAsyncComponent } from "vue";

import { defineModule } from "@/core/modules";
import { counter } from "@/core/pulse";

import { routes } from "./routes";

export default defineModule({
  id: "tasks",
  group: "work",
  order: 10,
  icon: ListChecks,
  title: "tasks.title",
  perm: ["tasks.view_all", "tasks.confirm", "tasks.assign"],
  hotkey: "t",
  routes,
  nav: [
    { key: "all", title: "tasks.nav.all", to: "tasks", perm: "tasks.view_all", exact: true },
    { key: "reviews", title: "tasks.nav.reviews", to: "tasks/reviews", perm: ["tasks.confirm", "tasks.view_all", "tasks.assign"], badge: counter("tasks.review") },
    { key: "photos", title: "tasks.nav.photos", to: "tasks/photos", perm: "tasks.view_all" },
  ],
  badge: counter("tasks.review"),
  // apps.tasks' pulse keys: tasks.tasks (any task saved), tasks.review, tasks.late_now.
  invalidates: ["tasks"],
  commands: (ctx) => [
    {
      id: "tasks.new",
      title: ctx.t("tasks.cmd.new"),
      icon: Plus,
      shortcut: ["N"],
      keywords: ["task", "vazifa", "задача", "new", "yangi"],
      perm: "tasks.assign",
      run: () => ctx.go("tasks?new=1"),
    },
    {
      id: "tasks.reviews",
      title: ctx.t("tasks.cmd.reviews"),
      icon: ClipboardCheck,
      keywords: ["check", "tekshirish", "проверка", "review"],
      perm: ["tasks.confirm", "tasks.view_all"],
      run: () => ctx.go("tasks/reviews"),
    },
    {
      id: "tasks.late",
      title: ctx.t("tasks.cmd.late"),
      icon: AlarmClock,
      keywords: ["late", "kechikkan", "просрочено", "overdue"],
      perm: "tasks.view_all",
      run: () => ctx.go("tasks?sv=late&overdue=true"),
    },
    {
      id: "tasks.photos",
      title: ctx.t("tasks.cmd.photos"),
      icon: Camera,
      keywords: ["photo", "rasm", "фото", "proof"],
      perm: "tasks.view_all",
      run: () => ctx.go("tasks/photos"),
    },
  ],
  widgets: [
    { id: "tasks.kpi.done_today", span: 1, order: 10, kind: "kpi", perm: "tasks.view_all", component: defineAsyncComponent(() => import("./widgets/DoneTodayWidget.vue")) },
    { id: "tasks.kpi.on_time", span: 1, order: 11, kind: "kpi", perm: "tasks.view_all", component: defineAsyncComponent(() => import("./widgets/OnTimeWidget.vue")) },
    { id: "tasks.kpi.late_now", span: 1, order: 12, kind: "kpi", perm: "tasks.view_all", component: defineAsyncComponent(() => import("./widgets/LateNowWidget.vue")) },
    { id: "tasks.chart.on_time_trend", span: 2, order: 40, kind: "chart", perm: "tasks.view_all", component: defineAsyncComponent(() => import("./widgets/OnTimeTrendWidget.vue")) },
    { id: "tasks.branches_now", span: 2, order: 39, kind: "card", perm: "tasks.view_all", component: defineAsyncComponent(() => import("./widgets/BranchesNowWidget.vue")) },
    { id: "tasks.top_bottom", span: 2, order: 41, kind: "card", perm: "reports.view", component: defineAsyncComponent(() => import("./widgets/TopBottomWidget.vue")) },
  ],
  settings: [
    { id: "tasks", title: "tasks.settings.title", perm: "company.settings", order: 15, icon: ListChecks, component: defineAsyncComponent(() => import("./components/TasksSettingsPanel.vue")) },
  ],
  personTabs: [
    { id: "tasks", title: "tasks.person.title", perm: "tasks.view_all", order: 20, component: defineAsyncComponent(() => import("./components/PersonTasksTab.vue")) },
  ],
  // Telegram `startapp=task_345` opens the task, `reviews` the checks waiting.
  deepLinks: {
    task: (argument) => (/^\d+$/.test(argument) ? `tasks?task=${argument}` : "tasks"),
    reviews: () => "tasks/reviews",
  },
  messages: (language) => import(`./i18n/${language}.json`),
});
