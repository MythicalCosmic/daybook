/**
 * The knowledge base (plan §13.5, package Q): spaces of how-to pages with a tree, a rich editor,
 * versions, "who has read it" and links to tasks and routines. Everything heavy (pages, the Tiptap
 * editor, widgets) loads on first use; this file stays tiny because it is in the first bundle.
 */
import { Archive, BookOpen, FilePlus2, Search } from "@lucide/vue";
import { defineAsyncComponent } from "vue";

import { defineModule } from "@/core/modules";

import { routes } from "./routes";

export default defineModule({
  id: "knowledge",
  group: "comms",
  order: 40,
  icon: BookOpen,
  title: "knowledge.title",
  hotkey: "k",
  routes,
  nav: [{ key: "spaces", title: "knowledge.title", to: "knowledge" }],
  // apps.knowledge bumps "knowledge.pages" after every change.
  invalidates: ["knowledge"],
  commands: (ctx) => [
    {
      id: "knowledge.new-page",
      title: ctx.t("knowledge.cmd.newPage"),
      icon: FilePlus2,
      perm: "knowledge.manage",
      keywords: ["page", "sahifa", "страница", "sop", "how to", "yo‘riqnoma", "инструкция"],
      run: () => ctx.go("knowledge/new"),
    },
    {
      id: "knowledge.archive",
      title: ctx.t("knowledge.cmd.archive"),
      icon: Archive,
      perm: "knowledge.manage",
      keywords: ["archive", "restore", "arxiv", "tiklash", "архив", "восстановить"],
      run: () => ctx.go("knowledge?archive=1"),
    },
    {
      id: "knowledge.open",
      title: ctx.t("knowledge.cmd.open"),
      icon: Search,
      keywords: ["wiki", "handbook", "qo‘llanma", "база знаний"],
      run: () => ctx.go("knowledge"),
    },
  ],
  searchResults: {
    "knowledge.page": defineAsyncComponent(() => import("./components/SearchHit.vue")),
  },
  widgets: [
    {
      id: "knowledge.reading",
      span: 2,
      order: 70,
      kind: "card",
      perm: "knowledge.manage",
      component: defineAsyncComponent(() => import("./widgets/ReadingWidget.vue")),
    },
  ],
  settings: [
    {
      id: "knowledge",
      title: "knowledge.settings.title",
      perm: "knowledge.manage",
      icon: BookOpen,
      component: defineAsyncComponent(() => import("./components/KnowledgeSettingsPanel.vue")),
    },
  ],
  // The tasks drawer shows "How to do this" for pages linked to the task (package B hosts it).
  extensions: {
    "tasks.drawer.actions": [defineAsyncComponent(() => import("./components/HowToSlot.vue"))],
  },
  // Telegram `startapp=kb_12` opens page 12.
  deepLinks: {
    kb: (argument) => (/^\d+$/.test(argument) ? `knowledge/p/${argument}` : "knowledge"),
  },
  messages: async () => {
    const [uz, ru, en] = await Promise.all([import("./i18n/uz.json"), import("./i18n/ru.json"), import("./i18n/en.json")]);
    return { uz: uz.default, ru: ru.default, en: en.default };
  },
});
