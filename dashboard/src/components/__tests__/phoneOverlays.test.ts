/**
 * Drawers and dialogs on a phone (the console inside Telegram): they become bottom sheets and must
 * keep everything their header holds, and the bottom safe area goes under the last thing only.
 */
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia, type Pinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { h, ref } from "vue";
import { createMemoryHistory, createRouter, type Router } from "vue-router";

import BottomSheet from "@/components/BottomSheet.vue";
import UiDialog from "@/components/UiDialog.vue";
import UiDrawer from "@/components/UiDrawer.vue";
import { i18n, setLanguage } from "@/i18n";
import { closeTopOverlay, overlayOpen } from "@/lib/backStack";

vi.mock("@/lib/useBreakpoints", () => ({
  useBreakpoints: () => ({ isPhone: ref(true), isTablet: ref(false), isDesktop: ref(false) }),
}));

let pinia: Pinia;
let router: Router;

beforeEach(async () => {
  pinia = createPinia();
  setActivePinia(pinia);
  router = createRouter({ history: createMemoryHistory(), routes: [{ path: "/:any(.*)*", component: { render: () => null } }] });
  await router.push("/c/1/tasks");
  setLanguage("en");
});

afterEach(() => {
  document.body.innerHTML = "";
});

const plugins = () => [pinia, router, i18n];
const sheet = () => document.body.querySelector<HTMLElement>("[role=dialog]")!;

describe("UiDrawer on a phone", () => {
  it("keeps its header actions (a task's More menu) and its own title", async () => {
    await router.push("/c/1/tasks?task=7");
    const wrapper = mount(UiDrawer, {
      props: { queryKey: "task", title: "Fridge check" },
      slots: {
        default: () => h("p", "body"),
        title: () => h("h2", { class: "custom-title" }, "Alisher Valiyev · Monday"),
        "header-actions": (props: { value: string | null }) => h("button", { class: "more-menu" }, `More for ${props.value}`),
      },
      global: { plugins: plugins() },
      attachTo: document.body,
    });
    await flushPromises();
    expect(sheet().querySelector(".more-menu")?.textContent).toBe("More for 7");
    expect(sheet().querySelector(".custom-title")?.textContent).toBe("Alisher Valiyev · Monday");
    wrapper.unmount();
  });
});

describe("UiDialog on a phone", () => {
  it("keeps its header actions", async () => {
    const wrapper = mount(UiDialog, {
      props: { open: true, title: "New task" },
      slots: { default: () => h("p", "form"), "header-actions": () => h("button", { class: "dictate" }, "Dictate") },
      global: { plugins: plugins() },
      attachTo: document.body,
    });
    await flushPromises();
    expect(sheet().querySelector("header .dictate")?.textContent).toBe("Dictate");
    wrapper.unmount();
  });
});

describe("BottomSheet", () => {
  it("puts the bottom safe area under the footer, not under the body as well", async () => {
    const wrapper = mount(BottomSheet, {
      props: { open: true, title: "Edit" },
      slots: { default: () => h("p", "form"), footer: () => h("button", "Save") },
      global: { plugins: plugins() },
      attachTo: document.body,
    });
    await flushPromises();
    expect(sheet().querySelector("[data-sheet-body]")!.className).not.toContain("safe-bottom");
    expect(sheet().querySelector("footer")!.className).toContain("var(--safe-bottom)");
    wrapper.unmount();
  });

  it("gives a footer note its own row above the buttons (New task's \"Creates 3 tasks\")", async () => {
    const wrapper = mount(BottomSheet, {
      props: { open: true, title: "New task" },
      slots: { default: () => h("p", "form"), footer: () => [h("div", { "data-sheet-note": "" }, "Creates 3 tasks"), h("button", "Cancel"), h("button", "Create")] },
      global: { plugins: plugins() },
      attachTo: document.body,
    });
    await flushPromises();
    const footer = sheet().querySelector("footer")!;
    expect(footer.className).toContain("flex-wrap");
    expect(footer.className).toContain("[&>[data-sheet-note]]:basis-full");
    wrapper.unmount();
  });

  it("puts it under the body when there is no footer", async () => {
    const wrapper = mount(BottomSheet, {
      props: { open: true, title: "Details" },
      slots: { default: () => h("p", "text") },
      global: { plugins: plugins() },
      attachTo: document.body,
    });
    await flushPromises();
    expect(sheet().querySelector("[data-sheet-body]")!.className).toContain("var(--safe-bottom)");
    wrapper.unmount();
  });
});

describe("Back on a phone", () => {
  it("closes an open sheet first (Telegram's BackButton), but never one that must stay", async () => {
    const wrapper = mount(BottomSheet, {
      props: { open: true, title: "Filters", "onUpdate:open": (value: boolean) => wrapper.setProps({ open: value }) },
      slots: { default: () => h("p", "chips") },
      global: { plugins: plugins() },
      attachTo: document.body,
    });
    await flushPromises();
    expect(overlayOpen.value).toBe(true);
    expect(closeTopOverlay()).toBe(true);
    await flushPromises();
    expect(wrapper.props("open")).toBe(false);
    expect(overlayOpen.value).toBe(false);
    wrapper.unmount();

    const busy = mount(BottomSheet, {
      props: { open: true, title: "Saving", dismissable: false },
      slots: { default: () => h("p", "wait") },
      global: { plugins: plugins() },
      attachTo: document.body,
    });
    await flushPromises();
    expect(overlayOpen.value).toBe(false);
    busy.unmount();
  });
});
