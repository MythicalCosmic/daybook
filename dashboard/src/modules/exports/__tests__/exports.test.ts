// The registry first, as in the app: it is what loads every module's index.ts (see core/modules.ts).
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ExportJob } from "@/api/types";
import { toasts } from "@/components/useToast";
import { mergeModuleMessages } from "@/i18n";
import { json } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

import { createExport, exportKeys, getExport, isBuilding, listExporters, listExports } from "../api";
import NewExportDialog from "../components/NewExportDialog.vue";
import en from "../i18n/en.json";
import module from "../index";
import ExportsPage from "../pages/ExportsPage.vue";

interface Call {
  method: string;
  url: string;
  body: unknown;
}

function stub(routes: Record<string, (call: Call) => Response>): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init?: RequestInit) => {
      const call = { method: init?.method ?? "GET", url: input, body: init?.body ? JSON.parse(String(init.body)) : undefined };
      calls.push(call);
      const path = input.replace("/api/v1/owner/companies/1/", "").split("?")[0]!;
      return routes[`${call.method} ${path}`]?.(call) ?? json({ detail: "Not found." }, 404);
    }),
  );
  return calls;
}

const job = (overrides: Partial<ExportJob>): ExportJob => ({
  id: 1,
  kind: "tasks.tasks",
  label: "Tasks",
  format: "xlsx",
  params: {},
  status: "ready",
  rows: 120,
  error: "",
  deliver_telegram: false,
  sensitive: false,
  created_at: new Date(Date.now() - 3600_000).toISOString(),
  finished_at: new Date().toISOString(),
  expires_at: new Date(Date.now() + 6 * 86400_000).toISOString(),
  file_name: "tasks-2026-10-21.xlsx",
  file_url: "/api/v1/files/old-token/",
  ...overrides,
});

const page = (results: ExportJob[]) => json({ count: results.length, next: null, previous: null, results });

beforeEach(() => {
  mergeModuleMessages("exports", { en, ru: en, uz: en });
  toasts.splice(0, toasts.length);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  document.body.innerHTML = "";
});

describe("api", () => {
  it("calls the W0 export endpoints, never sending to Telegram unless asked", async () => {
    const calls = stub({
      "GET exports/": () => page([]),
      "GET exports/kinds/": () => json([]),
      "POST exports/": () => json({ id: 9 }, 202),
      "GET exports/9/": () => json(job({ id: 9 })),
    });
    await listExports(1, { page: 2, page_size: 25 });
    await listExporters(1);
    await createExport(1, { kind: "tasks.tasks" });
    await createExport(1, { kind: "payroll.payslips", format: "csv", params: { run: 3 }, deliverTelegram: true });
    await getExport(1, 9);
    expect(calls.map((c) => `${c.method} ${c.url}`)).toEqual([
      "GET /api/v1/owner/companies/1/exports/?page=2&page_size=25",
      "GET /api/v1/owner/companies/1/exports/kinds/",
      "POST /api/v1/owner/companies/1/exports/",
      "POST /api/v1/owner/companies/1/exports/",
      "GET /api/v1/owner/companies/1/exports/9/",
    ]);
    expect(calls[2]!.body).toEqual({ kind: "tasks.tasks", format: "xlsx", params: {}, deliver_telegram: false });
    expect(calls[3]!.body).toEqual({ kind: "payroll.payslips", format: "csv", params: { run: 3 }, deliver_telegram: true });
  });

  it("registers behind data.export with the exports pulse key", () => {
    expect(module).toMatchObject({ id: "exports", group: "company", order: 20, perm: "data.export", invalidates: ["exports.exports"] });
    expect(exportKeys.list(1, { page: 1, page_size: 25 })).toEqual([1, "exports", "list", { page: 1, page_size: 25 }]);
    expect(isBuilding({ status: "running" })).toBe(true);
    expect(isBuilding({ status: "ready" })).toBe(false);
  });
});

