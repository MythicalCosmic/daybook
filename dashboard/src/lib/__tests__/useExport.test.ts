import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { toasts } from "@/components/useToast";
import { useExport } from "@/lib/useExport";
import { useCompanyStore } from "@/stores/company";
import { useSessionStore } from "@/stores/session";
import { json, me } from "@/test/fixtures";

describe("useExport", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    setActivePinia(createPinia());
    useSessionStore().me = me();
    useCompanyStore().setCurrent(1);
    toasts.splice(0, toasts.length);
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("starts the export, polls until the file is ready and offers it", async () => {
    const statuses = ["pending", "running", "ready"];
    const calls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string, init?: RequestInit) => {
        calls.push(`${init?.method ?? "GET"} ${input}`);
        if (init?.method === "POST") return json({ id: 5 }, 202);
        const status = statuses.shift()!;
        return json({ id: 5, kind: "finance.transactions", format: "xlsx", status, rows: 12, file_url: status === "ready" ? "/api/v1/files/abc/" : null });
      }),
    );
    const { start, running } = useExport();
    const done = start({ kind: "finance.transactions", params: { from: "2026-10-01" } });
    expect(running.value).toBe(true);
    await vi.advanceTimersByTimeAsync(1500 * 3);
    const job = await done;
    expect(job?.status).toBe("ready");
    expect(calls[0]).toBe("POST /api/v1/owner/companies/1/exports/");
    expect(calls.filter((c) => c.startsWith("GET /api/v1/owner/companies/1/exports/5/"))).toHaveLength(3);
    expect(toasts.at(-1)?.tone).toBe("success");
    expect(toasts.at(-1)?.action).toBeDefined();
    expect(running.value).toBe(false);
  });

  it("tells the person when the export failed", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_input: string, init?: RequestInit) =>
        init?.method === "POST" ? json({ id: 6 }, 202) : json({ id: 6, status: "failed", file_url: null }),
      ),
    );
    const done = useExport().start({ kind: "sales.daily", format: "csv" });
    await vi.advanceTimersByTimeAsync(1500);
    expect(await done).toBeNull();
    expect(toasts.at(-1)?.tone).toBe("error");
  });
});
