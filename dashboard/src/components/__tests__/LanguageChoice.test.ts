// The sign-in pages' language choice: O‘zbekcha first and pressed by default (Uzbek when nothing
// else is known); another pick switches the page and is kept in this browser.
import { flushPromises } from "@vue/test-utils";
import { afterEach, describe, expect, it } from "vitest";

import { setLanguage } from "@/i18n";
import { mountWithProviders, testApp } from "@/test/plugins";

import LanguageChoice from "../LanguageChoice.vue";

afterEach(() => {
  document.body.innerHTML = "";
  localStorage.removeItem("daybook.console.language");
});

describe("LanguageChoice", () => {
  it("lists O‘zbekcha first, presses the language shown and switches on a tap", async () => {
    const app = await testApp("/login", "uz");
    const { wrapper } = mountWithProviders(LanguageChoice, { plugins: app.plugins });
    const buttons = wrapper.findAll("button");
    expect(buttons.map((button) => button.text())).toEqual(["O‘zbekcha", "Русский", "English"]);
    expect(buttons[0]!.attributes("aria-pressed")).toBe("true");
    await buttons[1]!.trigger("click");
    await flushPromises();
    expect(wrapper.findAll("button")[1]!.attributes("aria-pressed")).toBe("true");
    expect(JSON.parse(localStorage.getItem("daybook.console.language") ?? "null")).toBe("ru");
    wrapper.unmount();
    await setLanguage("en");
  });
});
