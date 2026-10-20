import type { LucideIcon } from "lucide-react";
import { createElement, isValidElement, type ReactElement } from "react";

/** An icon prop: a lucide component (drawn at the primitive's size) or a ready element. */
export type IconLike = LucideIcon | ReactElement;

export function renderIcon(icon: IconLike | undefined, size: number, strokeWidth = 2.4): ReactElement | null {
  if (!icon) return null;
  if (isValidElement(icon)) return icon;
  return createElement(icon, { size, strokeWidth, "aria-hidden": true });
}
