// Round 2: sales forms that save what they show, and say why they can't.
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";
import { defineComponent, h, ref } from "vue";

import MoneyInput from "@/components/MoneyInput.vue";
import { ensureModuleMessages } from "@/i18n";
import { json } from "@/test/fixtures";
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
