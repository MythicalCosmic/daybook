import { createPinia, setActivePinia } from "pinia";
import { afterEach, describe, expect, it, vi } from "vitest";
import { effectScope, nextTick, ref } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";

import { closeTopOverlay, overlayOpen, useBackCloses } from "@/lib/backStack";
import { bindTelegram, detectTelegram, type TelegramWebApp } from "@/shell/TelegramBridge";

const scopes: Array<ReturnType<typeof effectScope>> = [];
function overlay(initiallyOpen = true) {
  const open = ref(initiallyOpen);
  const scope = effectScope();
  scope.run(() => useBackCloses(open, () => (open.value = false)));
  scopes.push(scope);
  return { open, scope };
}

afterEach(() => {
  scopes.splice(0).forEach((scope) => scope.stop());
});

describe("backStack", () => {
  it("closes the overlay opened last first, then the one under it", async () => {
    const sheet = overlay();
    const lightbox = overlay();
    await nextTick();
    expect(overlayOpen.value).toBe(true);
    expect(closeTopOverlay()).toBe(true);
    expect(lightbox.open.value).toBe(false);
    expect(sheet.open.value).toBe(true);
    await nextTick();
    expect(closeTopOverlay()).toBe(true);
    expect(sheet.open.value).toBe(false);
    await nextTick();
    expect(overlayOpen.value).toBe(false);
    expect(closeTopOverlay()).toBe(false);
  });

  it("forgets an overlay that closed by itself or unmounted", async () => {
    const sheet = overlay();
    const dialog = overlay();
    await nextTick();
    sheet.open.value = false;
    dialog.scope.stop();
    await nextTick();
    expect(overlayOpen.value).toBe(false);
    sheet.open.value = true;
    await nextTick();
    expect(overlayOpen.value).toBe(true);
  });
});

describe("Telegram's BackButton", () => {
  it("shows while a sheet is open on the first screen and closes the sheet, not the console", async () => {
    setActivePinia(createPinia());
    let onBack: (() => void) | null = null;
    const backButton = { show: vi.fn(), hide: vi.fn(), onClick: vi.fn((cb: () => void) => (onBack = cb)), offClick: vi.fn() };
    const webApp = {
      initData: "query_id=1&user=%7B%22id%22%3A1001%7D&auth_date=1&hash=x",
      initDataUnsafe: {},
      version: "8.0",
      platform: "ios",
      colorScheme: "light",
      themeParams: {},
      isVersionAtLeast: () => true,
      close: vi.fn(),
      ready: vi.fn(),
      expand: vi.fn(),
      setHeaderColor: vi.fn(),
      setBackgroundColor: vi.fn(),
      onEvent: vi.fn(),
      offEvent: vi.fn(),
      BackButton: backButton,
    } satisfies TelegramWebApp;
    window.Telegram = { WebApp: webApp };
    window.location.hash = "#tgWebAppData=x&tgWebAppVersion=8.0";
    await detectTelegram();
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: "/:any(.*)*", component: { render: () => null } }] });
    const back = vi.spyOn(router, "back");
    bindTelegram(router);
    await router.push("/c/1");
    expect(backButton.hide).toHaveBeenLastCalledWith();

    const sheet = overlay();
    await nextTick();
    expect(backButton.show).toHaveBeenCalled();
    onBack!();
    expect(sheet.open.value).toBe(false);
    expect(back).not.toHaveBeenCalled();
    await nextTick();
    expect(backButton.hide).toHaveBeenCalled();

    // Nothing open: Back goes back.
    onBack!();
    expect(back).toHaveBeenCalledOnce();
    window.location.hash = "";
    delete window.Telegram;
  });
});
