// Round 2: sales forms that save what they show, and say why they can't.
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";
import { defineComponent, h, ref } from "vue";

import MoneyInput from "@/components/MoneyInput.vue";
import { ensureModuleMessages } from "@/i18n";
import { useSessionStore } from "@/stores/session";
import { company, json, me } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

import salesModule from "..";
import en from "../i18n/en.json";

interface Call {
  method: string;
  url: string;
  body: unknown;
}

function stub(routes: Record<string, (call: Call) => Response | Promise<Response>>): Call[] {
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

function options() {
  return {
    currency: "UZS",
    settings: { mode: "receipts", blind_cash_count: true, cash_tolerance: "5000.00", business_day_ends_at: "04:00" },
    today: "2026-10-21",
    branches: [{ id: 1, name: "Chilonzor", code: "CHL" }],
    registers: [{ id: 5, name: "Kassa 1", branch_id: 1, branch: "Chilonzor", is_active: true }],
    methods: [
      { id: 1, name: "Naqd", kind: "cash", is_active: true },
      { id: 2, name: "Uzcard", kind: "card", is_active: true },
    ],
    cashiers: [],
    receivers: [],
    categories: [],
    accounts: [],
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

/** Mounts a dialog closed, then opens it (opening is what fills these forms). */
async function openDialog(component: object, path: string) {
  const app = await testApp(path);
  await ensureModuleMessages(salesModule);
  const open = ref(false);
  const Host = defineComponent({ setup: () => () => h(component as never, { open: open.value, "onUpdate:open": (value: boolean) => (open.value = value) }) });
  const { wrapper } = mountWithProviders(Host, { plugins: app.plugins });
  await flushPromises();
  open.value = true;
  await flushPromises();
  await flushPromises();
  return { wrapper, open, app };
}

const button = (label: string) => [...document.querySelectorAll<HTMLButtonElement>("button")].find((b) => b.textContent?.trim() === label)!;

describe("EntryDialog", () => {
  it("won't save a receipt whose Total counts an amount with no payment method", async () => {
    const calls = stub({ "GET sales/options/": () => json(options()), "POST sales/entries/": () => json({ id: 1 }, 201) });
    const EntryDialog = (await import("../components/EntryDialog.vue")).default;
    const { wrapper } = await openDialog(EntryDialog, "/c/1/sales/entries");
    button(en["sales.entries.addMethod"]).click();
    await flushPromises();
    const amounts = wrapper.findAllComponents(MoneyInput);
    amounts[0]!.vm.$emit("update:modelValue", "100000.00");
    amounts[1]!.vm.$emit("update:modelValue", "50000.00");
    await flushPromises();
    button(en["sales.entries.submit"]).click();
    await flushPromises();
    expect(calls.some((c) => c.method === "POST")).toBe(false);
    expect(document.body.textContent).toContain(en["sales.entries.needMethod"]);
    wrapper.unmount();
  });

  it("shows a field-only refusal from the server instead of closing silently", async () => {
    stub({ "GET sales/options/": () => json(options()), "POST sales/entries/": () => json({ payments: ["Uzcard is switched off."] }, 400) });
    const EntryDialog = (await import("../components/EntryDialog.vue")).default;
    const { wrapper, open } = await openDialog(EntryDialog, "/c/1/sales/entries");
    wrapper.findComponent(MoneyInput).vm.$emit("update:modelValue", "100000.00");
    await flushPromises();
    button(en["sales.entries.submit"]).click();
    await flushPromises();
    await flushPromises();
    expect(document.body.textContent).toContain("Uzcard is switched off.");
    expect(open.value).toBe(true);
    wrapper.unmount();
  });
});

describe("TargetDialog", () => {
  it("offers a branch-limited manager their branch, never the whole company the server refuses", async () => {
    const calls = stub({ "GET sales/options/": () => json(options()), "POST sales/targets/": () => json({ id: 3 }, 201) });
    const TargetDialog = (await import("../components/TargetDialog.vue")).default;
    const app = await testApp("/c/1/sales/targets");
    await ensureModuleMessages(salesModule);
    useSessionStore().me = me([company({ is_owner: false, permissions: ["sales.view", "sales.manage"], branch_scope: [1] })]);
    const open = ref(false);
    const Host = defineComponent({ setup: () => () => h(TargetDialog, { open: open.value, month: "2026-10-01", "onUpdate:open": (value: boolean) => (open.value = value) } as never) });
    const { wrapper } = mountWithProviders(Host, { plugins: app.plugins });
    await flushPromises();
    open.value = true;
    await flushPromises();
    await flushPromises();
    expect(document.body.textContent).not.toContain(en["sales.targets.scope.company"]);
    wrapper.findComponent(MoneyInput).vm.$emit("update:modelValue", "90000000.00");
    await flushPromises();
    button("Save").click();
    await flushPromises();
    expect(calls.find((c) => c.method === "POST")?.body).toMatchObject({ branch_id: 1, member_id: null });
    wrapper.unmount();
  });

  it("refuses a zero target and shows a field-only refusal", async () => {
    const calls = stub({ "GET sales/options/": () => json(options()), "POST sales/targets/": () => json({ month: ["Targets are set for this month or later."] }, 400) });
    const TargetDialog = (await import("../components/TargetDialog.vue")).default;
    const app = await testApp("/c/1/sales/targets");
    await ensureModuleMessages(salesModule);
    const open = ref(false);
    const Host = defineComponent({ setup: () => () => h(TargetDialog, { open: open.value, month: "2026-10-01", "onUpdate:open": (value: boolean) => (open.value = value) } as never) });
    const { wrapper } = mountWithProviders(Host, { plugins: app.plugins });
    await flushPromises();
    open.value = true;
    await flushPromises();
    wrapper.findComponent(MoneyInput).vm.$emit("update:modelValue", "0.00");
    await flushPromises();
    button("Save").click();
    await flushPromises();
    expect(calls.some((c) => c.method === "POST")).toBe(false);
    expect(document.body.textContent).toContain(en["sales.targets.errAmount"]);
    wrapper.findComponent(MoneyInput).vm.$emit("update:modelValue", "1000000.00");
    await flushPromises();
    button("Save").click();
    await flushPromises();
    await flushPromises();
    expect(document.body.textContent).toContain("Targets are set for this month or later.");
    wrapper.unmount();
  });
});

describe("palette links on a page already open", () => {
  it("opens Set a target when ?new=target arrives on the targets page", async () => {
    stub({
      "GET sales/options/": () => json(options()),
      "GET sales/targets/": () => json({ month: "2026-10", today: "2026-10-21", targets: [], series: [] }),
    });
    vi.stubGlobal(
      "ResizeObserver",
      class {
        observe(): void {}
        unobserve(): void {}
        disconnect(): void {}
      },
    );
    const TargetsPage = (await import("../pages/TargetsPage.vue")).default;
    const app = await testApp("/c/1/sales/targets");
    await ensureModuleMessages(salesModule);
    const { wrapper } = mountWithProviders(TargetsPage, { plugins: app.plugins });
    await flushPromises();
    await app.router.push("/c/1/sales/targets?new=target");
    await flushPromises();
    await flushPromises();
    expect(document.querySelector('[role="dialog"]')?.textContent).toContain(en["sales.targets.newTitle"]);
    expect(app.router.currentRoute.value.query.new).toBeUndefined();
    wrapper.unmount();
  });

  it("applies the To check view's filters when the palette opens it on the shifts page", async () => {
    const calls = stub({
      "GET sales/options/": () => json(options()),
      "GET sales/settings/": () => json({ mode: "shift_totals", cash_tolerance: "5000.00" }),
      "GET sales/shifts/": () => json({ count: 0, next: null, previous: null, results: [] }),
    });
    const ShiftsPage = (await import("../pages/ShiftsPage.vue")).default;
    const app = await testApp("/c/1/sales/shifts");
    await ensureModuleMessages(salesModule);
    const { wrapper } = mountWithProviders(ShiftsPage, { plugins: app.plugins });
    await flushPromises();
    await app.router.push("/c/1/sales/shifts?view=verify");
    await flushPromises();
    await flushPromises();
    expect(app.router.currentRoute.value.query.status).toEqual(["closed"]);
    expect(calls.filter((c) => c.url.includes("sales/shifts/")).at(-1)?.url).toContain("status=closed");
    wrapper.unmount();
  });
});
