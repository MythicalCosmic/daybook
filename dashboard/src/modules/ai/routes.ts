/** Routes of the AI section, children of /c/:companyId (briefs/ai-contract.md §7). Pages load lazily. */
import type { RouteRecordRaw } from "vue-router";

export const routes: RouteRecordRaw[] = [
  {
    path: "ai",
    name: "ai.agents",
    component: () => import("./pages/AgentsPage.vue"),
    meta: { title: "ai.agents.title" },
  },
  {
    path: "ai/activity",
    name: "ai.activity",
    component: () => import("./pages/ActivityPage.vue"),
    meta: { title: "ai.activity.title" },
  },
  {
    path: "ai/voice",
    name: "ai.voice",
    component: () => import("./pages/VoiceNotesPage.vue"),
    meta: { title: "ai.voice.title" },
  },
  {
    path: "ai/ask",
    name: "ai.ask",
    component: () => import("./pages/AskPage.vue"),
    meta: { title: "ai.chat.title", perm: "ai.use" },
  },
];
