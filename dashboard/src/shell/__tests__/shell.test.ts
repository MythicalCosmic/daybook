// The registry first, as in the app.
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";

import { usePaletteStore } from "@/stores/palette";
import { useSessionStore } from "@/stores/session";
import { company, json, manager, me } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

import CommandPalette from "../CommandPalette.vue";
import CompanySwitcher from "../CompanySwitcher.vue";
import { bufferKeysUntilPaletteMounts, loadPalette, markPaletteMounted, prefetchPaletteOnModifier } from "../paletteLoader";

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

describe("palette and switcher", () => {
  it("keeps the keys typed before its field has focus", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json({ results: [] })));
    Element.prototype.scrollIntoView ??= () => undefined;
    const app = await testApp("/c/1");
    const { wrapper } = mountWithProviders(CommandPalette, { plugins: app.plugins, props: { groups: [], aiAvailable: false } });
    usePaletteStore().show();
    await flushPromises();
    const input = document.querySelector<HTMLInputElement>("[data-palette-input]")!;
    expect(input).toBeTruthy();
    // The dialog is up but focus is still elsewhere, as in the frame after ⌘K: a shortcut with a
    // modifier is left alone, a letter lands in the field, and the field takes focus for the rest.
    input.blur();
    document.body.dispatchEvent(new KeyboardEvent("keydown", { key: "k", ctrlKey: true, bubbles: true, cancelable: true }));
    const typed = new KeyboardEvent("keydown", { key: "C", bubbles: true, cancelable: true });
    document.body.dispatchEvent(typed);
    await flushPromises();
    expect(typed.defaultPrevented).toBe(true);
    expect(input.value).toBe("C");
    expect(document.activeElement).toBe(input);
    // Once the field has focus, keys are its own.
    const next = new KeyboardEvent("keydown", { key: "H", bubbles: true, cancelable: true });
    input.dispatchEvent(next);
    expect(next.defaultPrevented).toBe(false);
    wrapper.unmount();
  });

  it("the company switcher leaves this company's count to the Inbox and dots the others' waiting work", async () => {
    const app = await testApp("/c/1");
    useSessionStore().me = me([company({ pending: 23 }), manager([], { pending: 5 })]);
    const { wrapper } = mountWithProviders(CompanySwitcher, { plugins: app.plugins });
    await flushPromises();
    expect(wrapper.text()).not.toContain("23");
    const dot = wrapper.find("[data-elsewhere]");
    expect(dot.attributes("title")).toBe("5 waiting in your other companies");
    useSessionStore().me = me([company({ pending: 23 }), manager([], { pending: 0 })]);
    await flushPromises();
    expect(wrapper.find("[data-elsewhere]").exists()).toBe(false);
    wrapper.unmount();
  });

  it("buffers the keys typed after ⌘K while the palette's code still loads, and leaves shortcuts alone", () => {
    let open = false;
    let buffered = "";
    const target = new EventTarget() as unknown as Window;
    const remove = bufferKeysUntilPaletteMounts(
      () => open,
      (key) => (buffered += key),
      target,
    );
    const press = (key: string, init: KeyboardEventInit = {}) => {
      const event = new KeyboardEvent("keydown", { key, cancelable: true, ...init });
      target.dispatchEvent(event);
      return event;
    };
    expect(press("n").defaultPrevented).toBe(false); // closed: "n" is the page's shortcut
    open = true;
    expect(press("C").defaultPrevented).toBe(true); // open, still loading: it is the search
    press("H");
    press("k", { ctrlKey: true });
    expect(buffered).toBe("CH");
    markPaletteMounted(true); // mounted: the palette catches its own keys from here on
    press("L");
    expect(buffered).toBe("CH");
    markPaletteMounted(false);
    remove();
  });

  it("starts loading as soon as Ctrl or ⌘ goes down, once", async () => {
    const listeners = new Map<string, (event: KeyboardEvent) => void>();
    const target = {
      addEventListener: vi.fn((type: string, listener: (event: KeyboardEvent) => void) => listeners.set(type, listener)),
      removeEventListener: vi.fn((type: string) => listeners.delete(type)),
    };
    prefetchPaletteOnModifier(target as unknown as Window);
    listeners.get("keydown")!({ key: "a" } as KeyboardEvent);
    expect(target.removeEventListener).not.toHaveBeenCalled();
    listeners.get("keydown")!({ key: "Control" } as KeyboardEvent);
    expect(target.removeEventListener).toHaveBeenCalledWith("keydown", expect.any(Function));
    // The same load the palette's first opening waits for.
    expect(loadPalette()).toBe(loadPalette());
    await expect(loadPalette()).resolves.toHaveProperty("default");
  });
});
