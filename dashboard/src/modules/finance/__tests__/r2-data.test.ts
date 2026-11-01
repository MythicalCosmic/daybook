// Round 2: money that lands where the person meant it to.
import "@/core/modules";

import { flushPromises, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import FileDrop from "@/components/FileDrop.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import TextInput from "@/components/TextInput.vue";
import { toasts } from "@/components/useToast";
import { mergeModuleMessages } from "@/i18n";
import { useSessionStore } from "@/stores/session";
import { company, json, me } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

import PnlTable from "../components/reports/PnlTable.vue";
import QuickAddDialog from "../components/QuickAddDialog.vue";
import TransactionDrawer from "../components/TransactionDrawer.vue";
import en from "../i18n/en.json";
import type { Options, Pnl, PnlNode, Transaction } from "../types";

interface Call {
  method: string;
  url: string;
  body: unknown;
}

const PREFIX = "/api/v1/owner/companies/1/finance/";

function stub(routes: Record<string, (call: Call) => Response | Promise<Response>>): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init?: RequestInit) => {
      const raw = init?.body;
      const body = raw instanceof FormData ? Object.fromEntries(raw.entries()) : raw ? JSON.parse(String(raw)) : undefined;
      const call = { method: init?.method ?? "GET", url: input, body };
      calls.push(call);
      const path = input.replace(PREFIX, "").split("?")[0]!;
      return routes[`${call.method} ${path}`]?.(call) ?? json({ detail: "Not found." }, 404);
    }),
  );
  return calls;
}

beforeEach(() => {
  mergeModuleMessages("finance", { en, ru: en, uz: en });
  toasts.splice(0, toasts.length);
  localStorage.clear();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  document.body.innerHTML = "";
});

const options = (): Options =>
  ({
    base_currency: "UZS",
    today: "2026-10-21",
    accounts: [
      { id: 3, name: "Kassa", kind: "cash", currency: "UZS", branch_id: 1 },
      { id: 9, name: "Dollar safe", kind: "cash", currency: "USD", branch_id: 1 },
    ],
    transfer_targets: [
      { id: 3, name: "Kassa", kind: "cash", currency: "UZS", branch_id: 1 },
      { id: 9, name: "Dollar safe", kind: "cash", currency: "USD", branch_id: 1 },
    ],
    members: [],
    branches: [
      { id: 1, name: "Chilonzor", code: "CHL" },
      { id: 2, name: "Yunusobod", code: "YUN" },
    ],
    projects: [],
    receipt_required_over: null,
    locked_until: null,
    rate: { rate: "12168.15", stale: false, source: "cbu" },
  }) as unknown as Options;

const entry = (overrides: Partial<Transaction> = {}): Transaction =>
  ({
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
    debt_id: null,
    transfer_id: null,
    is_contra: false,
    description: "",
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
    ...overrides,
  }) as Transaction;

describe("TransactionDrawer receipts", () => {
  it("attaches every dropped receipt to the entry it was dropped on, even when the drawer moves on mid-upload", async () => {
    let release!: () => void;
    const first = new Promise<void>((resolve) => (release = resolve));
    let uploads = 0;
    const calls = stub({
      "GET transactions/5/": () => json(entry()),
      "GET transactions/6/": () => json(entry({ id: 6 })),
      "POST transactions/5/receipts/": async () => {
        uploads += 1;
        if (uploads === 1) await first;
        return json({ id: 40 + uploads, url: "/media/r.jpg", thumb_url: null, is_image: true }, 201);
      },
      "POST transactions/6/receipts/": () => json({ id: 99, url: "/media/x.jpg", thumb_url: null, is_image: true }, 201),
    });
    const app = await testApp("/c/1/finance/transactions?txn=5");
    const { wrapper } = mountWithProviders(TransactionDrawer, { plugins: app.plugins });
    await flushPromises();
    await flushPromises();
    const drop = wrapper.findComponent(FileDrop);
    drop.vm.$emit("update:modelValue", [new File(["a"], "a.jpg", { type: "image/jpeg" }), new File(["b"], "b.jpg", { type: "image/jpeg" })]);
    await flushPromises();
    // The owner opens the next entry while the first photo is still going up.
    await app.router.push("/c/1/finance/transactions?txn=6");
    await flushPromises();
    release();
    await flushPromises();
    await flushPromises();
    const posted = calls.filter((c) => c.method === "POST").map((c) => c.url.replace(PREFIX, ""));
    expect(posted).toEqual(["transactions/5/receipts/", "transactions/5/receipts/"]);
    wrapper.unmount();
  });
});

