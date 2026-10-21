/**
 * Projects in the mini app (PLAN-OWNER §13.3, package T): my projects, a phone-shaped board where
 * I drag my own cards between lists, the updates feed, a timer (on the task screen through
 * `task.actions`, in the card sheet, and on Home while it runs) and a "Log time" sheet (also in
 * the (+) sheet). Me → Projects; Home shows my projects and the running timer.
 * Deep links: `?screen=project:12`, `projects.board:12`, `projects.updates:12`.
 */
import { Clock3, FolderKanban } from "lucide-react";
import { lazy } from "react";

import { isSuspended } from "../../api/membership";
import { defineFeature } from "../registry";
import { useMyProjects } from "./api";
import { ProjectsCard, TimerCard } from "./HomeCards";
import { messages } from "./messages";
import { TaskTimer } from "./Timer";

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
  homeCards: [
    { id: "timer", component: TimerCard, order: 10 },
    { id: "projects", component: ProjectsCard, order: 60 },
  ],
  // After "How to do this" (knowledge, 10): read how, then time the work.
  taskActions: [{ id: "timer", component: TaskTimer, order: 20 }],
  meItems: [
    {
      id: "projects",
      group: "work",
      label: "me.projects",
      icon: FolderKanban,
      open: { page: "list" },
      order: 30,
      useStatus: ({ member }) => {
        const projects = useMyProjects(member.companyId);
        const open = (projects.data ?? []).reduce((sum, project) => sum + project.my_open, 0);
        return { value: projects.data ? String(projects.data.length) : undefined, badge: open || null };
      },
    },
  ],
  plusActions: [{ id: "log", label: "plus.log", icon: Clock3, open: { sheet: "log" }, order: 40 }],
  routes: {
    project: { page: "board" },
  },
});
