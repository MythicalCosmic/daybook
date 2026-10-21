import { useEffect, useLayoutEffect, useRef } from "react";

import { attachNativeButton, hasNativeButton, updateNativeButton, type NativeButtonKind, type NativeButtonLook } from "../telegram";
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
 * Telegram has one main and one secondary button, but a page and a sheet over it may both want
 * them. The newest owner drives the button; when it goes away the one below gets it back.
 */
type Owner = { look: () => NativeButtonLook | null; press: () => void };

const owners: Record<NativeButtonKind, Owner[]> = { main: [], secondary: [] };
const detachers: Partial<Record<NativeButtonKind, () => void>> = {};

function lookOf(kind: NativeButtonKind, action: BottomAction | null): NativeButtonLook | null {
  if (!action) return null;
  return { text: action.text, disabled: action.disabled, loading: action.loading, shine: action.shine, position: "left", ...nativeButtonColors(kind) };
}

function refreshNative(kind: NativeButtonKind): void {
  const top = owners[kind].at(-1);
  const look = top?.look();
  if (!top || !look) {
    detachers[kind]?.();
    delete detachers[kind];
    return;
  }
  // Settings before showing, so the button never flashes Telegram's default text.
  updateNativeButton(kind, look);
  detachers[kind] ??= attachNativeButton(kind, () => owners[kind].at(-1)?.press()) ?? undefined;
}

/**
 * Drive Telegram's main or secondary button from React state while `action` is set. Presses
 * reach the latest `onClick`; changing text or state never hides the button.
 */
export function useNativeButton(kind: NativeButtonKind, action: BottomAction | null): void {
  const latest = useRef(action);
  latest.current = action;
  const owner = useRef<Owner>({
    look: () => lookOf(kind, latest.current),
    press: () => {
      const current = latest.current;
      if (current && !current.disabled && !current.loading) current.onClick();
    },
  });
  const active = action !== null;

  useEffect(() => {
    if (!active) return;
    const me = owner.current;
    owners[kind].push(me);
    refreshNative(kind);
    return () => {
      owners[kind] = owners[kind].filter((other) => other !== me);
      refreshNative(kind);
    };
  }, [kind, active]);

  const text = action?.text;
  const disabled = action?.disabled;
  const loading = action?.loading;
  const shine = action?.shine;
  useEffect(() => {
    if (active && owners[kind].at(-1) === owner.current) refreshNative(kind);
  }, [kind, active, text, disabled, loading, shine]);
}

/**
 * Hide Telegram's buttons while `active`, for an open sheet: the page's button would otherwise
 * sit under the sheet and read as the sheet's own ("Close shift" under a payout form). A
 * BottomBar inside the sheet still drives them: this is a layout effect, so it registers before
 * the sheet content's (passive) effects and the sheet's own button ends up on top.
 */
export function useHideNativeButtons(active: boolean): void {
  useLayoutEffect(() => {
    if (!active) return;
    const hidden: Owner = { look: () => null, press: () => undefined };
    for (const kind of ["main", "secondary"] as const) {
      owners[kind].push(hidden);
      refreshNative(kind);
    }
    return () => {
      for (const kind of ["main", "secondary"] as const) {
        owners[kind] = owners[kind].filter((other) => other !== hidden);
        refreshNative(kind);
      }
    };
  }, [active]);
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
