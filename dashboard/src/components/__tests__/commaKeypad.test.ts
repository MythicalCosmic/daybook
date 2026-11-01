// English fields on a phone whose number keypad has only a comma (most phones set to Uzbek or
// Russian regions): the comma typed last is the decimal point; commas inside a number group it.
import { mount } from "@vue/test-utils";
import { afterEach, describe, expect, it } from "vitest";

import NumberInput from "@/components/NumberInput.vue";
import { maskMoney } from "@/lib/moneyMask";
import { testApp } from "@/test/plugins";

afterEach(() => {
  document.body.innerHTML = "";
});

describe("maskMoney in English", () => {
  it("reads a comma typed at the end as the decimal point, so 12,50 is twelve dollars fifty", () => {
    expect(maskMoney("12,", 3, "en", { decimals: 2 })).toEqual({ text: "12.", value: "12.00", caret: 3 });
    expect(maskMoney("12.5", 4, "en", { decimals: 2 })).toMatchObject({ text: "12.5", value: "12.50" });
    expect(maskMoney("1,250,", 6, "en", { decimals: 2 })).toMatchObject({ text: "1,250.", value: "1250.00" });
  });

  it("keeps commas inside a number as thousands, and a so‘m field without decimals", () => {
    // "1,250" with its last digit deleted is 125, not 1.25.
    expect(maskMoney("1,25", 4, "en", { decimals: 2 })).toMatchObject({ text: "125", value: "125.00" });
    expect(maskMoney("1,200", 5, "en", { decimals: 2 })).toMatchObject({ text: "1,200", value: "1200.00" });
    expect(maskMoney("12,", 3, "en", { decimals: 0 })).toMatchObject({ text: "12", value: "12.00" });
  });
});

describe("NumberInput in English", () => {
  async function typed(text: string, decimals = 1): Promise<number | null | undefined> {
    const app = await testApp("/c/1", "en");
    let value: number | null | undefined;
    const wrapper = mount(NumberInput, { props: { modelValue: null, decimals, "onUpdate:modelValue": (next: number | null) => (value = next) }, global: { plugins: app.plugins } });
    await wrapper.find("input").setValue(text);
    wrapper.unmount();
    return value;
  }

  it("reads 1,200 as twelve hundred and 12,5 as twelve and a half", async () => {
    expect(await typed("1,200")).toBe(1200);
    expect(await typed("1,200,000", 0)).toBe(1200000);
    expect(await typed("12,5")).toBe(12.5);
    expect(await typed("1,200.5")).toBe(1200.5);
  });
});