describe("QuickAddDialog accounts", () => {
  it("drops a dollar account picked for a transfer when the entry becomes a so‘m expense", async () => {
    const calls = stub({
      "GET options/": () => json(options()),
      "GET categories/": () => json([{ id: 4, name: "Dori vositalari", kind: "expense", color: "", icon: "", is_system: false, system_code: "", is_active: true, is_capex: false, is_sensitive: false, parent: null, children: [] }]),
      "POST transactions/": () => json({ id: 77, amount: "-185000.00", currency: "UZS" }, 201),
    });
    const app = await testApp("/c/1/finance/transactions");
    const { wrapper } = mountWithProviders(QuickAddDialog, { plugins: app.plugins, props: { open: true, request: { mode: "transfer", amount: "185000", category: 4 } } });
    await flushPromises();
    await flushPromises();
    // From: the dollar safe (transfers offer every account).
    document.querySelector<HTMLButtonElement>('[role=radio][data-id="9"]')!.click();
    await flushPromises();
    (wrapper.findComponent(SegmentedControl) as VueWrapper).vm.$emit("update:modelValue", "expense");
    await flushPromises();
    document.querySelector<HTMLButtonElement>('[data-testid="quick-save"]')!.click();
    await flushPromises();
    const post = calls.find((c) => c.method === "POST");
    expect(post?.body).toMatchObject({ kind: "expense", amount: "185000", account: 3 });
    wrapper.unmount();
  });
});

describe("CounterpartyFormDialog typing", () => {
  it("keeps what is typed when the counterparty is fetched again while the dialog is open", async () => {
    stub({ "GET categories/": () => json([]) });
    const app = await testApp("/c/1/finance/counterparties/2");
    const { default: CounterpartyFormDialog } = await import("../components/CounterpartyFormDialog.vue");
    const { defineComponent, h, ref } = await import("vue");
    const party = ref({ id: 2, name: "Grand Pharm", kind: "supplier", tags: ["dori"], default_category: null, is_active: true });
    const Host = defineComponent({ setup: () => () => h(CounterpartyFormDialog, { open: true, party: party.value } as never) });
    const { wrapper } = mountWithProviders(Host, { plugins: app.plugins });
    await flushPromises();
    const name = wrapper.findComponent(TextInput);
    name.vm.$emit("update:modelValue", "Grand Pharm Ulgurji");
    await flushPromises();
    expect((wrapper.findComponent(TextInput).props() as { modelValue: string }).modelValue).toBe("Grand Pharm Ulgurji");
    // A pulse refetches the party: the same counterparty, a new object.
    party.value = { ...party.value, tags: [...party.value.tags] };
    await flushPromises();
    expect((wrapper.findComponent(TextInput).props() as { modelValue: string }).modelValue).toBe("Grand Pharm Ulgurji");
    wrapper.unmount();
  });
});

