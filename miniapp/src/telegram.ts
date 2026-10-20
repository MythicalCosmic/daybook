/**
 * Everything the app needs from Telegram's WebApp object, in one place.
 *
 * telegram-web-app.js defines window.Telegram.WebApp everywhere, but initData is only filled
 * inside Telegram. For local development, VITE_DEV_INIT_DATA can stand in for it (signed with
 * the dev backend's bot token).
 *
 * Every helper checks the Bot API version it needs and does nothing (or falls back to the
 * browser) on older clients, so screens can call them without guards.
 */

type WebApp = Window["Telegram"]["WebApp"];

const webApp: WebApp | undefined = window.Telegram?.WebApp;

/**
 * Whether a Telegram client hosts the page. telegram-web-app.js also runs in a plain browser,
 * where it reports platform "unknown" and version "6.0": nothing draws its buttons there.
 */
export function insideTelegram(): boolean {
  return Boolean(webApp) && webApp?.platform !== undefined && webApp.platform !== "unknown";
}

/** Whether this Telegram client supports a Bot API version ("6.1", "7.10", "8.0" …). */
export function supports(version: string): boolean {
  return insideTelegram() && Boolean(webApp?.isVersionAtLeast?.(version));
}

export function initData(): string {
  return webApp?.initData || import.meta.env.VITE_DEV_INIT_DATA || "";
}

export function telegramName(): { first: string; last: string } {
  const user = webApp?.initDataUnsafe?.user;
  return { first: user?.first_name ?? "", last: user?.last_name ?? "" };
}

/** The `startapp` parameter the mini app was opened with, if any. */
export function startParam(): string | null {
  return webApp?.initDataUnsafe?.start_param || null;
}

export function start(): void {
  webApp?.ready();
  webApp?.expand();
}

export function colorScheme(): "light" | "dark" {
  return webApp?.colorScheme === "dark" ? "dark" : "light";
}

export function onThemeChange(callback: () => void): () => void {
  webApp?.onEvent("themeChanged", callback);
  return () => webApp?.offEvent("themeChanged", callback);
}

/** Match Telegram's own header and background to the app's ground color. */
export function paintChrome(color: string): void {
  if (!webApp?.isVersionAtLeast("6.1")) return;
  webApp.setHeaderColor(color);
  webApp.setBackgroundColor(color);
  if (webApp.isVersionAtLeast("7.10")) webApp.setBottomBarColor(color);
}

// — haptics —

type ImpactStyle = "light" | "medium" | "heavy" | "rigid" | "soft";
type Notice = "success" | "warning" | "error";

function feedback() {
  const haptics = webApp?.HapticFeedback;
  return haptics && webApp?.isVersionAtLeast("6.1") ? haptics : null;
}

type Haptic = {
  /** Light tap, or a success/error notice: the original one-call form. */
  (kind?: "light" | "success" | "error"): void;
  /** A physical bump: light for ticks, medium/heavy for bigger moments. */
  impact(style?: ImpactStyle): void;
  /** Success on complete, check-in, signing; warning and error when something needs attention. */
  notify(type: Notice): void;
  /** The selection changed: segmented controls, chips, steppers, keypad keys. */
  select(): void;
};

export const haptic: Haptic = Object.assign(
  (kind: "light" | "success" | "error" = "light") => {
    const haptics = feedback();
    if (!haptics) return;
    if (kind === "light") haptics.impactOccurred("light");
    else haptics.notificationOccurred(kind);
  },
  {
    impact: (style: ImpactStyle = "light") => feedback()?.impactOccurred(style),
    notify: (type: Notice) => feedback()?.notificationOccurred(type),
    select: () => feedback()?.selectionChanged(),
  },
);

// — back button —

/** Show Telegram's back button while `onBack` is set. Returns a cleanup function. */
export function useBackButton(onBack: (() => void) | null): () => void {
  const button = webApp?.BackButton;
  if (!button || !webApp?.isVersionAtLeast("6.1") || !onBack) {
    button?.hide();
    return () => {};
  }
  button.onClick(onBack);
  button.show();
  return () => {
    button.offClick(onBack);
    button.hide();
  };
}

/** Whether Telegram draws a back button for us; otherwise pages show their own. */
export function hasNativeBackButton(): boolean {
  return Boolean(webApp?.BackButton) && supports("6.1");
}

// — main and secondary buttons —

export type NativeButtonKind = "main" | "secondary";

/** How the button looks and whether it can be pressed. */
export type NativeButtonLook = {
  text: string;
  disabled?: boolean;
  /** Spinner on the button; it can't be pressed meanwhile. */
  loading?: boolean;
  /** Background and text colors as hex (see theme.nativeButtonColors). */
  color?: string;
  textColor?: string;
  /** Telegram's shine effect, for the one action that matters most (7.10+). */
  shine?: boolean;
  /** Where the secondary button sits when both are visible (7.10+). */
  position?: "left" | "right" | "top" | "bottom";
};

