// The one checklist editor tasks and routines share (it was two copies differing by their i18n keys).
import { flushPromises } from "@vue/test-utils";
import { afterEach, describe, expect, it } from "vitest";
import { defineComponent, h, ref } from "vue";

import ChecklistEditor from "@/components/ChecklistEditor.vue";
import { mergeModuleMessages } from "@/i18n";
import { mountWithProviders, testApp } from "@/test/plugins";

import routinesEn from "../../modules/routines/i18n/en.json";

afterEach(() => {
  document.body.innerHTML = "";
});

describe("ChecklistEditor", () => {
  it("reads its words from the module it is given and adds a step on Enter", async () => {
    mergeModuleMessages("routines", { en: routinesEn, ru: routinesEn, uz: routinesEn });
    const app = await testApp("/c/1/routines/all");
    const steps = ref<string[]>(["Check the fridge"]);
    const Host = defineComponent({
      setup: () => () => h(ChecklistEditor, { texts: "routines.checklist", modelValue: steps.value, "onUpdate:modelValue": (next: string[]) => (steps.value = next) }),
    });
    const { wrapper } = mountWithProviders(Host, { plugins: app.plugins });
    expect(wrapper.text()).toContain("Add a step");
    expect(wrapper.find(`[aria-label="Remove the step"]`).exists()).toBe(true);
    await wrapper.find("input").trigger("keydown", { key: "Enter" });
    await flushPromises();
    expect(steps.value).toEqual(["Check the fridge", ""]);
    wrapper.unmount();
  });
});
