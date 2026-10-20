/**
 * The console inside Telegram (owner bot menu button, plan §7.2): loads telegram-web-app.js only
 * when Telegram opened us, signs in with initData, follows themeParams, binds the BackButton to
 * router.back(), keeps safe areas in CSS variables and routes `startapp` parameters.
 */
import { watch } from "vue";
import type { RouteLocationRaw, Router } from "vue-router";

import type { DashboardModule } from "@/core/modules";
import { useUiStore } from "@/stores/ui";

interface Insets {
  top: number;
  bottom: number;
  left: number;
  right: number;
}

/** The parts of Telegram.WebApp the console uses (Bot API 8.0). */
export interface TelegramWebApp {
  initData: string;
  initDataUnsafe: { start_param?: string; auth_date?: number };
  version: string;
  platform: string;
  colorScheme: "light" | "dark";
  themeParams: Record<string, string | undefined>;
  safeAreaInset?: Insets;
  contentSafeAreaInset?: Insets;
  isVersionAtLeast: (version: string) => boolean;
  close: () => void;
  ready: () => void;
  expand: () => void;
  setHeaderColor: (color: string) => void;
  setBackgroundColor: (color: string) => void;
  setBottomBarColor?: (color: string) => void;
  disableVerticalSwipes?: () => void;
  onEvent: (event: string, handler: () => void) => void;
  offEvent: (event: string, handler: () => void) => void;
  BackButton: { show: () => void; hide: () => void; onClick: (cb: () => void) => void; offClick: (cb: () => void) => void };
  HapticFeedback?: { impactOccurred: (style: "light" | "medium") => void; notificationOccurred: (kind: "success" | "warning" | "error") => void };
}

declare global {
  interface Window {
    Telegram?: { WebApp?: TelegramWebApp };
  }
}

const SCRIPT_URL = "https://telegram.org/js/telegram-web-app.js";
const GROUND = { light: "#f7f3ec", dark: "#141210" } as const;

export interface TelegramContext {
  inside: boolean;
  initData: string | null;
  startParam: string | null;
  webApp: TelegramWebApp | null;
}

const OUTSIDE: TelegramContext = { inside: false, initData: null, startParam: null, webApp: null };

/** Telegram passes launch data in the URL hash; its script keeps it in sessionStorage on reload. */
export function launchedFromTelegram(hash = typeof location !== "undefined" ? location.hash : ""): boolean {
  if (hash.includes("tgWebAppData=")) return true;
  try {
    return !!window.sessionStorage.getItem("__telegram__initParams");
  } catch {
    return false;
  }
}

function loadScript(src: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = src;
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("telegram-web-app.js failed to load"));
    document.head.appendChild(script);
  });
}

let context: TelegramContext = OUTSIDE;

/** Detects Telegram and loads its script; outside Telegram this costs nothing. */
export async function detectTelegram(): Promise<TelegramContext> {
  if (!launchedFromTelegram()) return OUTSIDE;
  try {
    if (!window.Telegram?.WebApp) await loadScript(SCRIPT_URL);
  } catch {
    return OUTSIDE;
  }
  const webApp = window.Telegram?.WebApp ?? null;
  if (!webApp?.initData) return OUTSIDE;
  context = { inside: true, initData: webApp.initData, startParam: webApp.initDataUnsafe.start_param ?? null, webApp };
  return context;
}

export function telegram(): TelegramContext {
  return context;
}

/** The backend refuses initData older than this (`OWNER_INIT_DATA_MAX_AGE`, plan §11.1). */
export const INIT_DATA_MAX_AGE_S = 3600;

/** Whether Telegram's launch data is too old to sign in with (then only reopening from the bot helps). */
export function initDataExpired(now = Date.now()): boolean {
  const authDate = context.webApp?.initDataUnsafe.auth_date;
  return typeof authDate === "number" && now / 1000 - authDate > INIT_DATA_MAX_AGE_S;
}

/** Signs in again with the same initData (http's `relogin` inside Telegram). */
export async function telegramRelogin(): Promise<string | null> {
  if (!context.initData || initDataExpired()) return null;
  try {
    const response = await fetch("/api/v1/owner/auth/telegram/", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", Accept: "application/json", "X-Requested-With": "dashboard" },
      body: JSON.stringify({ init_data: context.initData }),
    });
    if (!response.ok) return null;
    return ((await response.json()) as { access?: string }).access ?? null;
  } catch {
    return null;
  }
}

export function closeTelegram(): void {
  context.webApp?.close();
}

function applyInsets(webApp: TelegramWebApp): void {
  const root = document.documentElement.style;
  const safe = webApp.safeAreaInset;
  const content = webApp.contentSafeAreaInset;
  const top = (safe?.top ?? 0) + (content?.top ?? 0);
  const bottom = (safe?.bottom ?? 0) + (content?.bottom ?? 0);
  if (top) root.setProperty("--safe-top", `${top}px`);
  if (bottom) root.setProperty("--safe-bottom", `${bottom}px`);
  if (safe?.left) root.setProperty("--safe-left", `${safe.left}px`);
  if (safe?.right) root.setProperty("--safe-right", `${safe.right}px`);
}

/** Wires Telegram's chrome to the app. Call once after the router exists. */
export function bindTelegram(router: Router): void {
  const webApp = context.webApp;
  if (!webApp) return;
  const ui = useUiStore();
  document.documentElement.dataset.telegram = "true";
  webApp.ready();
  webApp.expand();
  if (webApp.isVersionAtLeast("7.7")) webApp.disableVerticalSwipes?.();

  const syncTheme = () => (ui.telegramTheme = webApp.colorScheme === "dark" ? "dark" : "light");
  syncTheme();
  webApp.onEvent("themeChanged", syncTheme);

  watch(
    () => ui.theme,
    (theme) => {
      if (!webApp.isVersionAtLeast("6.1")) return;
      webApp.setHeaderColor(GROUND[theme]);
      webApp.setBackgroundColor(GROUND[theme]);
      if (webApp.isVersionAtLeast("7.10")) webApp.setBottomBarColor?.(GROUND[theme]);
    },
    { immediate: true },
  );

  applyInsets(webApp);
  webApp.onEvent("safeAreaChanged", () => applyInsets(webApp));
  webApp.onEvent("contentSafeAreaChanged", () => applyInsets(webApp));

  // BackButton mirrors the browser history: shown whenever there is somewhere to go back to.
  const back = () => router.back();
  webApp.BackButton.onClick(back);
  router.afterEach(() => {
    const canGoBack = !!(window.history.state as { back?: string | null } | null)?.back;
    if (canGoBack) webApp.BackButton.show();
    else webApp.BackButton.hide();
  });
}

/**
 * `startapp` → where to go. "approvals" opens the Needs-you inbox; "<prefix>_<arg>" asks the
 * module that registered `deepLinks[prefix]`; anything else lands on the company overview.
 */
export function resolveStartParam(param: string | null, companyId: number, list: readonly DashboardModule[]): RouteLocationRaw | null {
  if (!param) return null;
  const base = `/c/${companyId}`;
  if (param === "approvals") return { path: base, query: { inbox: "needs" } };
  const separator = param.indexOf("_");
  const prefix = separator > 0 ? param.slice(0, separator) : param;
  const argument = separator > 0 ? param.slice(separator + 1) : "";
  for (const module of list) {
    const resolver = module.deepLinks?.[prefix];
    if (!resolver) continue;
    const target = resolver(argument);
    if (target === null) continue;
    return typeof target === "string" ? `${base}/${target.replace(/^\/+/, "")}` : target;
  }
  return base;
}
