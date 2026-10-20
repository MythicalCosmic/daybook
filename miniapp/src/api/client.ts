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

let accessToken: string | null = null;
let login: Promise<void> | null = null;

/** Exchange Telegram's init data for a JWT. Concurrent callers share one request. */
function ensureLogin(): Promise<void> {
  login ??= (async () => {
    try {
      const response = await fetch(`${BASE}/auth/telegram/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ init_data: initData() }),
      });
      if (!response.ok) throw new ApiError(response.status, await readBody(response));
      accessToken = ((await response.json()) as { access: string }).access;
    } finally {
      login = null;
    }
  })();
  return login;
}

type Options = { method?: string; json?: unknown; form?: FormData };

export async function api<T>(path: string, options: Options = {}): Promise<T> {
  if (!accessToken) await ensureLogin();
  let response = await send(path, options);
  if (response.status === 401) {
    // The access token expired: sign in again with the init data and retry once.
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

function send(path: string, { method, json, form }: Options): Promise<Response> {
  const headers: Record<string, string> = { Authorization: `Bearer ${accessToken}` };
  let body: BodyInit | undefined;
  if (form) body = form;
  else if (json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(json);
  }
  return fetch(`${BASE}${path}`, { method: method ?? (body ? "POST" : "GET"), headers, body });
}

async function readBody(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    return null;
  }
}
