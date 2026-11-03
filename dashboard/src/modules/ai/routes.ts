/** Routes of the AI section, children of /c/:companyId (briefs/ai-contract.md §7). Pages load lazily. */
import type { RouteLocationNormalized, RouteLocationRaw, RouteRecordRaw } from "vue-router";

/**
 * An agent used to open in a drawer over the Agents page (`ai?agent=deadline_watcher`); it has its
 * own page now (briefs/v5-agent-page.md), so links saved or sent the old way land there.
 */
export function agentDrawerRedirect(to: Pick<RouteLocationNormalized, "params" | "query">): RouteLocationRaw | true {
  const key = to.query.agent;
  if (typeof key !== "string" || !/^[a-z0-9_]+$/.test(key)) return true;
  const { agent: _drawer, ...query } = to.query;
  return { name: "ai.agent", params: { companyId: String(to.params.companyId), key }, query, replace: true };
}

export const routes: RouteRecordRaw[] = [
  {
    path: "ai",
    name: "ai.agents",
    component: () => import("./pages/AgentsPage.vue"),
    meta: { title: "ai.agents.title" },
    beforeEnter: agentDrawerRedirect,
  },
  {
    path: "ai/agents/:key",
    name: "ai.agent",
    component: () => import("./pages/AgentPage.vue"),
    meta: { title: "ai.agent.title" },
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
