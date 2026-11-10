/**
 * AI (briefs/ai-contract.md §5, §7): the agents that work by themselves (voice tasks, the deadline
 * watcher, the morning plan, the photo checker, the HR assistant) with their switches, each with
 * its own page (briefs/v5-agent-page.md: at work in its scene, what it did, its runs and Claude
 * calls, tokens, what comes next, its settings), what they did (live), the voice notes and what
 * they became, and Ask AI over the company's data. "Dictate" and
 * "Smart add" sit in the Tasks New task dialog (`tasks.create.tools`); the dictate dialog and the
 * shell's own Ask AI live in `shell.panel`, and so does Claude's little helper that walks with the
 * person on every page (BuddyCompanion.vue). Not behind the "ai" switch: turning AI on (the Agents
 * page) is what adds it. Pages, the widget, the panel and the dialog load on use.
 */
import { Activity, AudioLines, Bot, MessagesSquare, Mic, Newspaper, Smile, Sparkles, TrendingUp } from "@lucide/vue";
import { defineAsyncComponent } from "vue";

import { defineModule } from "@/core/modules";

import { buddyEverywhere } from "./components/buddyPrefs";
import { openDictation } from "./dictation";
import { routes } from "./routes";

export default defineModule({
  id: "ai",
  group: "work",
  order: 15,
  icon: Sparkles,
  title: "ai.title",
  perm: "dashboard.access",
  routes,
  nav: [
    // Not exact: an agent's own page (ai/agents/<key>) keeps "Agents" lit; the other pages are longer paths and win.
    { key: "agents", title: "ai.nav.agents", to: "ai" },
    { key: "advisor", title: "ai.nav.advisor", to: "ai/advisor", perm: "reports.view" },
    { key: "activity", title: "ai.nav.activity", to: "ai/activity" },
    { key: "voice", title: "ai.nav.voice", to: "ai/voice" },
    { key: "ask", title: "ai.nav.ask", to: "ai/ask", perm: "ai.use" },
  ],
  // apps.ai's pulse key, and apps.briefings' (Maslahatchi's reviews); drafts made into tasks
  // refresh the tasks lists themselves.
  invalidates: ["ai", "briefings"],
  commands: (ctx) => [
    {
      id: "ai.dictate",
      title: ctx.t("ai.cmd.dictate"),
      icon: Mic,
      keywords: ["voice", "ovoz", "голос", "dictate", "aytib", "надиктовать"],
      run: () => openDictation("voice"),
    },
    {
      id: "ai.smart-add",
      title: ctx.t("ai.cmd.smartAdd"),
      icon: Sparkles,
      keywords: ["smart", "aqlli", "умное", "several", "bir nechta", "несколько"],
      run: () => openDictation("text"),
    },
    { id: "ai.buddy", title: ctx.t("ai.cmd.buddy"), icon: Smile, keywords: ["claude", "buddy", "chibi", "yordamchi", "помощник", "mascot"], run: () => (buddyEverywhere.value = !buddyEverywhere.value) },
    { id: "ai.agents", title: ctx.t("ai.cmd.agents"), icon: Bot, keywords: ["agent", "agentlar", "агенты", "ai"], run: () => ctx.go("ai") },
    {
      id: "ai.advisor",
      title: ctx.t("ai.cmd.advisor"),
      icon: TrendingUp,
      perm: "reports.view",
      keywords: ["maslahatchi", "советник", "advisor", "sharh", "обзор", "review", "biznes", "бизнес"],
      run: () => ctx.go("ai/advisor"),
    },
    { id: "ai.activity", title: ctx.t("ai.cmd.activity"), icon: Activity, keywords: ["activity", "faoliyat", "активность"], run: () => ctx.go("ai/activity") },
    { id: "ai.voice", title: ctx.t("ai.cmd.voice"), icon: AudioLines, keywords: ["voice", "ovozli", "голосовые"], run: () => ctx.go("ai/voice") },
    { id: "ai.ask", title: ctx.t("ai.cmd.ask"), icon: MessagesSquare, perm: "ai.use", keywords: ["ask", "so‘rash", "спросить", "chat"], run: () => ctx.go("ai/ask") },
  ],
  widgets: [{ id: "ai.kpi.today", span: 1, order: 33, kind: "kpi", component: defineAsyncComponent(() => import("./widgets/AgentsTodayWidget.vue")) }],
  settings: [
    { id: "ai", title: "ai.settings.title", perm: "ai.configure", order: 10, icon: Sparkles, component: defineAsyncComponent(() => import("./components/AiSettingsPanel.vue")) },
    { id: "ai.briefings", title: "ai.advisor.settings.title", perm: "company.settings", order: 11, icon: Newspaper, component: defineAsyncComponent(() => import("./components/BriefingSettingsForm.vue")) },
  ],
  extensions: {
    "shell.panel": [defineAsyncComponent(() => import("./components/ShellHost.vue")), defineAsyncComponent(() => import("./components/BuddyCompanion.vue"))],
    "tasks.create.tools": [defineAsyncComponent(() => import("./components/NewTaskTools.vue"))],
  },
  // The owner bot's "Edit" (`startapp=draft_41`) opens that voice note; `ai` the agents, and
  // `ai_deadline_watcher` that agent's page.
  deepLinks: {
    draft: (argument) => (/^\d+$/.test(argument) ? `ai/voice?draft=${argument}` : "ai/voice"),
    ai: (argument) => (/^[a-z0-9_]+$/.test(argument) ? `ai/agents/${argument}` : "ai"),
    // `advisor_41`: that business review on Maslahatchi's page.
    advisor: (argument) => (/^\d+$/.test(argument) ? `ai/advisor?review=${argument}` : "ai/advisor"),
  },
  messages: (language) => import(`./i18n/${language}.json`),
});
