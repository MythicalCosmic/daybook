/**
 * Small pieces the recognition screens share: the badge medal (bronze, silver or gold, earned or
 * still to earn), the level ring, the kudos badges, and the celebration when a task is done on
 * time.
 */
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
  Lock,
  ShieldCheck,
  Star,
  Sunrise,
  Target,
  Trophy,
  Users,
  Zap,
  type LucideIcon,
} from "lucide-react";

import { hasModule } from "../../api/membership";
import type { Task } from "../../api/types";
import { useFeatureT } from "../../i18n/feature";
import type { Member } from "../../state/session";
import { celebrate, cx } from "../../ui";
import type { KudosBadge, Tier } from "./api";
import { messages } from "./messages";

export const useRecognitionT = () => useFeatureT(messages);

/** The catalogue's icon names (apps/recognition/badges.py) as lucide components. */
const BADGE_ICONS: Record<string, LucideIcon> = {
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

export const badgeIcon = (name: string): LucideIcon => BADGE_ICONS[name] ?? Award;

/** What a colleague can be thanked for, in the order the sheet offers them. */
export const KUDOS_BADGES: readonly { key: KudosBadge; icon: LucideIcon }[] = [
  { key: "thanks", icon: Heart },
  { key: "teamwork", icon: Users },
  { key: "fast", icon: Zap },
  { key: "careful", icon: ShieldCheck },
  { key: "helpful", icon: HandHelping },
  { key: "star", icon: Star },
];

export const kudosIcon = (key: string): LucideIcon => KUDOS_BADGES.find((badge) => badge.key === key)?.icon ?? Heart;

/** A round medal: the badge's icon on its tier's metal; still to earn, it is a quiet outline. */
export function Medal({ icon, tier, locked = false, size = 56, pop = false }: { icon: string; tier: Tier; locked?: boolean; size?: number; pop?: boolean }) {
  const Icon = badgeIcon(icon);
  return (
    <span className={cx("rcg-medal", `rcg-medal--${tier}`, locked && "rcg-medal--locked", pop && "rcg-medal--pop")} style={{ width: size, height: size }} aria-hidden>
      <Icon size={Math.round(size * 0.44)} strokeWidth={2.2} />
      {locked && (
        <span className="rcg-medal-lock">
          <Lock size={Math.max(11, Math.round(size * 0.2))} strokeWidth={2.6} />
        </span>
      )}
    </span>
  );
}

/** The level number inside a thin ring that fills towards the next level. */
export function LevelRing({ number, share, size = 34, stroke = 3.5 }: { number: number; share: number; size?: number; stroke?: number }) {
  const radius = (size - stroke) / 2 - 0.5;
  const circumference = 2 * Math.PI * radius;
  const filled = Math.min(1, Math.max(0, share));
  const center = size / 2;
  return (
    <span className="rcg-level-ring" style={{ width: size, height: size }} aria-hidden>
      <svg viewBox={`0 0 ${size} ${size}`} width={size} height={size}>
        <circle cx={center} cy={center} r={radius} fill="none" className="rcg-level-ring-track" strokeWidth={stroke} />
        <circle
          cx={center}
          cy={center}
          r={radius}
          fill="none"
          className="rcg-level-ring-value"
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={circumference * (1 - filled)}
          transform={`rotate(-90 ${center} ${center})`}
        />
      </svg>
      <span className="rcg-level-ring-number num" style={{ fontSize: Math.round(size * 0.42) }}>
        {number}
      </span>
    </span>
  );
}

/** How far a total has come from its level's start to the next one (1 at the top level). */
export function levelShare(points: number, level: { starts_at: number; next_at: number | null }): number {
  if (level.next_at === null) return 1;
  const span = level.next_at - level.starts_at;
  return span > 0 ? (points - level.starts_at) / span : 1;
}

/**
 * A task finished by its deadline gets a small burst of confetti (the done path already buzzes,
 * so none here). Only shared work, as for its points: routine work and tasks given by someone;
 * nothing while the company doesn't run recognition. Called from the app's one done handler
 * (`useDoneToast` in lib/actions.ts).
 */
export function celebrateTaskDone(member: Member, task: Pick<Task, "kind" | "status" | "due_at"> & { completed_at?: string | null }): boolean {
  if (!hasModule(member, "recognition") || task.kind === "personal") return false;
  if (task.status !== "done" && task.status !== "review") return false;
  if (!task.due_at || !task.completed_at || Date.parse(task.completed_at) > Date.parse(task.due_at)) return false;
  const point = typeof window === "undefined" ? null : { x: window.innerWidth / 2, y: Math.max(120, window.innerHeight - 110) };
  celebrate({ from: point, pieces: 36, haptic: null });
  return true;
}
