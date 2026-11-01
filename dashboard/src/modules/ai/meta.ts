/** Icons for what the AI endpoints name by key: agents (lucide names), sources and levels. */
import { AlarmClock, Bot, LayoutDashboard, Mic, ScanEye, Send, Smartphone, Sparkles, Sunrise, UserRoundCog } from "@lucide/vue";
import type { Component } from "vue";

import type { DraftSource } from "./types";

/** The agents' lucide names (contract §3) and a few likely newcomers; anything else gets a robot. */
const AGENT_ICONS: Record<string, Component> = {
  mic: Mic,
  "alarm-clock": AlarmClock,
  sunrise: Sunrise,
  "scan-eye": ScanEye,
  sparkles: Sparkles,
  bot: Bot,
};

export function agentIcon(name: string | null | undefined): Component {
  return (name && AGENT_ICONS[name]) || Bot;
}

export const SOURCE_ICON: Record<DraftSource, Component> = {
  bot: Send,
  owner_bot: UserRoundCog,
  miniapp: Smartphone,
  dashboard: LayoutDashboard,
};
