// Round 2: a refusal about a field a finance form doesn't show is said, never swallowed.
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import TextInput from "@/components/TextInput.vue";
import { toasts } from "@/components/useToast";
import { mergeModuleMessages } from "@/i18n";
import { json } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

import AccountFormDialog from "../components/AccountFormDialog.vue";
import TransactionDrawer from "../components/TransactionDrawer.vue";
import en from "../i18n/en.json";
import type { Options, Transaction } from "../types";

// Whole pages and dialogs mount here: slow while the rest of the suite runs beside them.
vi.setConfig({ testTimeout: 20_000 });

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
  toasts.splice(0, toasts.length);
});

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

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
    locked_until: "2026-09-30",
    rate: { rate: "12168.15", stale: false, source: "cbu" },
  }) as unknown as Options;

const button = (label: string) => [...document.querySelectorAll<HTMLButtonElement>("button")].find((b) => b.textContent?.trim() === label)!;

describe("finance lists", () => {
  it("hand vue-query's cancel signal to the request, so a list left behind is not downloaded in full", async () => {
    const signals: Array<AbortSignal | undefined> = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string, init?: RequestInit) => {
        if (input.includes("/transactions/") || input.includes("/debts/") || input.includes("/counterparties/")) signals.push(init?.signal ?? undefined);
        return json({ count: 0, next: null, previous: null, results: [] });
      }),
    );
    const { useCounterparties, useDebts, useTransactions } = await import("../api");
    const { defineComponent, h } = await import("vue");
    const Lists = defineComponent({
      setup() {
        useTransactions({ page: 1 });
        useDebts({ page: 1 });
        useCounterparties({ page: 1 });
        return () => h("div");
      },
    });
    const app = await testApp("/c/1/finance/transactions");
    const { wrapper } = mountWithProviders(Lists, { plugins: app.plugins });
    await flushPromises();
    expect(signals).toHaveLength(3);
    expect(signals.every((signal) => signal instanceof AbortSignal)).toBe(true);
    wrapper.unmount();
  });
});

describe("finance forms say field-only refusals", () => {
  it("a new account refused for its opening day", async () => {
    stub({ "GET options/": () => json(options()), "POST accounts/": () => json({ opening_on: ["The books are closed until 30 September."] }, 400) });
    const app = await testApp("/c/1/finance/accounts");
    const { wrapper } = mountWithProviders(AccountFormDialog, { plugins: app.plugins, props: { open: true } });
    await flushPromises();
    await flushPromises();
    wrapper.findComponent(TextInput).vm.$emit("update:modelValue", "Kassa 2");
    await flushPromises();
    button(en["finance.accounts.create"]).click();
    await flushPromises();
    await flushPromises();
    expect(toasts.map((toast) => toast.title)).toContain("The books are closed until 30 September.");
    wrapper.unmount();
  });

  it("a debt's correction refused for its due day", async () => {
    const debt = {
      id: 9,
      direction: "receivable",
      direction_label: "Owed to us",
      kind: "trade",
      kind_label: "Sold on credit",
      status: "open",
      party: { id: 2, name: "Grand Pharm", type: "counterparty" },
      currency: "UZS",
      amount: "1200000.00",
      paid: "0.00",
      outstanding: "1200000.00",
      base_outstanding: "1200000.00",
      issued_on: "2026-10-01",
      due_on: "2026-10-30",
      days_overdue: 0,
      description: "Dori partiyasi",
      branch: { id: 1, name: "Chilonzor", code: "CHL" },
      responsible: null,
      is_opening: false,
      is_locked: false,
      source: null,
      masked: false,
      created_at: "2026-10-01T10:00:00+05:00",
    };
    stub({
      "GET debts/9/": () => json({ debt, installments: [], payments: [], can_pay: true, can_write_off: true, can_cancel: true }),
      "GET options/": () => json(options()),
      "PATCH debts/9/": () => json({ due_on: ["The due day can't be before the day it was issued."] }, 400),
    });
    const app = await testApp("/c/1/finance/debts?debt=9");
    const { default: DebtDrawer } = await import("../components/DebtDrawer.vue");
    const { wrapper } = mountWithProviders(DebtDrawer, { plugins: app.plugins });
    await flushPromises();
    await flushPromises();
    button("Edit").click();
    await flushPromises();
    button("Save").click();
    await flushPromises();
    await flushPromises();
    expect(toasts.map((toast) => toast.title)).toContain("The due day can't be before the day it was issued.");
    wrapper.unmount();
  });

  it("an entry's correction refused for its day", async () => {
    const entry = {
      id: 5,
      kind: "expense",
      kind_label: "Expense",
      status: "posted",
      status_label: "Posted",
      occurred_on: "2026-10-20",
      account: { id: 3, name: "Kassa", kind: "cash", currency: "UZS" },
      amount: "-450000.00",
      currency: "UZS",
      rate: "1.000000",
      rate_stale: false,
      base_amount: "-450000.00",
      category: null,
      counterparty: null,
      membership: null,
      branch: null,
      project: null,
      description: "Benzin",
      source: null,
      created_by: "Nigora Azimova",
      created_at: "2026-10-20T10:00:00+05:00",
      approved_by: null,
      approved_at: null,
      voided_by: null,
      voided_at: null,
      void_reason: "",
      receipts: [],
      masked: false,
      is_manual: true,
      can_edit: true,
      can_void: true,
      can_approve: false,
    } as unknown as Transaction;
    stub({
      "GET transactions/5/": () => json(entry),
      "GET options/": () => json(options()),
      "GET categories/": () => json([]),
      "PATCH transactions/5/": () => json({ occurred_on: ["The books are closed until 30 September."] }, 400),
    });
    const app = await testApp("/c/1/finance/transactions?txn=5");
    const { wrapper } = mountWithProviders(TransactionDrawer, { plugins: app.plugins });
    await flushPromises();
    await flushPromises();
    button("Edit").click();
    await flushPromises();
    button("Save").click();
    await flushPromises();
    await flushPromises();
    expect(toasts.map((toast) => toast.title)).toContain("The books are closed until 30 September.");
    wrapper.unmount();
  });
});
