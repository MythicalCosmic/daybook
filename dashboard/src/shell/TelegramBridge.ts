/**
 * The console inside Telegram (Daybook's owner bot, Davomat's own bot: their menu buttons, plan
 * §7.2): loads telegram-web-app.js only when Telegram opened us, signs in with initData, keeps the
 * session alive with its refresh token, follows themeParams, binds the BackButton to
 * router.back(), keeps safe areas in CSS variables and routes `startapp` parameters.
 *
 * The session: signing in with initData (good for an hour) answers an access token and a refresh
 * token in the body (no cookie reaches a cross-site iframe). The refresh token lives in memory
 * and in sessionStorage, so it survives Telegram reloading the webview and ends with it; every
 * next access token comes from `telegram/refresh/`, which rotates it. Only when the session was
 * ended (signed out on the devices list, or idle for a week) and the launch data is too old does
 * the page say "Session ended". Offline is not the end: the session stays for the next try.
 */
import { watch } from "vue";
import type { RouteLocationRaw, Router } from "vue-router";

import { isApiError } from "@/api/http";
import { shellApi } from "@/api/shell";
import { editionThemeColor } from "@/core/edition";
import type { DashboardModule } from "@/core/modules";
import { closeTopOverlay, overlayOpen } from "@/lib/backStack";
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
  initDataUnsafe: { start_param?: string; auth_date?: number; user?: { id: number } };
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
  /** Bot API 8.0: Telegram's own download prompt (its webviews ignore `<a download>`). */
  downloadFile?: (params: { url: string; file_name: string }, callback?: (accepted: boolean) => void) => void;
}

declare global {
  interface Window {
    Telegram?: { WebApp?: TelegramWebApp };
  }
}

const SCRIPT_URL = "https://telegram.org/js/telegram-web-app.js";

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

// ─── The session's refresh token ──────────────────────────────────────────────

/** Where the refresh token waits across reloads of the webview (sessionStorage: it ends with it). */
export const SESSION_KEY = "daybook.console.telegramSession";

interface KeptSession {
  /** Whose it is: another Telegram account opening the app in this tab (Telegram Web) starts afresh. */
  user: number | null;
  refresh: string;
}

let refreshToken: string | null = null;
let signedOut = false;

function telegramUserId(): number | null {
  return context.webApp?.initDataUnsafe.user?.id ?? null;
}

function keptRefresh(): string | null {
  if (refreshToken) return refreshToken;
  try {
    const raw = window.sessionStorage.getItem(SESSION_KEY);
    if (!raw) return null;
    const kept = JSON.parse(raw) as Partial<KeptSession>;
    if (typeof kept.refresh !== "string" || (kept.user ?? null) !== telegramUserId()) return null;
    refreshToken = kept.refresh;
  } catch {
    // Storage blocked or garbled: memory only.
  }
  return refreshToken;
}

function keepRefresh(token: string): void {
  refreshToken = token;
  try {
    window.sessionStorage.setItem(SESSION_KEY, JSON.stringify({ user: telegramUserId(), refresh: token } satisfies KeptSession));
  } catch {
    // Storage blocked: it lives in memory until the webview reloads.
  }
}

function forgetRefresh(): void {
  refreshToken = null;
  try {
    window.sessionStorage.removeItem(SESSION_KEY);
  } catch {
    // Nothing kept there.
  }
}

/** Why there is no session (the Session-ended page words it): none yet, or the last attempt's. */
export type TelegramProblem = "ended" | "no_access" | "offline" | null;
let problem: TelegramProblem = null;

export function telegramProblem(): TelegramProblem {
  return problem;
}

/** Thrown when the server couldn't be asked (offline, busy, restarting): nothing was refused. */
export class TelegramUnreachable extends Error {
  constructor() {
    super("Telegram sign-in couldn't reach the server");
    this.name = "TelegramUnreachable";
  }
}

/** A refusal (the token or the launch data is no good, or no access): the rest may work later. */
function refused(error: unknown): boolean {
  return isApiError(error) && (error.status === 400 || error.status === 401 || error.status === 403);
}

/**
 * A new access token inside Telegram (http's `relogin`): the kept refresh token first, then the
 * launch data while it is fresh; every new refresh token is kept. Null when both were refused (the
 * page shows "Session ended"); throws TelegramUnreachable when the server couldn't be asked, so the
 * session stays for the next try.
 */
export async function telegramRelogin(): Promise<string | null> {
  if (signedOut) return null;
  let unreachable = false;
  const kept = keptRefresh();
  if (kept) {
    try {
      const session = await shellApi.telegramRefresh(kept);
      // null: another tab refreshed with it a moment ago; the one we have stays good.
      if (session.refresh) keepRefresh(session.refresh);
      problem = null;
      return session.access;
    } catch (error) {
      if (refused(error)) forgetRefresh();
      else unreachable = true;
    }
  }
  let noAccess = false;
  if (context.initData && !initDataExpired()) {
    try {
      // The shell's own call: the API base and the language headers in one place.
      const session = await shellApi.telegramLogin(context.initData);
      if (session.refresh) keepRefresh(session.refresh);
      problem = null;
      return session.access;
    } catch (error) {
      if (!refused(error)) unreachable = true;
      else noAccess = isApiError(error) && error.status === 403;
    }
  }
  if (unreachable) {
    problem = "offline";
    throw new TelegramUnreachable();
  }
  problem = noAccess ? "no_access" : "ended";
  return null;
}

/** Signing out inside Telegram: the server ends this session (its refresh token) and we forget it. */
export async function endTelegramSession(): Promise<void> {
  const kept = keptRefresh();
  signedOut = true;
  forgetRefresh();
  problem = "ended";
  await shellApi.logout(kept);
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
      // The edition's own canvas: Daybook's warm paper, Davomat's cool grey.
      const ground = editionThemeColor(theme);
      webApp.setHeaderColor(ground);
      webApp.setBackgroundColor(ground);
      if (webApp.isVersionAtLeast("7.10")) webApp.setBottomBarColor?.(ground);
    },
    { immediate: true },
  );

  applyInsets(webApp);
  webApp.onEvent("safeAreaChanged", () => applyInsets(webApp));
  webApp.onEvent("contentSafeAreaChanged", () => applyInsets(webApp));

  // BackButton closes the sheet, dialog or palette on top first (lib/backStack), then mirrors the
  // browser history: shown whenever there is an overlay to close or somewhere to go back to.
  webApp.BackButton.onClick(() => {
    if (!closeTopOverlay()) router.back();
  });
  const syncBackButton = () => {
    const canGoBack = !!(window.history.state as { back?: string | null } | null)?.back;
    if (canGoBack || overlayOpen.value) webApp.BackButton.show();
    else webApp.BackButton.hide();
  };
  router.afterEach(syncBackButton);
  watch(overlayOpen, syncBackButton);
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
