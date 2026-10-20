/**
 * The one fetch wrapper (plan §6.5). It adds the Bearer token kept in memory, the UI language and
 * `X-Requested-With: dashboard`; on a 401 it makes one shared refresh call (the httpOnly cookie) and
 * retries once; it turns error bodies into an ApiError the UI can show: `{detail}` becomes a toast,
 * `{field: [...]}` becomes form errors (lib/useForm.ts reads `fieldErrors`).
 */
import type { AccessResponse } from "@/api/types";

export const API_BASE = "/api/v1";

export type FieldErrors = Record<string, string[]>;

export class ApiError extends Error {
  readonly status: number;
  readonly body: unknown;
  /** The backend's user-safe sentence, when it sent one. */
  readonly detail: string | null;
  /** Per-field messages from a DRF validation error (400). */
  readonly fieldErrors: FieldErrors;
  /** A stable code the backend attached (`{"code": "needs_proof"}`), when present. */
  readonly code: string | null;

  constructor(status: number, body: unknown) {
    const parsed = parseErrorBody(body);
    super(parsed.detail ?? `HTTP ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
    this.detail = parsed.detail;
    this.fieldErrors = parsed.fields;
    this.code = parsed.code;
  }

  get isNetwork(): boolean {
    return this.status === 0;
  }
}

export function isApiError(error: unknown): error is ApiError {
  return error instanceof ApiError;
}

const NON_FIELD = new Set(["detail", "non_field_errors", "code", "messages"]);

function asMessages(value: unknown): string[] | null {
  if (typeof value === "string") return [value];
  if (Array.isArray(value) && value.every((v) => typeof v === "string")) return value as string[];
  return null;
}

/** Splits a DRF error body into a sentence for a toast and messages per field. */
export function parseErrorBody(body: unknown): { detail: string | null; fields: FieldErrors; code: string | null } {
  const fields: FieldErrors = {};
  let detail: string | null = null;
  let code: string | null = null;
  if (typeof body === "string" && body.trim() && body.length < 300 && !body.trimStart().startsWith("<")) {
    detail = body.trim();
  } else if (Array.isArray(body)) {
    detail = asMessages(body)?.[0] ?? null;
  } else if (body && typeof body === "object") {
    const record = body as Record<string, unknown>;
    if (typeof record.detail === "string") detail = record.detail;
    if (typeof record.code === "string") code = record.code;
    const nonField = asMessages(record.non_field_errors);
    if (!detail && nonField) detail = nonField[0] ?? null;
    for (const [key, value] of Object.entries(record)) {
      if (NON_FIELD.has(key)) continue;
      const messages = asMessages(value);
      if (messages) fields[key] = messages;
    }
  }
  return { detail, fields, code };
}

export type QueryValue = string | number | boolean | null | undefined | ReadonlyArray<string | number>;
export type Query = Record<string, QueryValue>;

/** Arrays repeat the key (`branch=1&branch=2`); empty values are left out. */
export function buildQuery(query?: Query): string {
  if (!query) return "";
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === null || value === undefined || value === "") continue;
    if (Array.isArray(value)) value.forEach((item) => params.append(key, String(item)));
    else params.append(key, String(value));
  }
  const text = params.toString();
  return text ? `?${text}` : "";
}

/** Accepts "/owner/me/", "owner/me/" or a full "/api/v1/owner/me/" (queue actions send those). */
export function apiUrl(path: string, query?: Query): string {
  if (/^https?:\/\//.test(path)) return path + buildQuery(query);
  const clean = path.startsWith(API_BASE) ? path : `${API_BASE}/${path.replace(/^\/+/, "")}`;
  return clean + buildQuery(query);
}

/** `/owner/companies/{id}/{path}` */
export function ownerPath(companyId: number, path = ""): string {
  return `/owner/companies/${companyId}/${path.replace(/^\/+/, "")}`;
}

export interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  query?: Query;
  json?: unknown;
  form?: FormData;
  signal?: AbortSignal;
  headers?: Record<string, string>;
  /**
   * Show the error as a toast. Default: on for writes, off for reads (queries render ErrorState
   * inline, and the 15 s pulse must never spam toasts).
   */
  toast?: boolean;
  /** Skip the Authorization header and the refresh dance (auth endpoints). */
  anonymous?: boolean;
  /** Return the raw Response (downloads). */
  raw?: boolean;
}

export interface HttpConfig {
  getToken: () => string | null;
  setToken: (token: string | null) => void;
  getLanguage: () => string;
  /**
   * Gets a new access token another way than the refresh cookie. Inside Telegram there is no
   * cookie path (Telegram Web runs the console in a cross-site iframe), so TelegramBridge posts
   * initData again (plan §6.5).
   */
  relogin?: () => Promise<string | null>;
  /** Refresh failed: the session is over. */
  onSessionEnded: () => void;
  /** Show an error toast. */
  onError: (error: ApiError) => void;
}

const config: HttpConfig = {
  getToken: () => null,
  setToken: () => undefined,
  getLanguage: () => "uz",
  onSessionEnded: () => undefined,
  onError: () => undefined,
};

export function configureHttp(next: Partial<HttpConfig>): void {
  Object.assign(config, next);
}

let refreshing: Promise<string | null> | null = null;

/** One refresh at a time: every 401 that arrives meanwhile waits for the same call. */
export function refreshAccess(): Promise<string | null> {
  refreshing ??= (async () => {
    try {
      if (config.relogin) {
        const token = await config.relogin();
        if (token) config.setToken(token);
        return token;
      }
      const response = await fetch(apiUrl("/owner/auth/refresh/"), {
        method: "POST",
        credentials: "same-origin",
        headers: { "X-Requested-With": "dashboard", "Accept-Language": config.getLanguage(), Accept: "application/json" },
      });
      if (!response.ok) return null;
      const body = (await response.json()) as AccessResponse;
      config.setToken(body.access);
      return body.access;
    } catch {
      return null;
    } finally {
      refreshing = null;
    }
  })();
  return refreshing;
}

function send(url: string, options: RequestOptions): Promise<Response> {
  const headers: Record<string, string> = {
    Accept: "application/json",
    "Accept-Language": config.getLanguage(),
    "X-Requested-With": "dashboard",
    ...options.headers,
  };
  const token = options.anonymous ? null : config.getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  let body: BodyInit | undefined;
  if (options.form) body = options.form;
  else if (options.json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(options.json);
  }
  return fetch(url, {
    method: options.method ?? (body ? "POST" : "GET"),
    headers,
    body,
    signal: options.signal,
    credentials: "same-origin",
  });
}

async function readBody(response: Response): Promise<unknown> {
  const text = await response.text();
  if (!text) return null;
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return text;
  }
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const url = apiUrl(path, options.query);
  const method = options.method ?? (options.json !== undefined || options.form ? "POST" : "GET");
  const wantsToast = options.toast ?? method !== "GET";
  let response: Response;
  try {
    response = await send(url, { ...options, method });
    if (response.status === 401 && !options.anonymous) {
      const token = await refreshAccess();
      if (!token) {
        config.setToken(null);
        config.onSessionEnded();
        throw new ApiError(401, await readBody(response));
      }
      response = await send(url, { ...options, method });
    }
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    const offline = new ApiError(0, null);
    if (wantsToast) config.onError(offline);
    throw offline;
  }
  if (!response.ok) {
    const error = new ApiError(response.status, await readBody(response));
    // Field errors belong next to their fields; everything else is a toast.
    const onlyFields = Object.keys(error.fieldErrors).length > 0 && !error.detail;
    if (wantsToast && !onlyFields) config.onError(error);
    throw error;
  }
  if (options.raw) return response as unknown as T;
  if (response.status === 204) return undefined as T;
  return (await readBody(response)) as T;
}

export const http = {
  get: <T>(path: string, query?: Query, options: Omit<RequestOptions, "method" | "query"> = {}) =>
    request<T>(path, { ...options, method: "GET", query }),
  post: <T>(path: string, json?: unknown, options: Omit<RequestOptions, "method" | "json"> = {}) =>
    request<T>(path, { ...options, method: "POST", json: json ?? {} }),
  put: <T>(path: string, json?: unknown, options: Omit<RequestOptions, "method" | "json"> = {}) =>
    request<T>(path, { ...options, method: "PUT", json: json ?? {} }),
  patch: <T>(path: string, json?: unknown, options: Omit<RequestOptions, "method" | "json"> = {}) =>
    request<T>(path, { ...options, method: "PATCH", json: json ?? {} }),
  delete: <T = void>(path: string, options: Omit<RequestOptions, "method"> = {}) => request<T>(path, { ...options, method: "DELETE" }),
  form: <T>(path: string, form: FormData, options: Omit<RequestOptions, "form"> = {}) =>
    request<T>(path, { method: "POST", ...options, form }),
};
