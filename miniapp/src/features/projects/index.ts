/**
 * Projects in the mini app (PLAN-OWNER §13.3, package T): my projects, a phone-shaped board where
 * I drag my own cards between lists, the updates feed, a timer (on the task screen through
 * `task.actions`, in the card sheet, and on Home while it runs) and a "Log time" sheet (also in
 * the (+) sheet). Me → Projects; Home shows the running timer, and my projects at its end.
 * Deep links: `?screen=project:12`, `projects.board:12`, `projects.updates:12`.
 */
import { Clock3, FolderKanban } from "lucide-react";
import { lazy } from "react";

import { isSuspended } from "../../api/membership";
import { useFeatureT } from "../../i18n/feature";
import { defineFeature } from "../registry";
import { useMyProjects } from "./api";
import { ProjectsCard, TimerCard } from "./HomeCards";
import { messages } from "./messages";

export default defineFeature({
  id: "projects",
  messages,
  visible: (member) => member.status === "approved" && !isSuspended(member),
  pages: {
    list: lazy(() => import("./ProjectsPage")),
    board: lazy(() => import("./BoardPage")),
    updates: lazy(() => import("./UpdatesPage")),
  },
  sheets: {
    card: lazy(() => import("./CardSheet")),
    log: lazy(() => import("./LogTimeSheet")),
    update: lazy(() => import("./UpdateSheet")),
  },
  homeCards: [{ id: "timer", component: TimerCard, order: 10 }],
  // An overview, not today's work: after Home's "Up next" rather than above it.
  homeEnd: [{ id: "projects", component: ProjectsCard, order: 60 }],
  // After "How to do this" (knowledge, 10): read how, then time the work. Lazy: only the task
  // screen needs it.
  taskActions: [{ id: "timer", component: lazy(() => import("./TaskTimer")), order: 20 }],
  meItems: [
    {
      id: "projects",
      group: "work",
      label: "me.projects",
      icon: FolderKanban,
      open: { page: "list" },
      order: 30,
      // "11 open": my open cards, the number that asks something of me (a bubble beside a
      // project count read as two unrelated numbers).
      useStatus: ({ member }) => {
        const t = useFeatureT(messages);
        const projects = useMyProjects(member.companyId);
        if (!projects.data) return {};
        const open = projects.data.reduce((sum, project) => sum + project.my_open, 0);
        return { value: open ? t("me.open", { count: open }) : String(projects.data.length) };
      },
    },
  ],
  plusActions: [{ id: "log", label: "plus.log", icon: Clock3, open: { sheet: "log" }, order: 40 }],
  routes: {
    project: { page: "board" },
  },
});
