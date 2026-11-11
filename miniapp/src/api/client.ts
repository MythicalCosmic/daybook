import { initData } from "../telegram";

const BASE = "/api/v1";

export class ApiError extends Error {
  constructor(
    public status: number,
    public body: unknown,
  ) {
    super(`API ${status}`);
  }

  /** The backend's user-safe explanation, when it sent one. */
  get detail(): string | null {
    if (this.body && typeof this.body === "object") {
      const body = this.body as Record<string, unknown>;
      if (typeof body.detail === "string") return body.detail;
      const first = Object.values(body)[0];
      if (Array.isArray(first) && typeof first[0] === "string") return first[0];
    }
    return null;
  }
}

/**
 * The session (`POST auth/telegram/`, apps.accounts): an access token (1 hour) and a refresh token
 * (7 days, rotating; `auth/telegram/refresh/`). Init data is good for a day; the refresh token
 * keeps an open app signed in past that, so "session ended" only shows when both are refused.
 * Written by hand until the schema types are generated again.
 */
export interface TelegramSession {
  access: string;
  refresh: string;
}

/** Where the refresh token waits across reloads of the webview (sessionStorage: it ends with it). */
export const SESSION_KEY = "daybook.app.telegramSession";

let accessToken: string | null = null;
let refreshToken: string | null = null;
let login: Promise<void> | null = null;

/** Whose launch data this is: a token another Telegram account left in this tab is never used. */
function telegramUserId(): number | null {
  try {
    const user = JSON.parse(new URLSearchParams(initData()).get("user") ?? "null") as { id?: number } | null;
    return typeof user?.id === "number" ? user.id : null;
  } catch {
    return null;
  }
}

function keptRefresh(): string | null {
  if (refreshToken) return refreshToken;
  try {
    const raw = window.sessionStorage.getItem(SESSION_KEY);
    const kept = raw ? (JSON.parse(raw) as { user?: number | null; refresh?: unknown }) : null;
    if (kept && typeof kept.refresh === "string" && (kept.user ?? null) === telegramUserId()) refreshToken = kept.refresh;
  } catch {
    // Storage blocked or garbled: memory only.
  }
  return refreshToken;
}

function keepSession(session: { access: string; refresh?: string | null }): void {
  accessToken = session.access;
  if (!session.refresh) return;
  refreshToken = session.refresh;
  try {
    window.sessionStorage.setItem(SESSION_KEY, JSON.stringify({ user: telegramUserId(), refresh: session.refresh }));
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

function postJson(path: string, body: unknown): Promise<Response> {
  return fetch(`${BASE}${path}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
}

/** The kept refresh token's next session: false when refused (spent, expired, switched off). */
async function refreshSession(token: string): Promise<boolean> {
  const response = await postJson("/auth/telegram/refresh/", { refresh: token });
  if (response.ok) {
    keepSession((await response.json()) as TelegramSession);
    return true;
  }
  if (response.status === 400 || response.status === 401 || response.status === 403) {
    forgetRefresh();
    return false;
  }
  // Busy or restarting: not a refusal, so the token stays for the next try.
  throw new ApiError(response.status, await readBody(response));
}

/**
 * A session: the kept refresh token first, else Telegram's init data. Concurrent callers share
 * one request. Throws ApiError (401 when both were refused) or the network's TypeError.
 */
function ensureLogin(): Promise<void> {
  login ??= (async () => {
    try {
      const kept = keptRefresh();
      if (kept && (await refreshSession(kept))) return;
      const response = await postJson("/auth/telegram/", { init_data: initData() });
      if (!response.ok) throw new ApiError(response.status, await readBody(response));
      keepSession((await response.json()) as TelegramSession);
    } finally {
      login = null;
    }
  })();
  return login;
}

/** `keepalive`: the request still goes out if the app closes meanwhile (a confirm sent on leaving). */
type Options = { method?: string; json?: unknown; form?: FormData; keepalive?: boolean };

export async function api<T>(path: string, options: Options = {}): Promise<T> {
  if (!accessToken) await ensureLogin();
  let response = await send(path, options);
  if (response.status === 401) {
    // The access token expired: the refresh token (else the init data) gets a new one; retry once.
    accessToken = null;
    await ensureLogin();
    response = await send(path, options);
  }
  if (!response.ok) throw new ApiError(response.status, await readBody(response));
  return (response.status === 204 ? undefined : await response.json()) as T;
}

export type FormValue = string | number | boolean | Blob | null | undefined;
export type FormFields = Record<string, FormValue | readonly FormValue[]>;

/**
 * Multipart body from plain fields: numbers and booleans become strings ("true"/"false", as DRF
 * reads them), files keep their name, `null`/`undefined` are left out, and arrays repeat the field.
 */
export function toFormData(fields: FormFields): FormData {
  const form = new FormData();
  const append = (name: string, value: FormValue) => {
    if (value === null || value === undefined) return;
    if (value instanceof Blob) {
      // The server picks stored names itself; a File keeps its own, a bare Blob gets a neutral one.
      if (value instanceof File) form.append(name, value);
      else form.append(name, value, "upload");
    } else {
      form.append(name, String(value));
    }
  };
  for (const [name, value] of Object.entries(fields)) {
    if (Array.isArray(value)) value.forEach((item: FormValue) => append(name, item));
    else append(name, value as FormValue);
  }
  return form;
}

/**
 * Upload with multipart/form-data (photos, receipts, documents). The browser sets the boundary,
 * so no Content-Type header is sent; sign-in and the 401 retry work as in `api`.
 */
export function apiForm<T>(
  path: string,
  fields: FormFields | FormData,
  options: { method?: "POST" | "PATCH" | "PUT" } = {},
): Promise<T> {
  const form = fields instanceof FormData ? fields : toFormData(fields);
  return api<T>(path, { method: options.method ?? "POST", form });
}

function send(path: string, { method, json, form, keepalive }: Options): Promise<Response> {
  const headers: Record<string, string> = { Authorization: `Bearer ${accessToken}` };
  let body: BodyInit | undefined;
  if (form) body = form;
  else if (json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(json);
  }
  return fetch(`${BASE}${path}`, { method: method ?? (body ? "POST" : "GET"), headers, body, ...(keepalive ? { keepalive } : {}) });
}

async function readBody(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    return null;
  }
}
