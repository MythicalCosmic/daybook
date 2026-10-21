/**
 * Projects (plan §13.3, package T): the Trello part. Boards per project with lists, WIP limits and
 * drag and drop, a timeline, milestones, people and their load, time, money, updates and files;
 * a roadmap across projects. Entry from core/catalog.ts (work group, order 20, hotkey j).
 * Everything heavy loads lazily: this file is in the first bundle (two icons only).
 */
import { FolderKanban, FolderPlus } from "@lucide/vue";
import { defineAsyncComponent } from "vue";

import { defineModule } from "@/core/modules";

import { routes } from "./routes";

export default defineModule({
  id: "projects",
  group: "work",
  order: 20,
  icon: FolderKanban,
  title: "projects.title",
  hotkey: "j",
  routes,
  nav: [
    { key: "all", title: "projects.nav.all", to: "projects", exact: false },
    { key: "roadmap", title: "projects.nav.roadmap", to: "projects/roadmap", exact: true },
  ],
  // apps.projects bumps "projects.projects" (boards, index, roadmap) and "projects.time".
  invalidates: ["projects"],
  commands: (ctx) => [
    {
      id: "projects.new",
      title: ctx.t("projects.cmd.new"),
      icon: FolderPlus,
      keywords: ["project", "loyiha", "проект", "board"],
      perm: "projects.manage",
      run: () => ctx.go("projects?new=1"),
    },
    {
      id: "projects.roadmap",
      title: ctx.t("projects.cmd.roadmap"),
      icon: FolderKanban,
      keywords: ["roadmap", "timeline", "gantt", "yo‘l xaritasi", "дорожная карта"],
      run: () => ctx.go("projects/roadmap"),
    },
    {
      id: "projects.mine",
      title: ctx.t("projects.cmd.mine"),
      icon: FolderKanban,
      keywords: ["my projects", "mening loyihalarim", "мои проекты"],
      run: () => ctx.go("projects?mine=1"),
    },
  ],
  searchResults: {
    "projects.project": defineAsyncComponent(() => import("./components/ProjectHit.vue")),
  },
  widgets: [
    { id: "projects.atRisk", span: 2, order: 50, kind: "card", component: defineAsyncComponent(() => import("./widgets/AtRiskWidget.vue")) },
    { id: "projects.mine", span: 2, order: 55, kind: "card", component: defineAsyncComponent(() => import("./widgets/MyProjectsWidget.vue")) },
  ],
  settings: [
    {
      id: "projects",
      title: "projects.settings.title",
      perm: ["projects.manage", "company.settings"],
      order: 60,
      icon: FolderKanban,
      component: defineAsyncComponent(() => import("./components/ProjectSettingsPanel.vue")),
    },
  ],
  // Telegram `startapp=project_12` opens that project's board.
  deepLinks: {
    project: (argument) => (/^\d+$/.test(argument) ? `projects/${argument}` : "projects"),
  },
  messages: (language) => import(`./i18n/${language}.json`),
});
