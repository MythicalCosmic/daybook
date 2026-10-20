import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia, type Pinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { defineComponent, h } from "vue";
import { createMemoryHistory, createRouter, type Router } from "vue-router";

import { ApiError } from "@/api/http";
import ErrorState from "@/components/ErrorState.vue";
import ExtensionSlot from "@/components/ExtensionSlot.vue";
import KbdKey from "@/components/KbdKey.vue";
import UiBadge from "@/components/UiBadge.vue";
import UiButton from "@/components/UiButton.vue";
import UiDrawer from "@/components/UiDrawer.vue";
import { dismissToast, pauseToast, resumeToast, showToast, toasts } from "@/components/useToast";
import { defineModule, registerDevModules } from "@/core/modules";
import { i18n, setLanguage } from "@/i18n";
import { useCompanyStore } from "@/stores/company";
import { useSessionStore } from "@/stores/session";
import { me } from "@/test/fixtures";

let pinia: Pinia;
let router: Router;

beforeEach(async () => {
  pinia = createPinia();
  setActivePinia(pinia);
  useSessionStore().me = me();
  useCompanyStore().setCurrent(1);
  router = createRouter({ history: createMemoryHistory(), routes: [{ path: "/:any(.*)*", component: { render: () => null } }] });
  await router.push("/c/1/tasks");
  setLanguage("en");
});

afterEach(() => {
  toasts.splice(0, toasts.length);
  vi.useRealTimers();
  document.body.innerHTML = "";
});

const plugins = () => [pinia, router, i18n];

describe("useToast", () => {
  it("stacks at most four, replaces by id and dismisses", () => {
    for (let i = 0; i < 6; i++) showToast("info", `n${i}`);
    expect(toasts.map((t) => t.title)).toEqual(["n2", "n3", "n4", "n5"]);
    showToast("success", "replaced", { id: toasts[1]!.id });
    expect(toasts[1]!.title).toBe("replaced");
    dismissToast(toasts[0]!.id);
    expect(toasts).toHaveLength(3);
  });

  it("closes itself after its duration, paused while hovered", () => {
    vi.useFakeTimers();
    const id = showToast("error", "Failed");
    expect(toasts[0]!.duration).toBe(6000);
    pauseToast(id);
    vi.advanceTimersByTime(10_000);
    expect(toasts).toHaveLength(1);
    resumeToast(id);
    vi.advanceTimersByTime(6000);
    expect(toasts).toHaveLength(0);
    const undo = showToast("info", "Done", { action: { label: "Undo", onClick: () => undefined } });
    expect(toasts.find((t) => t.id === undo)!.duration).toBe(5000);
  });
});

describe("UiButton", () => {
  it("renders a link for `to` and keeps width while loading", async () => {
    const link = mount(UiButton, { props: { to: "/c/1/finance" }, slots: { default: "Finance" }, global: { plugins: plugins() } });
    expect(link.element.tagName).toBe("A");
    expect(link.attributes("href")).toBe("/c/1/finance");
    const busy = mount(UiButton, { props: { loading: true, variant: "primary" }, slots: { default: "Save" }, global: { plugins: plugins() } });
    expect(busy.attributes("disabled")).toBeDefined();
    expect(busy.attributes("aria-busy")).toBe("true");
    expect(busy.find(".ui-spinner").exists()).toBe(true);
    expect(busy.text()).toContain("Save");
  });
});

describe("KbdKey and UiBadge", () => {
  it("labels keys and caps counts", () => {
    const kbd = mount(KbdKey, { props: { keys: "mod+k" } });
    expect(kbd.findAll("kbd").map((k) => k.text())).toEqual(["Ctrl", "K"]);
    const seq = mount(KbdKey, { props: { keys: ["g", "t"] } });
    expect(seq.findAll("kbd").map((k) => k.text())).toEqual(["G", "T"]);
    expect(mount(UiBadge, { props: { count: 140 } }).text()).toBe("99+");
    expect(mount(UiBadge, { slots: { default: "New" } }).text()).toBe("New");
  });
});

describe("ErrorState", () => {
  it("explains the failure in plain words and retries", async () => {
    const retry = vi.fn();
    const wrapper = mount(ErrorState, { props: { error: new ApiError(0, null), retry }, global: { plugins: plugins() } });
    expect(wrapper.text()).toContain("No connection");
    await wrapper.find("button").trigger("click");
    expect(retry).toHaveBeenCalled();
    const detail = mount(ErrorState, { props: { error: new ApiError(400, { detail: "Locked period." }), compact: true }, global: { plugins: plugins() } });
    expect(detail.text()).toContain("Locked period.");
  });
});

describe("ExtensionSlot", () => {
  it("renders other modules' components and drops one that throws", async () => {
    const error = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const Good = defineComponent({ props: { context: { type: Object, required: true } }, setup: (props) => () => h("span", { class: "good" }, String(props.context.count)) });
    const Bad = defineComponent({
      setup() {
        throw new Error("broken extension");
      },
    });
    registerDevModules([
      defineModule({
        id: "slotprovider",
        group: "insights",
        order: 99,
        icon: {},
        title: "slotprovider.title",
        routes: [],
        extensions: { "tasks.toolbar": [Good, Bad] },
        messages: () => Promise.resolve({ uz: {}, ru: {}, en: {} }),
      }),
    ]);
    const wrapper = mount(ExtensionSlot, { props: { name: "tasks.toolbar", context: { count: 3 } }, global: { plugins: plugins() } });
    await flushPromises();
    expect(wrapper.find(".good").text()).toBe("3");
    expect(wrapper.find("[data-extension-slot]").attributes("data-extension-slot")).toBe("tasks.toolbar");
    expect(error).toHaveBeenCalled();
    const empty = mount(ExtensionSlot, { props: { name: "payroll.run.toolbar" }, global: { plugins: plugins() } });
    expect(empty.html()).toBe("<!--v-if-->");
    warn.mockRestore();
  });
});

describe("UiDrawer", () => {
  it("opens from the URL and closing removes the query key", async () => {
    await router.push("/c/1/tasks?task=345&view=board");
    const wrapper = mount(UiDrawer, {
      props: { queryKey: "task", title: "Task" },
      slots: { default: (props: { value: string | null }) => h("p", { class: "drawer-body" }, `task ${props.value}`) },
      global: { plugins: plugins() },
      attachTo: document.body,
    });
    await flushPromises();
    expect(document.body.querySelector(".drawer-body")?.textContent).toBe("task 345");
    const close = document.body.querySelector<HTMLButtonElement>('button[aria-label="Close"]');
    close?.click();
    await flushPromises();
    expect(router.currentRoute.value.fullPath).toBe("/c/1/tasks?view=board");
    wrapper.unmount();
  });
});
