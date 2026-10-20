import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

type Call = { url: string; init: RequestInit };

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

describe("apiForm", () => {
  let calls: Call[];
  let replies: Response[];

  beforeEach(() => {
    vi.resetModules();
    calls = [];
    replies = [];
    vi.stubEnv("VITE_DEV_INIT_DATA", "user=%7B%22id%22%3A4242%7D&hash=abc");
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init: RequestInit) => {
        calls.push({ url, init });
        if (url.endsWith("/auth/telegram/")) return json({ access: `token-${calls.length}` });
        return replies.shift() ?? json({ ok: true });
      }),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  it("builds multipart fields: strings for values, files kept, empty ones left out, arrays repeated", async () => {
    const { toFormData } = await import("./client");
    const photo = new File(["jpeg bytes"], "receipt.jpg", { type: "image/jpeg" });
    const form = toFormData({
      amount: "185000.00",
      quantity: 3,
      from_own_money: true,
      reimbursed: false,
      note: null,
      project: undefined,
      receipt: photo,
      tags: ["taxi", "supplier"],
      scan: new Blob(["x"], { type: "image/png" }),
    });
    expect(form.get("amount")).toBe("185000.00");
    expect(form.get("quantity")).toBe("3");
    expect(form.get("from_own_money")).toBe("true");
    expect(form.get("reimbursed")).toBe("false");
    expect(form.has("note")).toBe(false);
    expect(form.has("project")).toBe(false);
    expect((form.get("receipt") as File).name).toBe("receipt.jpg");
    expect(form.getAll("tags")).toEqual(["taxi", "supplier"]);
    expect((form.get("scan") as File).name).toBe("upload");
  });

  it("signs in, then posts the form with the token and no Content-Type of its own", async () => {
    const { apiForm } = await import("./client");
    replies.push(json({ id: 9, status: "submitted" }, 201));
    const result = await apiForm<{ id: number }>("/companies/1/expenses/", { amount: "185000.00", receipt: new File(["x"], "r.jpg") });

    expect(result).toEqual({ id: 9, status: "submitted" });
    expect(calls.map((call) => call.url)).toEqual(["/api/v1/auth/telegram/", "/api/v1/companies/1/expenses/"]);
    const upload = calls[1].init;
    expect(upload.method).toBe("POST");
    expect(upload.body).toBeInstanceOf(FormData);
    expect((upload.body as FormData).get("amount")).toBe("185000.00");
    const headers = upload.headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer token-1");
    expect(headers["Content-Type"]).toBeUndefined();
  });

  it("takes a ready FormData and another method", async () => {
    const { apiForm } = await import("./client");
    const form = new FormData();
    form.append("photo", new File(["x"], "me.jpg"));
    await apiForm("/companies/1/hr/me/photo/", form, { method: "PATCH" });
    expect(calls[1].init.method).toBe("PATCH");
    expect(calls[1].init.body).toBe(form);
  });

  it("signs in again and resends the same form once when the token expired", async () => {
    const { apiForm } = await import("./client");
    replies.push(json({ detail: "expired" }, 401), json({ id: 1 }, 201));
    const result = await apiForm<{ id: number }>("/companies/1/expenses/", { amount: "1" });
    expect(result).toEqual({ id: 1 });
    expect(calls.map((call) => call.url)).toEqual([
      "/api/v1/auth/telegram/",
      "/api/v1/companies/1/expenses/",
      "/api/v1/auth/telegram/",
      "/api/v1/companies/1/expenses/",
    ]);
    expect((calls[3].init.headers as Record<string, string>).Authorization).toBe("Bearer token-3");
    expect((calls[3].init.body as FormData).get("amount")).toBe("1");
  });

  it("raises the server's explanation on a refusal", async () => {
    const { apiForm, ApiError } = await import("./client");
    replies.push(json({ amount: ["Over your limit."] }, 400));
    const failure = await apiForm("/companies/1/expenses/", { amount: "99999999" }).catch((error: unknown) => error);
    expect(failure).toBeInstanceOf(ApiError);
    expect((failure as InstanceType<typeof ApiError>).status).toBe(400);
    expect((failure as InstanceType<typeof ApiError>).detail).toBe("Over your limit.");
  });
});
