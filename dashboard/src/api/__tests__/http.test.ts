import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, apiUrl, buildQuery, configureHttp, http, ownerPath, parseErrorBody, request } from "@/api/http";
import { qk, keys, moduleKey } from "@/api/keys";
import { json } from "@/test/fixtures";

let token: string | null = "old";
const errors: ApiError[] = [];
const ended = vi.fn();

beforeEach(() => {
  token = "old";
  errors.length = 0;
  ended.mockReset();
  configureHttp({
    getToken: () => token,
    setToken: (next) => (token = next),
    getLanguage: () => "ru",
    onSessionEnded: ended,
    onError: (error) => errors.push(error),
  });
});

afterEach(() => vi.unstubAllGlobals());

function headerOf(init: RequestInit | undefined, name: string): string | null {
  return new Headers(init?.headers).get(name);
}

describe("request", () => {
  it("sends the token, the language and the dashboard marker", async () => {
    const fetchMock = vi.fn(async () => json({ ok: true }));
    vi.stubGlobal("fetch", fetchMock);
    await http.get("/owner/me/");
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/v1/owner/me/");
    expect(headerOf(init, "Authorization")).toBe("Bearer old");
    expect(headerOf(init, "Accept-Language")).toBe("ru");
    expect(headerOf(init, "X-Requested-With")).toBe("dashboard");
    expect(init.credentials).toBe("same-origin");
  });

  it("refreshes once for many 401s, then retries each request", async () => {
    let refreshes = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        if (url === "/api/v1/owner/auth/refresh/") {
          refreshes += 1;
          await new Promise((resolve) => setTimeout(resolve, 5));
          return json({ access: "new" });
        }
        return headerOf(init, "Authorization") === "Bearer new" ? json({ url }) : json({ detail: "expired" }, 401);
      }),
    );
    const results = await Promise.all([http.get<{ url: string }>("/a/"), http.get<{ url: string }>("/b/"), http.get<{ url: string }>("/c/")]);
    expect(results.map((r) => r.url)).toEqual(["/api/v1/a/", "/api/v1/b/", "/api/v1/c/"]);
    expect(refreshes).toBe(1);
    expect(token).toBe("new");
  });

  it("signs in again with initData inside Telegram instead of the cookie", async () => {
    const relogin = vi.fn(async () => "fresh");
    configureHttp({ relogin });
    const fetchMock = vi.fn(async (_url: string, init?: RequestInit) =>
      headerOf(init, "Authorization") === "Bearer fresh" ? json({ ok: true }) : json({ detail: "expired" }, 401),
    );
    vi.stubGlobal("fetch", fetchMock);
    await expect(http.get("/owner/me/")).resolves.toEqual({ ok: true });
    expect(relogin).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith("/refresh/"))).toBe(false);
    configureHttp({ relogin: undefined });
  });

  it("ends the session when the refresh is refused", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => (url.endsWith("/refresh/") ? json({ detail: "no cookie" }, 401) : json({ detail: "expired" }, 401))),
    );
    await expect(http.get("/owner/me/")).rejects.toMatchObject({ status: 401 });
    expect(ended).toHaveBeenCalledTimes(1);
    expect(token).toBeNull();
  });

  it("toasts {detail} on writes but not on reads", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json({ detail: "The period is locked." }, 400)));
    await expect(http.post("/owner/companies/1/finance/transactions/", { amount: "1" })).rejects.toBeInstanceOf(ApiError);
    expect(errors.map((e) => e.detail)).toEqual(["The period is locked."]);
    await expect(http.get("/owner/companies/1/finance/transactions/")).rejects.toBeInstanceOf(ApiError);
    expect(errors).toHaveLength(1);
    await expect(http.get("/x/", undefined, { toast: true })).rejects.toBeInstanceOf(ApiError);
    expect(errors).toHaveLength(2);
  });

  it("keeps field errors for the form instead of a toast", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json({ amount: ["Must be positive."], name: "Too long." }, 400)));
    const error = await http.post("/x/", {}).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).fieldErrors).toEqual({ amount: ["Must be positive."], name: ["Too long."] });
    expect(errors).toHaveLength(0);
  });

  it("turns a network failure into status 0", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("Failed to fetch"))));
    const error = (await http.patch("/x/", {}).catch((e: unknown) => e)) as ApiError;
    expect(error.status).toBe(0);
    expect(error.isNetwork).toBe(true);
    expect(errors).toHaveLength(1);
  });

  it("returns undefined for 204 and the raw response on demand", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json(null, 204)));
    await expect(http.delete("/x/")).resolves.toBeUndefined();
    vi.stubGlobal("fetch", vi.fn(async () => new Response("file", { status: 200 })));
    const response = await request<Response>("/files/abc/", { raw: true });
    expect(await response.text()).toBe("file");
  });

  it("sends anonymous requests without a token and without refreshing", async () => {
    const fetchMock = vi.fn(async () => json({ detail: "bad" }, 401));
    vi.stubGlobal("fetch", fetchMock);
    await expect(request("/owner/auth/dev-login/", { method: "POST", json: {}, anonymous: true })).rejects.toBeInstanceOf(ApiError);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(headerOf((fetchMock.mock.calls[0] as unknown as [string, RequestInit])[1], "Authorization")).toBeNull();
  });
});

describe("helpers", () => {
  it("builds URLs and queries", () => {
    expect(buildQuery({ q: "fridge", branch: [1, 2], empty: "", none: null, page: 2, flag: false })).toBe("?q=fridge&branch=1&branch=2&page=2&flag=false");
    expect(buildQuery()).toBe("");
    expect(apiUrl("owner/me/")).toBe("/api/v1/owner/me/");
    expect(apiUrl("/api/v1/owner/companies/1/tasks/9/confirm/")).toBe("/api/v1/owner/companies/1/tasks/9/confirm/");
    expect(ownerPath(12, "/pulse/")).toBe("/owner/companies/12/pulse/");
  });

  it("parses DRF error bodies", () => {
    expect(parseErrorBody({ detail: "No.", code: "needs_proof" })).toEqual({ detail: "No.", fields: {}, code: "needs_proof" });
    expect(parseErrorBody({ non_field_errors: ["Locked."] })).toEqual({ detail: "Locked.", fields: {}, code: null });
    expect(parseErrorBody(["One."])).toEqual({ detail: "One.", fields: {}, code: null });
    expect(parseErrorBody("<html>Bad gateway</html>").detail).toBeNull();
    expect(parseErrorBody(null)).toEqual({ detail: null, fields: {}, code: null });
  });

  it("keys every query by company and module", () => {
    expect(qk(12, "finance", "transactions", { page: 2 })).toEqual([12, "finance", "transactions", { page: 2 }]);
    expect(moduleKey(12, "finance")).toEqual([12, "finance"]);
    expect(keys.pulse(3)).toEqual([3, "shell", "pulse", {}]);
    expect(keys.search(3, "madina")).toEqual([3, "shell", "search", { q: "madina" }]);
  });
});
