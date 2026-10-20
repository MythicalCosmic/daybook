import { nameInitials } from "../lib/team";
import { cx } from "./cx";

export type AvatarSize = "xs" | "sm" | "md" | "lg" | "xl";

/**
 * A round photo, or initials on sage when there is none. Sizes: xs 28, sm 34 (comments),
 * md 40 (people rows), lg 64 (profile), xl 88.
 */
export function Avatar({
  name,
  src,
  size = "md",
  tone = "sage",
  className,
}: {
  name: string;
  src?: string | null;
  size?: AvatarSize;
  tone?: "sage" | "accent" | "neutral";
  className?: string;
}) {
  return (
    <span
      className={cx("avatar", `avatar--${size}`, tone !== "sage" && `avatar--${tone}`, className)}
      role={src ? undefined : "img"}
      aria-label={src ? undefined : name}
    >
      {src ? <img src={src} alt={name} loading="lazy" /> : nameInitials(name)}
    </span>
  );
}

/** Overlapping avatars for a group (project members, who has read a page), with "+3". */
export function AvatarStack({
  people,
  max = 4,
  size = "sm",
}: {
  people: readonly { name: string; src?: string | null }[];
  max?: number;
  size?: AvatarSize;
}) {
  const shown = people.slice(0, max);
  const rest = people.length - shown.length;
  return (
    <span className={cx("ui-avatars", `ui-avatars--${size}`)}>
      {shown.map((person, index) => (
        <Avatar key={`${person.name}-${index}`} name={person.name} src={person.src} size={size} />
      ))}
      {rest > 0 && <span className={cx("avatar", `avatar--${size}`, "avatar--neutral", "ui-avatars-more")}>+{rest}</span>}
    </span>
  );
}
