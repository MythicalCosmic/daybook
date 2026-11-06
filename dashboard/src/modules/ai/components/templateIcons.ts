/**
 * The icons of the New agent dialog's ready jobs (apps.ai.agents.custom_templates names them in
 * lucide's words). Here, not in meta.ts, so only the dialog, which loads on use, carries them.
 */
import { AlarmClock, CalendarCheck, FileClock, Moon, Sparkles, TrendingDown, Trophy, UserCheck, Wallet } from "@lucide/vue";
import type { Component } from "vue";

const TEMPLATE_ICONS: Record<string, Component> = {
  moon: Moon,
  trophy: Trophy,
  "user-check": UserCheck,
  wallet: Wallet,
  "calendar-check": CalendarCheck,
  "file-clock": FileClock,
  "trending-down": TrendingDown,
  "alarm-clock": AlarmClock,
};

export function templateIcon(name: string | null | undefined): Component {
  return (name && TEMPLATE_ICONS[name]) || Sparkles;
}
