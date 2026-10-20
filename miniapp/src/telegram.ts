/**
 * Everything the app needs from Telegram's WebApp object, in one place.
 *
 * telegram-web-app.js defines window.Telegram.WebApp everywhere, but initData is only filled
 * inside Telegram. For local development, VITE_DEV_INIT_DATA can stand in for it (signed with
 * the dev backend's bot token).
 */

type WebApp = Window["Telegram"]["WebApp"];

const webApp: WebApp | undefined = window.Telegram?.WebApp;

export function initData(): string {
  return webApp?.initData || import.meta.env.VITE_DEV_INIT_DATA || "";
}

export function telegramName(): { first: string; last: string } {
  const user = webApp?.initDataUnsafe?.user;
  return { first: user?.first_name ?? "", last: user?.last_name ?? "" };
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

export function haptic(kind: "light" | "success" | "error" = "light"): void {
  const feedback = webApp?.HapticFeedback;
  if (!feedback || !webApp?.isVersionAtLeast("6.1")) return;
  if (kind === "light") feedback.impactOccurred("light");
  else feedback.notificationOccurred(kind);
}

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
