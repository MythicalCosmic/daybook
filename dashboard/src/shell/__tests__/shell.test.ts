// The registry first, as in the app.
import "@/core/modules";

import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query";
import { flushPromises, mount as mountRaw } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createMemoryHistory, createRouter } from "vue-router";

import { findModule } from "@/core/modules";
import { ensureModuleMessages, i18n, setLanguage } from "@/i18n";
import { useCompanyStore } from "@/stores/company";
import { usePaletteStore } from "@/stores/palette";
import { useSessionStore } from "@/stores/session";
import { company, json, manager, me } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

import CommandPalette from "../CommandPalette.vue";
import CompanySwitcher from "../CompanySwitcher.vue";
import ForbiddenPage from "../ForbiddenPage.vue";
import MobileTabBar from "../MobileTabBar.vue";
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

  it("leads with the group the query names, and leaves out loose fuzzy matches", async () => {
    // The server lists payments that mention Barakat Farm before the counterparty itself.
    const results = [
      { type: "finance.transaction", id: 1, title: "Debt payment", subtitle: "19.10.2026 · 1 500 000 UZS · Barakat Farm", url: "finance/transactions?txn=1" },
      { type: "finance.transaction", id: 2, title: "Ulgurji, nasiyaga", subtitle: "Barakat Farm", url: "finance/transactions?txn=2" },
      { type: "finance.counterparty", id: 3, title: "Barakat Farm", subtitle: "Customer", url: "finance/counterparties?cp=3" },
    ];
    vi.stubGlobal("fetch", vi.fn(async (url: string) => json(String(url).includes("/search/") ? { results } : {})));
    Element.prototype.scrollIntoView ??= () => undefined;
    const app = await testApp("/c/1");
    const { wrapper } = mountWithProviders(CommandPalette, { plugins: app.plugins, props: { groups: [], aiAvailable: false } });
    usePaletteStore().show();
    await flushPromises();
    const input = document.querySelector<HTMLInputElement>("[data-palette-input]")!;
    input.value = "Barakat";
    input.dispatchEvent(new Event("input", { bubbles: true }));
    await new Promise((resolve) => setTimeout(resolve, 250));
    await flushPromises();
    const text = document.querySelector("[role='dialog']")!.textContent ?? "";
    expect(text.indexOf("Counterparties")).toBeGreaterThan(-1);
    expect(text.indexOf("Counterparties")).toBeLessThan(text.indexOf("Transactions"));
    // "Barakat" is two letters off the Uzbek "xarajat" of Record an expense: not a match.
    expect(text).not.toContain("Record an expense");
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

  it("the company switcher's button opens its menu on first use, loading the menu then", async () => {
    const app = await testApp("/c/1");
    useSessionStore().me = me([company({ pending: 23 }), manager([], { pending: 5 })]);
    const { wrapper } = mountWithProviders(CompanySwitcher, { plugins: app.plugins });
    await flushPromises();
    const button = wrapper.get("button[aria-label='Switch company']");
    expect(button.attributes("aria-haspopup")).toBe("menu");
    await button.trigger("click");
    await vi.waitFor(() => expect(document.body.textContent).toContain("Your companies"), { timeout: 8000 });
    expect(wrapper.get("button[aria-label='Switch company']").attributes("aria-expanded")).toBe("true");
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

describe("a page that won't open", () => {
  async function forbidden(companies: ReturnType<typeof company>[], path: string, meta: Record<string, unknown>) {
    const pinia = createPinia();
    setActivePinia(pinia);
    useSessionStore().me = me(companies);
    useCompanyStore().setCurrent(companies[0]!.id);
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: "/c/:companyId/:rest(.*)*", component: { render: () => null }, meta }] });
    await router.push(path);
    // The module's name comes from its own dictionary, as the shell loads it in the app.
    const module = findModule(String(meta.module));
    if (module) await ensureModuleMessages(module, "en");
    const client = new QueryClient();
    const wrapper = mountRaw(ForbiddenPage, { global: { plugins: [pinia, router, i18n, [VueQueryPlugin, { queryClient: client }]] } });
    await flushPromises();
    return wrapper;
  }

  it("says the company has the module switched off, and offers Settings › Modules to whoever may switch it on", async () => {
    // Sales is off for this company; the owner may change modules.
    const owner = await forbidden([company({ features: ["finance"] })], "/c/1/sales", { module: "sales" });
    expect(owner.text()).toContain("Sales is off in Demo Dorixona");
    expect(owner.text()).not.toContain("Your role");
    expect(owner.get("a[href='/c/1/settings/features']").text()).toBe("Open Settings › Modules");
    owner.unmount();
    // A manager can't change modules: told who can, no link to a page they can't open.
    const staff = await forbidden([manager([], { id: 1, name: "Demo Distribyutor", features: [] })], "/c/1/sales", { module: "sales" });
    expect(staff.text()).toContain("The owner can switch it on");
    expect(staff.find("a[href='/c/1/settings/features']").exists()).toBe(false);
    staff.unmount();
  });

  it("still says the role is the reason when the module is on", async () => {
    const page = await forbidden([manager([], { id: 1 })], "/c/1/finance", { module: "finance" });
    expect(page.text()).toContain("This page isn’t open to you");
    expect(page.find("[data-switched-off]").exists()).toBe(false);
    page.unmount();
  });
});

describe("phone tab bar", () => {
  it("names the whole Work area, not just Tasks (Routines, Projects and Reminders live there too)", async () => {
    const entry = (moduleId: string) => ({ key: moduleId, moduleId, title: `${moduleId}.title`, path: `/c/1/${moduleId}`, group: "work" as const, hotkey: undefined, children: [], badge: 0, icon: {} });
    const groups = [{ id: "work" as const, modules: [entry("tasks"), entry("routines")], badge: 2 }];
    for (const [language, label] of [["en", "Work"], ["uz", "Ish"], ["ru", "Работа"]] as const) {
      const app = await testApp("/c/1/routines", language);
      // A module dictionary loaded by an earlier test must arrive in this language first.
      await setLanguage(language);
      const { wrapper } = mountWithProviders(MobileTabBar, { plugins: app.plugins, props: { groups, moreOpen: false } });
      await flushPromises();
      const tab = wrapper.find('a[href="/c/1/tasks"]');
      expect(tab.text()).toBe(label);
      wrapper.unmount();
    }
  });
});