export type NativeButtonParams = NativeButtonLook & { onClick: () => void };

function nativeButton(kind: NativeButtonKind) {
  if (!webApp) return null;
  if (kind === "main") return webApp.MainButton && supports("6.0") ? webApp.MainButton : null;
  return webApp.SecondaryButton && supports("7.10") ? webApp.SecondaryButton : null;
}

/** Whether Telegram can draw this button under the app (Bot API 6.0 main, 7.10 secondary). */
export function hasNativeButton(kind: NativeButtonKind): boolean {
  return nativeButton(kind) !== null;
}

/** Change the text, colors and state of a native button without hiding it. */
export function updateNativeButton(kind: NativeButtonKind, look: NativeButtonLook): void {
  const button = nativeButton(kind);
  if (!button) return;
  button.setParams({
    text: look.text,
    ...(look.color ? { color: look.color } : {}),
    ...(look.textColor ? { text_color: look.textColor } : {}),
    ...(supports("7.10") && look.shine !== undefined ? { has_shine_effect: look.shine } : {}),
    ...(kind === "secondary" && look.position ? { position: look.position } : {}),
    is_active: !look.disabled && !look.loading,
  });
  if (look.loading) button.showProgress(false);
  else button.hideProgress();
}

/**
 * Show a native button and send its presses to `onClick`. Returns the cleanup that removes the
 * handler and hides it again, or null when this client has no such button.
 */
export function attachNativeButton(kind: NativeButtonKind, onClick: () => void): (() => void) | null {
  const button = nativeButton(kind);
  if (!button) return null;
  button.onClick(onClick);
  button.show();
  return () => {
    button.offClick(onClick);
    button.hideProgress();
    button.hide();
  };
}

/**
 * Show Telegram's main ("bottom") or secondary button with these settings in one call. Returns
 * the cleanup, or null when the client has no such button (render an in-page button instead;
 * `ui/BottomBar` does both and keeps the button in sync with React state).
 */
export function showNativeButton(kind: NativeButtonKind, params: NativeButtonParams): (() => void) | null {
  if (!nativeButton(kind)) return null;
  updateNativeButton(kind, params);
  return attachNativeButton(kind, params.onClick);
}

/** `showNativeButton("main", …)`: the Bot API calls it the bottom button since 7.10. */
export const bottomButton = (params: NativeButtonParams) => showNativeButton("main", params);
export const secondaryButton = (params: NativeButtonParams) => showNativeButton("secondary", params);

// — vertical swipes and fullscreen —

let swipeLocks = 0;

/**
 * Stop the swipe-down-to-close gesture while something scrollable is open (a sheet). Returns
 * the function that allows it again. Nested calls stack; the gesture comes back when the last
 * one is released. Needs 7.7+.
 */
export function disableVerticalSwipes(): () => void {
  if (!webApp || !supports("7.7")) return () => {};
  swipeLocks += 1;
  if (swipeLocks === 1) webApp.disableVerticalSwipes();
  let released = false;
  return () => {
    if (released) return;
    released = true;
    swipeLocks -= 1;
    if (swipeLocks === 0) webApp.enableVerticalSwipes();
  };
}

/** Ask for full screen (8.0+; mobile clients). Returns false when unsupported. */
export function requestFullscreen(): boolean {
  if (!webApp || !supports("8.0")) return false;
  webApp.requestFullscreen();
  return true;
}

export function exitFullscreen(): void {
  if (webApp && supports("8.0") && webApp.isFullscreen) webApp.exitFullscreen();
}

export function isFullscreen(): boolean {
  return Boolean(webApp && supports("8.0") && webApp.isFullscreen);
}

export function onFullscreenChange(callback: () => void): () => void {
  if (!webApp || !supports("8.0")) return () => {};
  webApp.onEvent("fullscreenChanged", callback);
  return () => webApp.offEvent("fullscreenChanged", callback);
}

// — QR scanner, dialogs, links —

/**
 * Open Telegram's QR scanner and resolve with the first code read, or null when the person
 * closes it or the client can't scan (6.4+).
 */
export function scanQr(text?: string): Promise<string | null> {
  return new Promise((resolve) => {
    if (!webApp || !supports("6.4")) {
      resolve(null);
      return;
    }
    let settled = false;
    const closed = () => finish(null);
    const finish = (value: string | null) => {
      if (settled) return;
      settled = true;
      webApp.offEvent("scanQrPopupClosed", closed);
      resolve(value);
    };
    webApp.onEvent("scanQrPopupClosed", closed);
    webApp.showScanQrPopup(text ? { text } : {}, (data) => {
      finish(data);
      webApp.closeScanQrPopup();
      return true;
    });
  });
}

