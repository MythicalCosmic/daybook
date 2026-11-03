/**
 * A row for things with a long story (a fine's reason, a document's number and end date, a
 * record's category and day): the title and an optional amount on the first line, the details
 * across the whole row under them, and small chips last, so nothing is squeezed beside a badge.
 */
import { ChevronRight } from "lucide-react";
import type { ReactNode } from "react";

import { cx } from "../ui";
import { renderIcon, type IconLike } from "../ui/icon";
import "./states.css";

export function EntryRow({
  icon,
  tone = "plain",
  title,
  aside,
  details = [],
  chips,
  onOpen,
  className,
}: {
  icon: IconLike;
  tone?: "plain" | "accent" | "sage";
  title: ReactNode;
  /** On the title's line, at the right: an amount. */
  aside?: ReactNode;
  /** Lines under the title (empty ones are left out). */
  details?: (ReactNode | null | false | undefined)[];
  /** Badges under the details. */
  chips?: ReactNode;
  onOpen: () => void;
  className?: string;
}) {
  return (
    <button type="button" className={cx("row ft-entry", className)} onClick={onOpen}>
      <span className={cx("circle ui-row-icon", tone !== "plain" && `ui-row-icon--${tone}`)}>{renderIcon(icon, 19)}</span>
      <span className="row-main">
        <span className="ft-entry-head">
          <span className="row-title">{title}</span>
          {aside}
        </span>
        {details.filter(Boolean).map((line, index) => (
          <span key={index} className="row-meta ft-entry-detail">
            {line}
          </span>
        ))}
        {chips && <span className="ft-entry-chips">{chips}</span>}
      </span>
      <ChevronRight className="ui-row-chevron" size={19} strokeWidth={2.5} aria-hidden />
    </button>
  );
}
