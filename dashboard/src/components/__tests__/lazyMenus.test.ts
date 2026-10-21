// Menus and tooltips stay out of the first load (README "Budgets"): the menu code loads on first
// use or when the browser is idle, and tooltips need no positioning library.
import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";
import { defineComponent, h } from "vue";

import { placeTooltip } from "@/components/tooltip";
import UiTooltip from "@/components/UiTooltip.vue";

afterEach(() => {
  vi.useRealTimers();
  document.body.innerHTML = "";
});

describe("lazy menus", () => {
  it("shows the trigger as it is until the menu loads, then opens it on the first click", async () => {
    // A fresh copy of the modules: the menu's code isn't loaded yet, as on the first page.
    vi.resetModules();
    const { default: DropdownMenu } = await import("@/components/DropdownMenu.vue");
    const { menuPanel } = await import("@/components/lazyPart");
    expect(menuPanel.current).toBeNull();
    const onSelect = vi.fn();
    const wrapper = mount(DropdownMenu, {
      props: { items: [{ label: "Log out", onSelect }] },
      slots: { trigger: () => h("button", { type: "button", "data-trigger": "" }, "Account") },
      attachTo: document.body,
    });
    const trigger = wrapper.get("[data-trigger]");
    expect(trigger.attributes("aria-haspopup")).toBe("menu");
    expect(document.body.textContent).not.toContain("Log out");

    await trigger.trigger("click");
    // The menu's code arrives (a fresh module graph to compile in a test: give it time) and opens.
    await vi.waitFor(() => expect(menuPanel.current).not.toBeNull(), { timeout: 8000 });
    await vi.waitFor(() => expect(document.body.textContent).toContain("Log out"), { timeout: 3000 });
    // The real trigger has taken over, open.
    expect(wrapper.get("[data-trigger]").attributes("aria-expanded")).toBe("true");
    expect(onSelect).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it("loads each part once, whoever asks first", async () => {
    vi.resetModules();
    const { lazyPart } = await import("@/components/lazyPart");
    const importer = vi.fn(async () => ({ default: defineComponent({ render: () => null }) }));
    const part = lazyPart(importer);
    await Promise.all([part.load(), part.load()]);
    expect(importer).toHaveBeenCalledTimes(1);
    expect(part.current).not.toBeNull();
  });
});

describe("UiTooltip", () => {
  const mountTip = (props: Record<string, unknown> = {}) =>
    mount(UiTooltip, {
      props: { content: "Inbox", shortcut: "g i", ...props },
      slots: { default: () => h("button", { type: "button", "aria-label": "Inbox" }, "i") },
      attachTo: document.body,
    });
  const tip = () => document.body.querySelector<HTMLElement>("[role='tooltip']");

  it("opens after a pause on hover, describes its trigger, and closes on leaving", async () => {
    vi.useFakeTimers();
    const wrapper = mountTip();
    const button = wrapper.get("button");
    await button.trigger("pointerenter", { pointerType: "mouse" });
    expect(tip()).toBeNull();
    vi.advanceTimersByTime(460);
    await flushPromises();
    expect(tip()!.textContent).toContain("Inbox");
    expect(button.attributes("aria-describedby")).toBe(tip()!.id);
    await button.trigger("pointerleave");
    expect(tip()).toBeNull();
    wrapper.unmount();
  });

  it("never opens on touch, closes on a press and on Escape, and opens at once on keyboard focus", async () => {
    vi.useFakeTimers();
    const wrapper = mountTip();
    const button = wrapper.get("button");
    await button.trigger("pointerenter", { pointerType: "touch" });
    vi.advanceTimersByTime(1000);
    await flushPromises();
    expect(tip()).toBeNull();

    await button.trigger("pointerenter", { pointerType: "mouse" });
    vi.advanceTimersByTime(460);
    await flushPromises();
    expect(tip()).not.toBeNull();
    await button.trigger("pointerdown");
    expect(tip()).toBeNull();

    // Keyboard focus (jsdom has no :focus-visible: the check is stubbed as true).
    const matches = vi.spyOn(HTMLElement.prototype, "matches").mockReturnValue(true);
    await button.trigger("focus");
    await flushPromises();
    expect(tip()).not.toBeNull();
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    await flushPromises();
    expect(tip()).toBeNull();
    matches.mockRestore();
    wrapper.unmount();
  });

  it("renders only its trigger when disabled or empty", () => {
    const wrapper = mountTip({ disabled: true });
    expect(wrapper.find("button").attributes("aria-describedby")).toBeUndefined();
    expect(wrapper.html()).not.toContain("tooltip");
    wrapper.unmount();
  });

  it("places itself on the asked side, flips when there is no room, and stays inside the window", () => {
    const viewport = { width: 1000, height: 800 };
    const size = { width: 120, height: 28 };
    const button = { left: 500, top: 400, width: 32, height: 32 };
    const top = placeTooltip(button, size, { side: "top", align: "center", offset: 6, viewport });
    expect(top).toMatchObject({ side: "top", x: 456, y: 366 });
    // Too close to the top of the window: below instead.
    expect(placeTooltip({ ...button, top: 10 }, size, { side: "top", align: "center", offset: 6, viewport }).side).toBe("bottom");
    // At the right edge: kept 8 px inside, the arrow still points at the button.
    const edge = placeTooltip({ ...button, left: 980 }, size, { side: "bottom", align: "center", offset: 6, viewport });
    expect(edge.x).toBe(1000 - 8 - 120);
    expect(Number.parseInt(edge.arrow.left!, 10)).toBeGreaterThan(80);
    // A rail tooltip on the right.
    expect(placeTooltip({ left: 8, top: 100, width: 40, height: 40 }, size, { side: "right", align: "center", offset: 10, viewport })).toMatchObject({ side: "right", x: 58, y: 106 });
  });
});