/** A yes/no question in Telegram's own dialog (6.2+), or the browser's confirm(). */
export function confirm(message: string): Promise<boolean> {
  return new Promise((resolve) => {
    if (webApp && supports("6.2")) webApp.showConfirm(message, (ok) => resolve(ok));
    else resolve(window.confirm(message));
  });
}

/** The absolute http(s) form of `url` (relative ones resolve against the app), or null for anything else. */
export function webUrl(url: string): string | null {
  try {
    const parsed = new URL(url, window.location.href);
    return parsed.protocol === "https:" || parsed.protocol === "http:" ? parsed.href : null;
  } catch {
    return null;
  }
}

/**
 * Open an external link (Telegram's in-app browser when available). Only http(s) links open:
 * a `javascript:` or `data:` URL from a server field is dropped, never run. Returns whether it opened.
 */
export function openLink(url: string): boolean {
  const safe = webUrl(url);
  if (!safe) {
    console.error("Refusing to open a non-web link", url);
    return false;
  }
  if (webApp && supports("6.1")) webApp.openLink(safe);
  else window.open(safe, "_blank", "noopener");
  return true;
}

/** Open a t.me link inside Telegram (a chat, a bot, a profile). Returns whether it opened. */
export function openTelegramLink(url: string): boolean {
  const safe = webUrl(url);
  if (!safe || !/^(www\.)?t\.me$/i.test(new URL(safe).hostname)) {
    console.error("Refusing to open a non-t.me link", url);
    return false;
  }
  if (webApp && supports("6.1")) webApp.openTelegramLink(safe);
  else window.open(safe, "_blank", "noopener");
  return true;
}

// — cloud storage —

const CLOUD_KEY = /^[A-Za-z0-9_-]{1,128}$/;
const CLOUD_VALUE_MAX = 4096;
const LOCAL_PREFIX = "daybook.cloud.";

function cloud() {
  return webApp?.CloudStorage && supports("6.9") ? webApp.CloudStorage : null;
}

function local<T>(work: (storage: Storage) => T, fallback: T): T {
  try {
    return work(window.localStorage);
  } catch {
    return fallback;
  }
}

/**
 * Small per-person storage that follows the person across devices (Telegram 6.9+), with
 * localStorage as the fallback. Keys: 1–128 of A–Z a–z 0–9 _ -; values up to 4096 characters.
 * Every call resolves, never rejects: drafts are a convenience, not a source of truth.
 */
export const cloudStorage = {
  get(key: string): Promise<string | null> {
    if (!CLOUD_KEY.test(key)) return Promise.resolve(null);
    const storage = cloud();
    if (!storage) return Promise.resolve(local((s) => s.getItem(LOCAL_PREFIX + key), null));
    return new Promise((resolve) => storage.getItem(key, (error, value) => resolve(error ? null : value || null)));
  },

  set(key: string, value: string): Promise<boolean> {
    if (!CLOUD_KEY.test(key) || value.length > CLOUD_VALUE_MAX) return Promise.resolve(false);
    const storage = cloud();
    if (!storage) {
      return Promise.resolve(
        local((s) => {
          s.setItem(LOCAL_PREFIX + key, value);
          return true;
        }, false),
      );
    }
    return new Promise((resolve) => storage.setItem(key, value, (error, done) => resolve(!error && done === true)));
  },

  remove(key: string): Promise<void> {
    if (!CLOUD_KEY.test(key)) return Promise.resolve();
    const storage = cloud();
    if (!storage) return Promise.resolve(local((s) => s.removeItem(LOCAL_PREFIX + key), undefined));
    return new Promise((resolve) => storage.removeItem(key, () => resolve()));
  },

  keys(): Promise<string[]> {
    const storage = cloud();
    if (!storage) {
      return Promise.resolve(
        local(
          (s) =>
            Array.from({ length: s.length }, (_, index) => s.key(index) ?? "")
              .filter((name) => name.startsWith(LOCAL_PREFIX))
              .map((name) => name.slice(LOCAL_PREFIX.length)),
          [],
        ),
      );
    }
    return new Promise((resolve) => storage.getKeys((error, keys) => resolve(error ? [] : keys ?? [])));
  },
};

// — contact, close —

/** Ask Telegram to share the person's phone with the bot. Resolves to whether they agreed. */
export function requestContact(): Promise<boolean> {
  return new Promise((resolve) => {
    if (!webApp?.isVersionAtLeast("6.9")) {
      resolve(false);
      return;
    }
    webApp.requestContact((shared) => resolve(shared));
  });
}

export function close(): void {
  webApp?.close();
}
