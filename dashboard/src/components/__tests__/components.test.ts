import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia, type Pinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { defineComponent, h } from "vue";
import { createMemoryHistory, createRouter, type Router } from "vue-router";

import { ApiError } from "@/api/http";
import AvatarStack from "@/components/AvatarStack.vue";
import CalendarWeek from "@/components/CalendarWeek.vue";
import ErrorState from "@/components/ErrorState.vue";
import ExtensionSlot from "@/components/ExtensionSlot.vue";
import KbdKey from "@/components/KbdKey.vue";
import KpiCard from "@/components/KpiCard.vue";
import KpiStrip from "@/components/KpiStrip.vue";
import PageHeader from "@/components/PageHeader.vue";
import PersonCell from "@/components/PersonCell.vue";
import SavedViewsTabs from "@/components/SavedViewsTabs.vue";
import TextInput from "@/components/TextInput.vue";
import UiBadge from "@/components/UiBadge.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import UiDrawer from "@/components/UiDrawer.vue";
import { fadeMask, moreToTheRight } from "@/components/useScrollFade";
import WidgetCard from "@/components/WidgetCard.vue";
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

  it("hides its shortcut hint on phones and touch screens by itself", () => {
    const button = mount(UiButton, { props: { kbd: "N", variant: "primary" }, slots: { default: "New task" }, global: { plugins: plugins() } });
    const hint = button.findComponent(KbdKey);
    expect(hint.exists()).toBe(true);
    // Below 768 px (the phone layout) and with a coarse pointer (any touch screen).
    expect(hint.classes()).toEqual(expect.arrayContaining(["max-md:hidden", "pointer-coarse:hidden"]));
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
        messages: () => Promise.resolve({}),
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

  it("puts the host's attributes on its wrapper, or on each extension without one", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const Pill = defineComponent({ props: { context: { type: Object, required: true } }, setup: (props) => () => (props.context.hidden ? null : h("a", { class: "pill" }, "Pill")) });
    registerDevModules([
      defineModule({
        id: "attrsprovider",
        group: "insights",
        order: 98,
        icon: {},
        title: "attrsprovider.title",
        routes: [],
        extensions: { "shell.nav.top": [Pill], "comms.composer.tools": [Pill, Pill] },
        messages: () => Promise.resolve({}),
      }),
    ]);
    const wrapped = mount(ExtensionSlot, { props: { name: "shell.nav.top", context: {} }, attrs: { class: "px-3 pt-2 empty:hidden", "data-x": "1" }, global: { plugins: plugins() } });
    const host = wrapped.find("[data-extension-slot='shell.nav.top']");
    expect(host.classes()).toEqual(["px-3", "pt-2", "empty:hidden"]);
    expect(host.attributes("data-x")).toBe("1");
    expect(host.find(".pill").classes()).toEqual(["pill"]);
    // An extension that renders nothing leaves only a comment, so `empty:hidden` hides the spacing.
    const hidden = mount(ExtensionSlot, { props: { name: "shell.nav.top", context: { hidden: true } }, attrs: { class: "px-3" }, global: { plugins: plugins() } });
    expect(hidden.find("[data-extension-slot]").element.children).toHaveLength(0);
    const bare = mount(ExtensionSlot, { props: { name: "comms.composer.tools", as: "none" }, attrs: { class: "shrink-0" }, global: { plugins: plugins() } });
    expect(bare.findAll("a.pill.shrink-0")).toHaveLength(2);
    expect(warn.mock.calls.flat().join(" ")).not.toMatch(/Extraneous non-props attributes/);
    warn.mockRestore();
  });
});

