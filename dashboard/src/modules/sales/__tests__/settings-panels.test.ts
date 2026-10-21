// The sales panels in Settings (Payment methods, Tills): one line under each name, in full on hover.
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { mergeModuleMessages, setLanguage } from "@/i18n";
import { json } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

import PaymentMethodsPanel from "../components/PaymentMethodsPanel.vue";
import en from "../i18n/en.json";
import ru from "../i18n/ru.json";
import uz from "../i18n/uz.json";
import type { PaymentMethod } from "../types";

const method = (id: number, extra: Partial<PaymentMethod>): PaymentMethod => ({
  id,
  name: `Method ${id}`,
  kind: "card",
  account: { id: 3, name: "Terminal (karta va QR)" },
  fee_percent: "0.00",
  is_active: true,
  order: id,
  is_default: true,
  ...extra,
});

beforeEach(() => {
  mergeModuleMessages("sales", { en, ru, uz });
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string) => {
      if (input.includes("payment-methods/")) return json([method(1, { name: "Naqd", kind: "cash", account: null }), method(2, { name: "Uzcard", fee_percent: "0.60" })]);
      return json({});
    }),
  );
});

afterEach(async () => {
  vi.unstubAllGlobals();
  await setLanguage("en");
  document.body.innerHTML = "";
});

describe("PaymentMethodsPanel", () => {
  it("says the kind, the account and the fee in the person's number format, with the line in full on hover", async () => {
    const app = await testApp("/c/1/settings/payment-methods", "ru");
    const { wrapper } = mountWithProviders(PaymentMethodsPanel, { plugins: app.plugins });
    await flushPromises();
    await flushPromises();
    const lines = wrapper.findAll("p[title]").map((p) => [p.text(), p.attributes("title")]);
    expect(lines).toEqual([
      [ru["sales.methods.kind.cash"], ru["sales.methods.kind.cash"]],
      [`${ru["sales.methods.kind.card"]} · Terminal (karta va QR) · комиссия 0,6 %`, `${ru["sales.methods.kind.card"]} · Terminal (karta va QR) · комиссия 0,6 %`],
    ]);
  });
});
