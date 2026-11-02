// Round 2: finance offers only what the viewer may do (the owner sees everything either way).
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { CommandCtx } from "@/core/modules";
import type { Perm } from "@/core/perms";
import { hasPerm } from "@/core/perms";
import { mergeModuleMessages } from "@/i18n";
import { useSessionStore } from "@/stores/session";
import { company, json, me } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

import AccountCard from "../components/AccountCard.vue";
import QuickAddDialog from "../components/QuickAddDialog.vue";
import en from "../i18n/en.json";
import module from "../index";
import type { Account, Options } from "../types";

const PREFIX = "/api/v1/owner/companies/1/finance/";

function stub(routes: Record<string, () => Response>): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init?: RequestInit) => {
      const path = input.replace(PREFIX, "").split("?")[0]!;
      return routes[`${init?.method ?? "GET"} ${path}`]?.() ?? json({ detail: "Not found." }, 404);
    }),
  );
}

beforeEach(() => {
  mergeModuleMessages("finance", { en, ru: en, uz: en });
  localStorage.clear();
});

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

/** Signs the test in as a non-owner holding these permissions in company 1. */
function as(permissions: Perm[]): void {
  useSessionStore().me = me([company({ is_owner: false, permissions })]);
}

const options = (): Options =>
  ({
    base_currency: "UZS",
    today: "2026-10-21",
    accounts: [{ id: 3, name: "Kassa", kind: "cash", currency: "UZS", branch_id: 1 }],
    transfer_targets: [],
    members: [],
    branches: [{ id: 1, name: "Chilonzor", code: "CHL" }],
    projects: [],
    receipt_required_over: null,
    locked_until: null,
    rate: { rate: "12168.15", stale: false, source: "cbu" },
  }) as unknown as Options;

describe("finance permissions", () => {
  it("offers opening balances on account cards only to someone who manages finance", async () => {
    const app = await testApp("/c/1/finance/accounts?setup=opening");
    as(["finance.view", "finance.record"]);
    const account = { id: 3, name: "Kassa", kind: "cash", currency: "UZS", color: "", balance: "0.00", base_balance: "0.00", is_active: true, can_record: true, spark: [], last_activity: null } as unknown as Account;
    const { wrapper } = mountWithProviders(AccountCard, { plugins: app.plugins, props: { account, setup: true } });
    expect(wrapper.text()).not.toContain(en["finance.accounts.setOpening"]);
    wrapper.unmount();
  });

  it("opens quick add as an expense when someone who can't manage asks for an opening balance", async () => {
    stub({ "GET options/": () => json(options()), "GET categories/": () => json([]) });
    const app = await testApp("/c/1/finance/accounts");
    as(["finance.view", "finance.record"]);
    mountWithProviders(QuickAddDialog, { plugins: app.plugins, props: { open: true, request: { mode: "opening", account: 3 } } });
    await flushPromises();
    await flushPromises();
    expect(document.body.textContent).toContain(en["finance.quick.title.expense"]);
    expect(document.body.textContent).not.toContain(en["finance.quick.mode.opening"]);
  });

  it("lists the debt and opening commands only for people who can open the page they go to", () => {
    const commands = (perms: Perm[]) => {
      const subject = { ...company({ is_owner: false, permissions: perms }) };
      const ctx = { companyId: 1, company: subject, router: {} as never, t: (key: string) => key, can: (perm) => hasPerm(subject, perm), go: () => undefined } as CommandCtx;
      return module.commands!(ctx)
        .filter((command) => hasPerm(subject, command.perm))
        .map((command) => command.id);
    };
    // Records money but may not see the debts page.
    expect(commands(["finance.record"])).not.toContain("finance.new-debt");
    expect(commands(["finance.record", "finance.view"])).toContain("finance.new-debt");
    // Manages the books but sees neither accounts nor entries.
    expect(commands(["finance.manage"])).not.toContain("finance.opening");
    expect(commands(["finance.manage", "finance.view"])).toContain("finance.opening");
  });

  it("opens Record debt when the palette's ?new=1 arrives on the debts page already open", async () => {
    stub({
      "GET debts/": () => json({ count: 0, next: null, previous: null, results: [] }),
      "GET options/": () => json(options()),
      "GET categories/": () => json([]),
    });
    const DebtsPage = (await import("../pages/DebtsPage.vue")).default;
    const app = await testApp("/c/1/finance/debts");
    const { wrapper } = mountWithProviders(DebtsPage, { plugins: app.plugins });
    await flushPromises();
    await app.router.push("/c/1/finance/debts?new=1");
    await flushPromises();
    await flushPromises();
    expect(document.querySelector('[role="dialog"]')?.textContent).toContain(en["finance.debts.newTitle"]);
    expect(app.router.currentRoute.value.query.new).toBeUndefined();
    wrapper.unmount();
  });

  it("says the debts summary failed, with a retry, instead of an empty total", async () => {
    stub({
      "GET debts/": () => json({ count: 0, next: null, previous: null, results: [] }),
      "GET debts/summary/": () => json({ detail: "Server error." }, 500),
    });
    const DebtsPage = (await import("../pages/DebtsPage.vue")).default;
    const app = await testApp("/c/1/finance/debts");
    const { wrapper } = mountWithProviders(DebtsPage, { plugins: app.plugins });
    await flushPromises();
    await flushPromises();
    expect(document.querySelector('[data-testid="debt-summary-error"]')).not.toBeNull();
    wrapper.unmount();
  });

  it("links the stale-rate alert and the first-run opening balances only for someone who manages finance", async () => {
    const side = { total: "0.00", overdue: "0.00", count: 0, overdue_count: 0 };
    const overview = (hasLedger: boolean) => ({
      currency: "UZS",
      today: "2026-10-21",
      cash: { on: "2026-10-21", currency: "UZS", total: "0.00", complete: true, by_currency: [], accounts: [], rate: { rate: "12168.15", stale: true, source: "cbu" } },
      month: { from: "2026-10-01", to: "2026-10-21", income: "0.00", expense: "0.00", profit: "0.00", previous: { from: "2026-09-01", to: "2026-09-21", income: "0.00", expense: "0.00", profit: "0.00" } },
      receivable: side,
      payable: side,
      due_soon: [],
      pending: { count: 0, total: "0.00" },
      top_expenses: [],
      negative_accounts: [],
      rate: { rate: "12168.15", date: "2026-10-14", stale: true, source: "cbu" },
      has_ledger: hasLedger,
      locked_until: null,
    });
    const FinanceOverviewPage = (await import("../pages/FinanceOverviewPage.vue")).default;
    for (const hasLedger of [true, false]) {
      stub({ "GET overview/": () => json(overview(hasLedger)), "GET reports/cash-flow/": () => json({ series: [], totals: { income: "0.00", expense: "0.00", net: "0.00" } }) });
      const app = await testApp("/c/1/finance");
      as(["finance.view"]);
      const { wrapper } = mountWithProviders(FinanceOverviewPage, { plugins: app.plugins });
      await flushPromises();
      await flushPromises();
      const hrefs = [...document.querySelectorAll("a")].map((a) => a.getAttribute("href") ?? "");
      expect(hrefs.some((href) => href.includes("/finance/settings"))).toBe(false);
      expect(hrefs.some((href) => href.includes("setup=opening"))).toBe(false);
      wrapper.unmount();
      document.body.innerHTML = "";
      vi.unstubAllGlobals();
    }
  });
});
