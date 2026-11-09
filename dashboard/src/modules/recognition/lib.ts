/** Small helpers of the recognition pages: icons, the person shape PersonCell takes, permissions. */
import {
  Award,
  Brain,
  CalendarCheck,
  CirclePlay,
  ClipboardCheck,
  Flame,
  GraduationCap,
  HandHeart,
  HandHelping,
  Heart,
  HeartHandshake,
  Library,
  Lightbulb,
  ShieldCheck,
  Star,
  Sunrise,
  Target,
  Trophy,
  Users,
  Zap,
} from "@lucide/vue";
import type { Component } from "vue";

import type { KudosBadge, RecPerson } from "./types";

/** Who reads the recognition pages; changing needs recognition.manage. */
export const READ = ["members.view", "learning.view", "recognition.manage"] as const;
export const MANAGE = "recognition.manage" as const;

const BADGE_ICONS: Record<string, Component> = {
  "circle-play": CirclePlay,
  "clipboard-check": ClipboardCheck,
  target: Target,
  "graduation-cap": GraduationCap,
  library: Library,
  flame: Flame,
  lightbulb: Lightbulb,
  brain: Brain,
  sunrise: Sunrise,
  "hand-heart": HandHeart,
  "heart-handshake": HeartHandshake,
  "calendar-check": CalendarCheck,
  trophy: Trophy,
};

export const badgeIcon = (name: string): Component => BADGE_ICONS[name] ?? Award;

export const KUDOS_BADGES: readonly { key: KudosBadge; icon: Component }[] = [
  { key: "thanks", icon: Heart },
  { key: "teamwork", icon: Users },
  { key: "fast", icon: Zap },
  { key: "careful", icon: ShieldCheck },
  { key: "helpful", icon: HandHelping },
  { key: "star", icon: Star },
];

export const kudosIcon = (key: string): Component => KUDOS_BADGES.find((badge) => badge.key === key)?.icon ?? Heart;

/** The shape PersonCell and the avatars take. */
export const personRef = (person: RecPerson) => ({ id: person.id, name: person.name, photo_url: person.avatar_url });

/** ISO date (YYYY-MM-DD) of `day` moved by whole weeks or months. */
export function shiftDay(day: string, period: "week" | "month", steps: number): string {
  const [year, month, date] = day.split("-").map(Number) as [number, number, number];
  const moved = period === "week" ? new Date(Date.UTC(year, month - 1, date + 7 * steps)) : new Date(Date.UTC(year, month - 1 + steps, 1));
  return moved.toISOString().slice(0, 10);
}