describe("KpiStrip", () => {
  const items = (n: number) => Array.from({ length: n }, (_, i) => ({ label: `K${i}`, value: i, hint: "hint" }));
  const strip = (props: Record<string, unknown>) => mount(KpiStrip, { props, global: { plugins: plugins() } }).find(".kpi-strip");

  it("stacks on phones by default and keeps its desktop columns", () => {
    const grid = strip({ items: items(4), columns: 4 });
    expect(grid.classes()).toEqual(expect.arrayContaining(["grid-cols-1", "sm:grid-cols-2", "xl:grid-cols-4"]));
    expect(grid.attributes("data-phone")).toBe("stack");
  });

  it("opts into two numbers per row on phones (three for a strip of three)", () => {
    const five = strip({ items: items(5), columns: 5, phone: "compact" });
    expect(five.classes()).toEqual(expect.arrayContaining(["grid-cols-2", "sm:grid-cols-2", "lg:grid-cols-3", "xl:grid-cols-5"]));
    expect(five.classes()).not.toContain("grid-cols-1");
    expect(five.attributes()).toMatchObject({ "data-phone": "compact", "data-phone-columns": "2" });
    // Compact hides each number's footer on phones; KpiCard marks it for that.
    expect(five.findAll("[data-kpi-foot]")).toHaveLength(5);
    const three = strip({ items: items(3), columns: 3, phone: "grid" });
    expect(three.classes()).toEqual(expect.arrayContaining(["grid-cols-3", "sm:grid-cols-3"]));
    expect(three.attributes("data-phone-columns")).toBe("3");
  });
});

describe("AvatarStack", () => {
  it("overlaps by 15 % of the size, so the next ring doesn't cut the initials", () => {
    const people = [{ name: "Dilnoza Karimova" }, { name: "Bekzod Mirzayev" }, { name: "Nigora Saidova" }, { name: "Jasur Aliyev" }];
    const wrapper = mount(AvatarStack, { props: { people, max: 3, size: 28, tooltips: false }, global: { plugins: plugins() } });
    const margins = wrapper.findAll("[style*='margin-left']").map((el) => (el.element as HTMLElement).style.marginLeft);
    // Two overlapping avatars after the first, then the "+1" chip: round(28 × 0.15) = 4.
    expect(margins).toEqual(["-4px", "-4px", "-4px"]);
    expect(wrapper.text()).toContain("+1");
  });
});

describe("UiDialog", () => {
  it("fits below its top offset: the body scrolls and the footer stays visible", async () => {
    const wrapper = mount(UiDialog, {
      props: { open: true, title: "New account", mobile: "center" },
      slots: { default: () => h("div", { style: "height: 2000px" }, "Tall form"), footer: () => h("button", "Save") },
      global: { plugins: plugins() },
      attachTo: document.body,
    });
    await flushPromises();
    const content = document.body.querySelector<HTMLElement>("[role=dialog]")!;
    // The container is `p-4 pt-[min(14vh,120px)]`: the dialog may use what is left of the screen.
    expect(content.className).toContain("max-h-[calc(100dvh-min(14vh,120px)-16px)]");
    expect(content.className).toContain("flex-col");
    expect(content.parentElement!.className).toContain("pt-[min(14vh,120px)]");
    const body = content.querySelector<HTMLElement>("[data-dialog-body]")!;
    expect(body.className).toMatch(/\bmin-h-0\b.*\boverflow-y-auto\b/);
    expect(content.querySelector("footer")!.className).toContain("shrink-0");
    wrapper.unmount();
  });
});

describe("PersonCell", () => {
  it("lets a tap on a plain name reach the row (phone cards), while a linked name opens the person", async () => {
    const rowClick = vi.fn();
    const Row = (link: boolean) =>
      defineComponent({ setup: () => () => h("li", { onClick: rowClick }, [h(PersonCell, { person: { id: 7, name: "Alisher Valiyev" }, link })]) });
    const plain = mount(Row(false), { global: { plugins: plugins() } });
    await plain.find("span.font-medium").trigger("click");
    expect(rowClick).toHaveBeenCalledTimes(1);
    const linked = mount(Row(true), { global: { plugins: plugins() } });
    const anchor = linked.find("a");
    expect(anchor.attributes("href")).toBe("/c/1/people/7");
    await anchor.trigger("click");
    expect(rowClick).toHaveBeenCalledTimes(1);
  });
});