describe("ExportsPage", () => {
  it("lists exports with their state and downloads through a fresh signed link", async () => {
    const clicks: string[] = [];
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      clicks.push(`${this.getAttribute("href")} ${this.download}`);
    });
    const calls = stub({
      "GET exports/": () =>
        page([
          job({ id: 1 }),
          job({ id: 2, label: "Payslips", kind: "payroll.payslips", status: "failed", error: "The run has no payslips yet.", rows: null, file_url: null, file_name: null, sensitive: true }),
          job({ id: 3, label: "Team", kind: "members.people", status: "running", rows: null, file_url: null, file_name: null }),
        ]),
      "GET exports/1/": () => json(job({ id: 1, file_url: "/api/v1/files/fresh-token/" })),
    });
    const app = await testApp("/c/1/exports");
    const { wrapper } = mountWithProviders(ExportsPage, { plugins: app.plugins });
    await flushPromises();
    const text = wrapper.text();
    expect(text).toContain("Ready");
    expect(text).toContain("Failed");
    expect(text).toContain("Building");
    await wrapper.findAll("button").find((b) => b.text() === "Download")!.trigger("click");
    await flushPromises();
    expect(calls.some((c) => c.url.endsWith("/exports/1/"))).toBe(true);
    expect(clicks).toEqual(["/api/v1/files/fresh-token/ tasks-2026-10-21.xlsx"]);
  });

  it("makes a failed export again with the same choices, but not to Telegram", async () => {
    const calls = stub({
      "GET exports/": () => page([job({ id: 2, kind: "finance.transactions", label: "Transactions", format: "csv", params: { from: "2026-10-01" }, deliver_telegram: true, status: "failed", file_url: null })]),
      "POST exports/": () => json({ id: 10 }, 202),
    });
    const app = await testApp("/c/1/exports");
    const { wrapper } = mountWithProviders(ExportsPage, { plugins: app.plugins });
    await flushPromises();
    await wrapper.findAll("button").find((b) => b.text() === "Export again")!.trigger("click");
    await flushPromises();
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({ kind: "finance.transactions", format: "csv", params: { from: "2026-10-01" }, deliver_telegram: false });
    expect(toasts.at(-1)?.title).toBe("Building “Transactions”");
  });

  it("explains an empty list and offers a new export instead of an empty table", async () => {
    stub({ "GET exports/": () => page([]) });
    const app = await testApp("/c/1/exports");
    const { wrapper } = mountWithProviders(ExportsPage, { plugins: app.plugins });
    await flushPromises();
    const empty = wrapper.find("[data-exports-empty]");
    expect(empty.exists()).toBe(true);
    expect(empty.text()).toContain(en["exports.empty.body"]);
    expect(empty.findAll("button").some((b) => b.text() === en["exports.new"])).toBe(true);
    expect(wrapper.find("table").exists()).toBe(false);
  });
});

describe("NewExportDialog", () => {
  it("offers what the person may export, warns about sensitive files and keeps Telegram off by default", async () => {
    const calls = stub({
      "GET exports/kinds/": () =>
        json([
          { kind: "payroll.payslips", label: "Payslips", sensitive: true, formats: ["xlsx"], columns: [] },
          { kind: "tasks.tasks", label: "Tasks", sensitive: false, formats: ["xlsx", "csv"], columns: [] },
        ]),
      "POST exports/": () => json({ id: 11 }, 202),
    });
    const app = await testApp("/c/1/exports");
    const { wrapper } = mountWithProviders(NewExportDialog, { plugins: app.plugins, props: { open: true } });
    await flushPromises();
    await flushPromises();
    const dialog = document.body;
    expect(dialog.textContent).toContain(en["exports.dialog.sensitive"]);
    const checkbox = dialog.querySelector<HTMLButtonElement>('[role="checkbox"]');
    expect(checkbox?.getAttribute("aria-checked")).toBe("false");
    dialog.querySelector<HTMLFormElement>("form#new-export")!.dispatchEvent(new Event("submit", { cancelable: true }));
    await flushPromises();
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({ kind: "payroll.payslips", format: "xlsx", params: {}, deliver_telegram: false });
    wrapper.unmount();
  });
});
