import { useCallback, useEffect, useRef } from "react";

import { attachNativeButton, hasNativeButton, updateNativeButton, type NativeButtonKind } from "../telegram";
import { nativeButtonColors } from "../theme";
import { Button } from "./Button";
import { cx } from "./cx";
import type { IconLike } from "./icon";

export type BottomAction = {
  text: string;
  onClick: () => void;
  disabled?: boolean;
  loading?: boolean;
  /** Only for the in-page fallback; Telegram's buttons have no icons. */
  icon?: IconLike;
  /** Telegram's shine on the main button, for the one action that matters. */
  shine?: boolean;
};

/**
 * Drive Telegram's main or secondary button from React state while `action` is set. The press
 * handler always calls the latest `onClick`, and changing text or state never hides the button.
 */
export function useNativeButton(kind: NativeButtonKind, action: BottomAction | null): void {
  const latest = useRef(action);
  latest.current = action;
  const press = useCallback(() => {
    const current = latest.current;
    if (current && !current.disabled && !current.loading) current.onClick();
  }, []);
  const active = action !== null;

  const text = action?.text;
  const disabled = action?.disabled;
  const loading = action?.loading;
  const shine = action?.shine;
  // Settings first, so the button never flashes Telegram's default text when it appears.
  useEffect(() => {
    if (!active || text === undefined) return;
    updateNativeButton(kind, { text, disabled, loading, shine, position: "left", ...nativeButtonColors(kind) });
  }, [kind, active, text, disabled, loading, shine]);

  useEffect(() => {
    if (!active) return;
    return attachNativeButton(kind, press) ?? undefined;
  }, [kind, active, press]);
}

/**
 * The primary (and optional secondary) action of a page or sheet. Inside Telegram it uses the
 * native bottom buttons; elsewhere, or when the client can't draw every button asked for, it
 * renders the in-page action bar. `native={false}` always renders in the page.
 */
export function BottomBar({
  primary,
  secondary,
  native = true,
  className,
}: {
  primary: BottomAction;
  secondary?: BottomAction;
  native?: boolean;
  className?: string;
}) {
  const useNative = native && hasNativeButton("main") && (!secondary || hasNativeButton("secondary"));
  useNativeButton("main", useNative ? primary : null);
  useNativeButton("secondary", useNative && secondary ? secondary : null);
  if (useNative) return null;
  return (
    <div className={cx("action-bar", className)}>
      {secondary && (
        <Button
          variant="secondary"
          size="lg"
          className="ui-bar-secondary"
          icon={secondary.icon}
          disabled={secondary.disabled}
          loading={secondary.loading}
          onClick={secondary.onClick}
        >
          {secondary.text}
        </Button>
      )}
      <Button
        variant="primary"
        size="lg"
        className="ui-bar-primary"
        icon={primary.icon}
        disabled={primary.disabled}
        loading={primary.loading}
        onClick={primary.onClick}
      >
        {primary.text}
      </Button>
    </div>
  );
}