describe("DebtFormDialog branch", () => {
  it("lets someone limited to two branches pick the debt's branch, and shows the server's branch refusal", async () => {
    const calls = stub({
      "GET options/": () => json(options()),
      "GET categories/": () => json([{ id: 4, name: "Dori savdosi", kind: "income", color: "", icon: "", is_system: false, system_code: "", is_active: true, is_capex: false, is_sensitive: false, parent: null, children: [] }]),
      "POST debts/": () => json({ branch: ["Pick one of your branches."] }, 400),
    });
    const app = await testApp("/c/1/finance/debts");
    useSessionStore().me = me([
      company({
        is_owner: false,
        permissions: ["finance.view", "finance.record"],
        branch_scope: [1, 2],
        branches: [
          { id: 1, name: "Chilonzor", code: "CHL" },
          { id: 2, name: "Yunusobod", code: "YUN" },
        ],
      }),
    ]);
    const { default: DebtFormDialog } = await import("../components/DebtFormDialog.vue");
    const { wrapper } = mountWithProviders(DebtFormDialog, { plugins: app.plugins, props: { open: true, counterparty: { id: 2, name: "Grand Pharm" } } });
    await flushPromises();
    await flushPromises();
    expect(document.querySelector('[data-testid="debt-branch"]')).not.toBeNull();
    const { default: MoneyInput } = await import("@/components/MoneyInput.vue");
    wrapper.findComponent(MoneyInput).vm.$emit("update:modelValue", "500000.00");
    const { default: ComboBox } = await import("@/components/ComboBox.vue");
    // The second combo box is the category (the first is the counterparty).
    wrapper.findAllComponents(ComboBox).at(-1)!.vm.$emit("update:modelValue", 4);
    await flushPromises();
    const save = [...document.querySelectorAll<HTMLButtonElement>("button")].find((b) => b.textContent?.trim() === en["finance.debts.create"])!;
    save.click();
    await flushPromises();
    await flushPromises();
    const post = calls.find((c) => c.method === "POST");
    expect(post?.body).toMatchObject({ branch: 1 });
    expect(document.body.textContent).toContain("Pick one of your branches.");
    wrapper.unmount();
  });
});

const node = (id: number, amounts: string[], children: PnlNode[] = [], own: string[] = amounts.map(() => "0.00")): PnlNode => ({
  id,
  name: `Category ${id}`,
  color: "",
  system_code: "",
  is_sensitive: false,
  amounts,
  total: String(amounts.reduce((sum, value) => sum + Number(value), 0)),
  own,
  own_total: String(own.reduce((sum, value) => sum + Number(value), 0)),
  previous: null,
  children,
});

function pnl(income: PnlNode[]): Pnl {
  return {
    range: { from: "2026-09-01", to: "2026-10-21" },
    compare: null,
    currency: "UZS",
    group: "month",
    periods: [
      { key: "2026-09", from: "2026-09-01", to: "2026-09-30" },
      { key: "2026-10", from: "2026-10-01", to: "2026-10-21" },
    ],
    income: { nodes: income, amounts: ["900000.00", "700000.00"], total: "1600000.00", previous: null },
    expense: { nodes: [], amounts: ["0.00", "0.00"], total: "0.00", previous: null },
    profit: { amounts: ["900000.00", "700000.00"], total: "1600000.00", previous: null },
    margin: { amounts: [null, null], total: null, previous: null },
  };
}

describe("PnlTable drill-down", () => {
  it("never sends the 'without a subcategory' line to every entry, and keeps the branch filter on its links", async () => {
    const parent = node(1, ["900000.00", "700000.00"], [node(11, ["800000.00", "650000.00"])], ["100000.00", "50000.00"]);
    const app = await testApp("/c/1/finance/reports/pnl?branch=2");
    const { wrapper } = mountWithProviders(PnlTable, { plugins: app.plugins, props: { data: pnl([parent]), branch: [2] } });
    await wrapper.find('button[aria-expanded="false"]').trigger("click");
    const hrefs = wrapper.findAll("a").map((a) => a.attributes("href") ?? "");
    // No link without a category: that would be every entry of the period.
    expect(hrefs.filter((href) => !href.includes("category="))).toEqual([]);
    expect(hrefs.every((href) => href.includes("branch=2"))).toBe(true);
    expect(hrefs).toContain("/c/1/finance/transactions?from=2026-09-01&to=2026-09-30&category=11&branch=2");
    wrapper.unmount();
  });
});