describe("small layout fixes", () => {
  it("PageHeader keeps its actions inside the header and gives them a full row on phones", () => {
    const header = mount(PageHeader, { props: { title: "Sales" }, slots: { actions: () => h("button", "Export") }, global: { plugins: plugins() } });
    expect(header.find("[data-page-actions]").classes()).toEqual(expect.arrayContaining(["max-w-full", "min-w-0", "flex-wrap", "max-sm:w-full"]));
  });

  it("PageHeader moves the tab underline when a tab's count arrives and widens it", async () => {
    // jsdom has no layout: a tab is 10 px per character, placed after the tabs before it.
    const width = (el: HTMLElement) => (el.textContent ?? "").trim().length * 10;
    const widthSpy = vi.spyOn(HTMLElement.prototype, "offsetWidth", "get").mockImplementation(function (this: HTMLElement) {
      return width(this);
    });
    const leftSpy = vi.spyOn(HTMLElement.prototype, "offsetLeft", "get").mockImplementation(function (this: HTMLElement) {
      let left = 0;
      for (let el = this.previousElementSibling as HTMLElement | null; el; el = el.previousElementSibling as HTMLElement | null) if (el.dataset.tab) left += width(el);
      return left;
    });
    const tabs = (count?: number) => [
      { id: "verify", label: "To verify", count },
      { id: "all", label: "All" },
    ];
    const header = mount(PageHeader, { props: { title: "Shifts", tabs: tabs(), tab: "all" }, global: { plugins: plugins() } });
    await flushPromises();
    const underline = () => header.find("nav span[aria-hidden='true']").attributes("style");
    expect(underline()).toContain("left: 90px");
    await header.setProps({ tabs: tabs(4) });
    await flushPromises();
    // "To verify" grew a badge: "All", and its underline, start further right.
    const first = header.find("[data-tab='verify']").element as HTMLElement;
    expect(width(first)).toBeGreaterThan(90);
    expect(underline()).toContain(`left: ${width(first)}px`);
    widthSpy.mockRestore();
    leftSpy.mockRestore();
  });

  it("SavedViewsTabs moves the underline when a view's count arrives and widens a tab before it", async () => {
    // jsdom has no layout: a tab is 10 px per character, placed after the tabs before it.
    const width = (el: HTMLElement) => (el.textContent ?? "").trim().length * 10;
    const widthSpy = vi.spyOn(HTMLElement.prototype, "offsetWidth", "get").mockImplementation(function (this: HTMLElement) {
      return width(this);
    });
    const leftSpy = vi.spyOn(HTMLElement.prototype, "offsetLeft", "get").mockImplementation(function (this: HTMLElement) {
      let left = 0;
      for (let el = this.previousElementSibling as HTMLElement | null; el; el = el.previousElementSibling as HTMLElement | null) if (el.dataset.active) left += width(el);
      return left;
    });
    const views = (count?: number) => [
      { id: "verify", name: "To verify", builtin: true, count },
      { id: "all", name: "All", builtin: true },
    ];
    const tabs = mount(SavedViewsTabs, { props: { modelValue: "all", views: views() as never }, global: { plugins: plugins() } });
    await flushPromises();
    const underline = () => tabs.find("[role='tablist'] > span[aria-hidden='true']").attributes("style");
    expect(underline()).toContain("left: 90px");
    await tabs.setProps({ views: views(4) as never });
    await flushPromises();
    const first = tabs.find("[data-active='false']").element as HTMLElement;
    expect(width(first)).toBeGreaterThan(90);
    expect(underline()).toContain(`left: ${width(first)}px`);
    widthSpy.mockRestore();
    leftSpy.mockRestore();
  });

  it("TextInput marks a clearable field, so a search field shows only its own clear button", async () => {
    const search = mount(TextInput, { props: { modelValue: "milk", type: "search", clearable: true }, global: { plugins: plugins() } });
    expect(search.find("input").attributes("data-clearable")).toBe("true");
    expect(search.findAll("button[aria-label='Clear']")).toHaveLength(1);
    const plain = mount(TextInput, { props: { modelValue: "milk", type: "search" }, global: { plugins: plugins() } });
    expect(plain.find("input").attributes("data-clearable")).toBeUndefined();
  });

  it("CalendarWeek puts the first hour's label below its line, clear of the sticky day headers", () => {
    const week = mount(CalendarWeek, { props: { items: [], week: "2026-10-19", startHour: 7, endHour: 10 }, global: { plugins: plugins() } });
    const labels = week.findAll("[data-hour-label]");
    expect(labels.map((label) => label.text())).toEqual(["07:00", "08:00", "09:00"]);
    expect(labels[0]!.classes()).toContain("top-0.5");
    expect(labels[1]!.classes()).toContain("-top-2");
  });

  it("UiDrawer lets its description run to two lines", async () => {
    await router.push("/c/1/tasks?task=1");
    const wrapper = mount(UiDrawer, {
      props: { queryKey: "task", title: "Task", description: "A long description that needs a second line on a narrow drawer" },
      global: { plugins: plugins() },
      attachTo: document.body,
    });
    await flushPromises();
    const description = document.body.querySelector<HTMLElement>("[role=dialog] header p")!;
    expect(description.className).toContain("line-clamp-2");
    expect(description.className).not.toContain("truncate");
    wrapper.unmount();
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

describe("WidgetCard", () => {
  it("frames a widget: title, a count only when there is one, the page link and a footer", () => {
    const card = mount(WidgetCard, {
      props: { title: "Projects at risk", count: 2, countTone: "warning", to: "/c/1/projects" },
      slots: { default: () => h("ul", [h("li", "Chilonzor opening")]), footer: () => "1 more" },
      global: { plugins: plugins() },
    });
    expect(card.find("h3").text()).toBe("Projects at risk");
    expect(card.find("header").text()).toContain("2");
    const link = card.find("a");
    expect(link.attributes("href")).toBe("/c/1/projects");
    expect(link.attributes("title")).toBe("View all");
    expect(card.find("footer").text()).toBe("1 more");
    const empty = mount(WidgetCard, { props: { title: "Off today", count: 0 }, global: { plugins: plugins() } });
    expect(empty.find("h3").element.parentElement!.textContent!.trim()).toBe("Off today");
    expect(empty.find("a").exists()).toBe(false);
  });

  it("fades only the edge that has more to scroll to", () => {
    expect(fadeMask(0, 300, 300)).toBeNull();
    expect(fadeMask(0, 300, 500)).toBe("linear-gradient(to bottom, #000 0, #000 14px, #000 calc(100% - 14px), transparent 100%)");
    expect(fadeMask(100, 300, 500)).toContain("transparent 0");
    expect(fadeMask(100, 300, 500)).toContain("transparent 100%");
    expect(fadeMask(200, 300, 500)).toBe("linear-gradient(to bottom, transparent 0, #000 14px, #000 calc(100% - 14px), #000 100%)");
  });

  it("KpiCard keeps its label when the number fails, and Try again doesn't follow the tile's link", async () => {
    const retry = vi.fn();
    const tile = mount(KpiCard, {
      props: { label: "Done today", value: null, to: "/c/1/tasks", error: new ApiError(500, null), retry },
      global: { plugins: plugins() },
    });
    expect(tile.text()).toContain("Done today");
    expect(tile.find("[role='alert']").exists()).toBe(true);
    const before = router.currentRoute.value.fullPath;
    await tile.find("[role='alert'] button").trigger("click");
    await flushPromises();
    expect(retry).toHaveBeenCalledTimes(1);
    expect(router.currentRoute.value.fullPath).toBe(before);
  });

  it("knows when a wide table still has columns past its right edge", () => {
    expect(moreToTheRight(0, 1000, 1000)).toBe(false);
    expect(moreToTheRight(0, 1000, 1240)).toBe(true);
    expect(moreToTheRight(240, 1000, 1240)).toBe(false);
  });
});
