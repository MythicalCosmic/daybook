/**
 * Recognition in the mini app (docs/PLAN-LEARNING.md §7, §12.2, package R): points, the ten
 * levels, badges, the learning streak, the leaderboard and thanks between colleagues, on the
 * employee endpoints of `backend/apps/recognition/api.py`.
 *
 * Home: the chip under the greeting (level, this week's points, the streak's flame), which also
 * opens the celebration for a new level or badge, and a card when someone thanked the person
 * today. Me: "My achievements" and "Thanks". (+): "Say thanks". A task done on time gets a small
 * burst of confetti (`celebrateTaskDone`, called from the app's done handler). Only while the
 * company runs recognition.
 *
 * Deep links: `achievements`, `leaderboard`, `kudos` (the thanks), `thank:<member id>` (the
 * sheet with that colleague picked: the bot's "Say thanks back"), `thank` (the sheet).
 */
import { HeartHandshake, Trophy } from "lucide-react";
import { lazy } from "react";

import { hasModule } from "../../api/membership";
import { defineFeature, type SlotProps } from "../registry";
import { useRecognitionMe } from "./api";
import { HeroChip } from "./HeroChip";
import { messages } from "./messages";
import { ThankedCard } from "./ThankedCard";

function useAchievementsStatus({ member }: SlotProps) {
  const me = useRecognitionMe(member.companyId);
  const data = me.data;
  if (!data) return {};
  return { value: data.enabled ? data.level.name : undefined, badge: data.unseen.length || null };
}

function useKudosStatus({ member }: SlotProps) {
  const me = useRecognitionMe(member.companyId);
  return { badge: (me.data?.kudos_today ?? []).filter((row) => !row.seen).length || null };
}

function useKudosOn({ member }: SlotProps) {
  return !!useRecognitionMe(member.companyId).data?.kudos_enabled;
}

export default defineFeature({
  id: "recognition",
  messages,
  visible: (member) => member.status === "approved" && hasModule(member, "recognition"),
  pages: {
    achievements: lazy(() => import("./AchievementsPage")),
    leaderboard: lazy(() => import("./LeaderboardPage")),
    kudos: lazy(() => import("./KudosPage")),
  },
  sheets: {
    kudos: lazy(() => import("./KudosSheet")),
    celebrate: lazy(() => import("./CelebrationSheet")),
  },
  // Under the check-in (10) and the till (20): what to do first, then how it's going.
  homeHero: [{ id: "chip", component: HeroChip, order: 30 }],
  homeCards: [{ id: "thanked", component: ThankedCard, order: 45 }],
  meItems: [
    { id: "achievements", group: "work", label: "me.achievements", icon: Trophy, open: { page: "achievements" }, order: 5, useStatus: useAchievementsStatus },
    { id: "kudos", group: "team", label: "me.kudos", icon: HeartHandshake, open: { page: "kudos" }, order: 40, useStatus: useKudosStatus },
  ],
  plusActions: [{ id: "thank", label: "plus.thank", icon: HeartHandshake, open: { sheet: "kudos" }, order: 60, useVisible: useKudosOn }],
  routes: {
    achievements: { page: "achievements", tab: "profile" },
    leaderboard: { page: "leaderboard", tab: "profile" },
    kudos: { page: "kudos", tab: "profile" },
    thank: { sheet: "kudos", param: "to" },
  },
});
