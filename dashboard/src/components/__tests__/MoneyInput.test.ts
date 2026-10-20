import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { mount } from "@vue/test-utils";
import { afterEach, describe, expect, it } from "vitest";

import MoneyInput from "@/components/MoneyInput.vue";
import { fractionDigits, maskMoney, moneyToText } from "@/lib/moneyMask";
import { testApp } from "@/test/plugins";

const NBSP = " ";

describe("maskMoney", () => {
  it("groups digits as they are typed, per language", () => {
    expect(maskMoney("1250000", 7, "uz", { decimals: 0 })).toEqual({ text: `1${NBSP}250${NBSP}000`, value: "1250000.00", caret: 9 });
    expect(maskMoney("1250000", 7, "en", { decimals: 0 }).text).toBe("1,250,000");
    expect(maskMoney("", 0, "ru", { decimals: 0 })).toEqual({ text: "", value: null, caret: 0 });
  });

  it("keeps the caret beside the same digit after regrouping", () => {
    // "1 250|" + "0" typed → "12 500|"
    const typed = maskMoney(`1${NBSP}2500`, 6, "uz", { decimals: 0 });
    expect(typed.text).toBe(`12${NBSP}500`);
    expect(typed.caret).toBe(6);
    // Typing in the middle: "12| 500" + "3" → "123 500" caret after the 3
    const middle = maskMoney(`123${NBSP}500`, 3, "uz", { decimals: 0 });
    expect(middle.text).toBe(`123${NBSP}500`);
    expect(middle.caret).toBe(3);
    const grows = maskMoney(`1239${NBSP}500`, 4, "uz", { decimals: 0 });
    expect(grows.text).toBe(`1${NBSP}239${NBSP}500`);
    expect(grows.text.slice(0, grows.caret).replace(/\D/g, "")).toBe("1239");
  });

  it("takes decimals only when the field allows them, never more than allowed", () => {
    expect(maskMoney("12.5", 4, "en", { decimals: 2 })).toMatchObject({ text: "12.5", value: "12.50" });
    expect(maskMoney("12,567", 6, "ru", { decimals: 2 })).toMatchObject({ text: "12,56", value: "12.56" });
    expect(maskMoney("12.5", 4, "en", { decimals: 0 })).toMatchObject({ text: "125", value: "125.00" });
    // A lone decimal mark becomes "0," and keeps the caret after it.
    expect(maskMoney(",", 1, "uz", { decimals: 2 })).toEqual({ text: "0,", value: null, caret: 2 });
  });

  it("drops leading zeros and junk, accepts a minus only when allowed", () => {
    expect(maskMoney("007", 3, "en", { decimals: 0 })).toMatchObject({ text: "7", value: "7.00", caret: 1 });
    expect(maskMoney("1a2b3", 5, "en", { decimals: 0 }).value).toBe("123.00");
    expect(maskMoney("-15000", 6, "uz", { decimals: 0, negative: true })).toMatchObject({ text: `−15${NBSP}000`, value: "-15000.00" });
    expect(maskMoney("-15000", 6, "uz", { decimals: 0 }).value).toBe("15000.00");
  });

  it("pastes formatted amounts from anywhere", () => {
    expect(maskMoney("1,250,000.50", 12, "en", { decimals: 2 }).value).toBe("1250000.50");
    expect(maskMoney(`1${NBSP}250${NBSP}000,50`, 12, "ru", { decimals: 2 }).value).toBe("1250000.50");
  });

  it("keeps very large amounts exact (no float rounding)", () => {
    expect(maskMoney("123456789012345", 15, "en", { decimals: 0 }).value).toBe("123456789012345.00");
    expect(moneyToText("9007199254740993.07", "en", 2)).toBe("9,007,199,254,740,993.07");
  });

  it("renders API values for the field and counts their tiyins", () => {
    expect(moneyToText("1250000.00", "uz", 0)).toBe(`1${NBSP}250${NBSP}000`);
    expect(moneyToText("1250.50", "en", 2)).toBe("1,250.50");
    expect(moneyToText(null, "en", 2)).toBe("");
    expect(fractionDigits("12.00")).toBe(0);
    expect(fractionDigits("12.50")).toBe(1);
    expect(fractionDigits("12.05")).toBe(2);
  });
});

describe("MoneyInput", () => {
  afterEach(() => {
    document.body.innerHTML = "";
  });

  it("emits the API string while showing grouped digits", async () => {
    const app = await testApp("/c/1", "uz");
    const wrapper = mount(MoneyInput, { props: { modelValue: null }, global: { plugins: app.plugins }, attachTo: document.body });
    const input = wrapper.get("input");
    input.element.value = "4500000";
    input.element.setSelectionRange(7, 7);
    await input.trigger("input");
    expect(wrapper.emitted("update:modelValue")?.at(-1)).toEqual(["4500000.00"]);
    expect(input.element.value).toBe(`4${NBSP}500${NBSP}000`);
    expect(wrapper.text()).toContain("so‘m");
  });

  it("shows an existing value and switches currency", async () => {
    const app = await testApp("/c/1", "en");
    const wrapper = mount(MoneyInput, {
      props: { modelValue: "1240.50", currencies: ["UZS", "USD"], currency: "USD" },
      global: { plugins: app.plugins },
    });
    expect(wrapper.get("input").element.value).toBe("1,240.50");
    const radios = wrapper.findAll("[role=radio]");
    expect(radios.map((r) => r.attributes("aria-checked"))).toEqual(["false", "true"]);
    await radios[0]!.trigger("click");
    expect(wrapper.emitted("update:currency")?.at(-1)).toEqual(["UZS"]);
  });

  it("never parses money with floats", () => {
    const here = dirname(fileURLToPath(import.meta.url));
    for (const file of ["../MoneyInput.vue", "../../lib/moneyMask.ts", "../MoneyText.vue", "../MoneyCell.vue"]) {
      // Code only: the doc comments explain the rule and name what is banned.
      const source = readFileSync(resolve(here, file), "utf8").replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
      expect(source, file).not.toMatch(/parseFloat|Number\(/);
    }
  });
});
