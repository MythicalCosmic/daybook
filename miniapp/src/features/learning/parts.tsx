/** Small pieces the learning screens share. */
import { GraduationCap, type LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { samePage, useNavigation, type Navigation, type Params } from "../../state/navigation";
import { haptic } from "../../telegram";
import { Button, cx, type IconLike } from "../../ui";
import { renderIcon } from "../../ui/icon";
import { hueClass } from "./lib";
import type { CourseCard, TopicRef } from "./types";

/** A course's mark: the owner's emoji on its colour, or a mortarboard when it has none. */
export function CourseTile({ course, size = "md" }: { course: Pick<CourseCard, "emoji" | "color">; size?: "md" | "lg" }) {
  return (
    <span className={cx("lrn-tile", size === "lg" && "lrn-tile--lg", hueClass(course.color))} aria-hidden>
      {course.emoji || <GraduationCap size={size === "lg" ? 26 : 21} strokeWidth={2.3} />}
    </span>
  );
}

/** Topic chips under a lesson, in their palette colours. */
export function TopicChips({ topics }: { topics: readonly TopicRef[] }) {
  if (!topics.length) return null;
  return (
    <div className="lrn-topics">
      {topics.map((topic) => (
        <span key={topic.id} className={cx("lrn-topic", hueClass(topic.color))}>
          {topic.name}
        </span>
      ))}
    </div>
  );
}

/** What stands where the video would be when it can't play yet (or at all). */
export function PlayerState({
  icon,
  title,
  body,
  action,
  tone = "plain",
}: {
  icon: LucideIcon;
  title: ReactNode;
  body?: ReactNode;
  action?: { label: string; onClick: () => void; icon?: IconLike };
  tone?: "plain" | "accent";
}) {
  return (
    <div className={cx("lrn-player-state", tone === "accent" && "lrn-player-state--accent")} role="status">
      <span className="lrn-player-state-icon">{renderIcon(icon, 26, 2.3)}</span>
      <span className="lrn-player-state-title">{title}</span>
      {body && <span className="lrn-player-state-body">{body}</span>}
      {action && (
        <Button variant="secondary" icon={action.icon} onClick={action.onClick}>
          {action.label}
        </Button>
      )}
    </div>
  );
}

/** Whether this page is the one in front (pages under it stay mounted, covered). */
export function useIsTop(feature: string, page: string, params: Params): boolean {
  const navigation = useNavigation();
  return samePage(navigation.top ?? undefined, { feature, page, params });
}

/** Back to the course a step was opened from: the page under this one, or the course afresh. */
export function backToCourse(navigation: Navigation, course: number): void {
  haptic.select();
  const below = navigation.stack.at(-2);
  if (below && below.feature === "learning" && below.page === "course" && Number(below.params?.id) === course) navigation.pop();
  else navigation.replace({ feature: "learning", page: "course", params: { id: course } });
}

/** The number params a learning page was opened with (`course`, `assignment`, `entry`), or null. */
export function numberParam(params: Params, name: string): number | null {
  const value = Number(params[name]);
  return Number.isFinite(value) && value > 0 ? value : null;
}
