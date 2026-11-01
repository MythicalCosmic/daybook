/**
 * AI (briefs/ai-contract.md §5, §7): the agents that work by themselves (voice tasks, the deadline
 * watcher, the morning plan, the photo checker) with their switches and settings, what they did
 * (live), the voice notes and what they became, and Ask AI over the company's data. "Dictate" and
 * "Smart add" sit in the Tasks New task dialog (`tasks.create.tools`); the dictate dialog and the
 * shell's own Ask AI live in `shell.panel`. Not behind the "ai" switch: turning AI on (the Agents
 * page) is what adds it. Pages, the widget, the panel and the dialog load on use.
 */
import { Activity, AudioLines, Bot, MessagesSquare, Mic, Sparkles } from "@lucide/vue";
import { defineAsyncComponent } from "vue";

import { defineModule } from "@/core/modules";

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
    { key: "agents", title: "ai.nav.agents", to: "ai", exact: true },
    { key: "activity", title: "ai.nav.activity", to: "ai/activity" },
    { key: "voice", title: "ai.nav.voice", to: "ai/voice" },
    { key: "ask", title: "ai.nav.ask", to: "ai/ask", perm: "ai.use" },
  ],
  // apps.ai's pulse key; drafts made into tasks refresh the tasks lists themselves.
  invalidates: ["ai"],
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
    { id: "ai.agents", title: ctx.t("ai.cmd.agents"), icon: Bot, keywords: ["agent", "agentlar", "агенты", "ai"], run: () => ctx.go("ai") },
    { id: "ai.activity", title: ctx.t("ai.cmd.activity"), icon: Activity, keywords: ["activity", "faoliyat", "активность"], run: () => ctx.go("ai/activity") },
    { id: "ai.voice", title: ctx.t("ai.cmd.voice"), icon: AudioLines, keywords: ["voice", "ovozli", "голосовые"], run: () => ctx.go("ai/voice") },
    { id: "ai.ask", title: ctx.t("ai.cmd.ask"), icon: MessagesSquare, perm: "ai.use", keywords: ["ask", "so‘rash", "спросить", "chat"], run: () => ctx.go("ai/ask") },
  ],
  widgets: [{ id: "ai.kpi.today", span: 1, order: 33, kind: "kpi", component: defineAsyncComponent(() => import("./widgets/AgentsTodayWidget.vue")) }],
  settings: [{ id: "ai", title: "ai.settings.title", perm: "ai.configure", order: 10, icon: Sparkles, component: defineAsyncComponent(() => import("./components/AiSettingsPanel.vue")) }],
  extensions: {
    "shell.panel": [defineAsyncComponent(() => import("./components/ShellHost.vue"))],
    "tasks.create.tools": [defineAsyncComponent(() => import("./components/NewTaskTools.vue"))],
  },
  // The owner bot's "Edit" (`startapp=draft_41`) opens that voice note; `ai` the agents.
  deepLinks: {
    draft: (argument) => (/^\d+$/.test(argument) ? `ai/voice?draft=${argument}` : "ai/voice"),
    ai: () => "ai",
  },
  messages: (language) => import(`./i18n/${language}.json`),
});
