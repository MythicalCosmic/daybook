import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

type WebApp = Window["Telegram"]["WebApp"];

/** A fake WebApp for a given Bot API version, recording what the app asks of it. */
function fakeWebApp(version: string) {
  const at = (wanted: string) => {
    const [a, b] = version.split(".").map(Number);
    const [c, d] = wanted.split(".").map(Number);
    return a > c || (a === c && b >= d);
  };
  const button = () => ({
    setParams: vi.fn(),
    showProgress: vi.fn(),
    hideProgress: vi.fn(),
    onClick: vi.fn(),
    offClick: vi.fn(),
    show: vi.fn(),
    hide: vi.fn(),
  });
  const store = new Map<string, string>();
  return {
    platform: "android",
    isVersionAtLeast: at,
    initDataUnsafe: { start_param: "payslip-12" },
    HapticFeedback: { impactOccurred: vi.fn(), notificationOccurred: vi.fn(), selectionChanged: vi.fn() },
    MainButton: button(),
    SecondaryButton: button(),
    BackButton: { show: vi.fn(), hide: vi.fn(), onClick: vi.fn(), offClick: vi.fn() },
    disableVerticalSwipes: vi.fn(),
    enableVerticalSwipes: vi.fn(),
    requestFullscreen: vi.fn(),
    isFullscreen: false,
    onEvent: vi.fn(),
    offEvent: vi.fn(),
    showScanQrPopup: vi.fn(),
    closeScanQrPopup: vi.fn(),
    CloudStorage: {
      setItem: vi.fn((key: string, value: string, done: (error: string | null, ok: true | null) => void) => {
        store.set(key, value);
        done(null, true);
      }),
      getItem: vi.fn((key: string, done: (error: string | null, value: string | null) => void) => done(null, store.get(key) ?? "")),
      removeItem: vi.fn((key: string, done: () => void) => {
        store.delete(key);
        done();
      }),
      getKeys: vi.fn((done: (error: string | null, keys: string[]) => void) => done(null, [...store.keys()])),
    },
  };
}

async function load(webApp?: ReturnType<typeof fakeWebApp>) {
  vi.resetModules();
  vi.stubGlobal("Telegram", webApp ? { WebApp: webApp as unknown as WebApp } : undefined);
  return import("./telegram");
}

describe("telegram helpers", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => vi.unstubAllGlobals());

  it("keep the original haptic() calls and add notify, select and impact", async () => {
    const webApp = fakeWebApp("8.0");
    const { haptic } = await load(webApp);
    haptic();
    haptic("success");
    haptic.notify("warning");
    haptic.select();
    haptic.impact("heavy");
    expect(webApp.HapticFeedback.impactOccurred.mock.calls).toEqual([["light"], ["heavy"]]);
    expect(webApp.HapticFeedback.notificationOccurred.mock.calls).toEqual([["success"], ["warning"]]);
    expect(webApp.HapticFeedback.selectionChanged).toHaveBeenCalledOnce();
  });

  it("do nothing outside Telegram instead of failing", async () => {
    const telegram = await load();
    expect(() => {
      telegram.haptic.notify("success");
      telegram.disableVerticalSwipes()();
      telegram.exitFullscreen();
    }).not.toThrow();
    expect(telegram.requestFullscreen()).toBe(false);
    expect(telegram.showNativeButton("main", { text: "Send", onClick: () => undefined })).toBeNull();
    expect(telegram.hasNativeBackButton()).toBe(false);
    expect(await telegram.scanQr()).toBeNull();
    expect(telegram.startParam()).toBeNull();
  });

  it("treat telegram-web-app.js in a plain browser as outside Telegram", async () => {
    // Outside a client the script reports platform "unknown" and version 6.0: no one draws buttons.
    const browser = { ...fakeWebApp("6.0"), platform: "unknown" };
    const telegram = await load(browser);
    expect(telegram.insideTelegram()).toBe(false);
    expect(telegram.hasNativeButton("main")).toBe(false);
    expect(telegram.bottomButton({ text: "Send", onClick: () => undefined })).toBeNull();
    expect(browser.MainButton.show).not.toHaveBeenCalled();
    expect((await load(fakeWebApp("6.0"))).insideTelegram()).toBe(true);
  });

  it("open only web links", async () => {
    const webApp = { ...fakeWebApp("8.0"), openLink: vi.fn(), openTelegramLink: vi.fn() };
    const telegram = await load(webApp);
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    expect(telegram.openLink("/api/v1/files/abc/")).toBe(true);
    expect(webApp.openLink).toHaveBeenCalledWith(`${window.location.origin}/api/v1/files/abc/`);
    expect(telegram.openLink("javascript:alert(1)")).toBe(false);
    expect(telegram.openLink("data:text/html,<b>x</b>")).toBe(false);
    expect(webApp.openLink).toHaveBeenCalledOnce();
    expect(telegram.openTelegramLink("https://t.me/aziz")).toBe(true);
    expect(telegram.openTelegramLink("https://evil.example/t.me")).toBe(false);
    expect(webApp.openTelegramLink).toHaveBeenCalledOnce();
  });

  it("drive the main and secondary buttons and clean up after them", async () => {
    const webApp = fakeWebApp("7.10");
    const { showNativeButton, hasNativeButton } = await load(webApp);
    expect(hasNativeButton("secondary")).toBe(true);
    const onClick = vi.fn();
    const cleanup = showNativeButton("main", { text: "Close the till", onClick, loading: true, color: "#c67139", textColor: "#f5ead8", shine: true });
    expect(webApp.MainButton.setParams).toHaveBeenCalledWith({
      text: "Close the till",
      color: "#c67139",
      text_color: "#f5ead8",
      has_shine_effect: true,
      is_active: false,
    });
    expect(webApp.MainButton.showProgress).toHaveBeenCalledWith(false);
    expect(webApp.MainButton.onClick).toHaveBeenCalledWith(onClick);
    expect(webApp.MainButton.show).toHaveBeenCalled();
    cleanup!();
    expect(webApp.MainButton.offClick).toHaveBeenCalledWith(onClick);
    expect(webApp.MainButton.hide).toHaveBeenCalled();
  });

  it("keep a disabled button disabled, though Telegram's hideProgress() switches it back on", async () => {
    const webApp = fakeWebApp("8.0");
    // Telegram's own rules (telegram-web-app.js): setParams sets the flag, showProgress(false)
    // clears it, and hideProgress() makes an inactive button active again.
    let active = true;
    webApp.MainButton.setParams.mockImplementation((params: { is_active?: boolean }) => {
      if (params.is_active !== undefined) active = params.is_active;
    });
    webApp.MainButton.showProgress.mockImplementation((leaveActive?: boolean) => {
      active = Boolean(leaveActive);
    });
    webApp.MainButton.hideProgress.mockImplementation(() => {
      active = true;
    });
    const { updateNativeButton } = await load(webApp);
    updateNativeButton("main", { text: "Send my request", disabled: true });
    expect(active).toBe(false);
    updateNativeButton("main", { text: "Send my request" });
    expect(active).toBe(true);
    updateNativeButton("main", { text: "Sending…", loading: true });
    expect(active).toBe(false);
    updateNativeButton("main", { text: "Send my request", disabled: true });
    expect(active).toBe(false);
  });

  it("tell an app opened from a keyboard button (Telegram, no sign-in) from a browser", async () => {
    vi.stubEnv("VITE_DEV_INIT_DATA", "");
    const keyboard = { ...fakeWebApp("8.0"), initData: "", sendData: vi.fn() };
    const telegram = await load(keyboard);
    expect(telegram.openedWithoutSignIn()).toBe(true);
    // Telegram lets exactly such an app send the bot a line (and closes it).
    expect(telegram.sendToBot("open_app")).toBe(true);
    expect(keyboard.sendData).toHaveBeenCalledWith("open_app");

    // A browser: telegram-web-app.js is there too, but reports the platform "unknown".
    const browser = { ...fakeWebApp("6.0"), platform: "unknown", initData: "", sendData: vi.fn() };
    const outside = await load(browser);
    expect(outside.openedWithoutSignIn()).toBe(false);
    expect(outside.sendToBot("open_app")).toBe(false);
    expect(browser.sendData).not.toHaveBeenCalled();

    const signed = { ...fakeWebApp("8.0"), initData: "user=%7B%22id%22%3A1%7D&hash=abc" };
    const signedIn = await load(signed);
    expect(signedIn.openedWithoutSignIn()).toBe(false);
    vi.unstubAllEnvs();
  });

  it("follow Telegram's light or dark theme inside it, and the browser's outside", async () => {
    const dark = vi.fn(() => ({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() }));
    vi.stubGlobal("matchMedia", dark);
    const inside = await load({ ...fakeWebApp("8.0"), colorScheme: "light" } as ReturnType<typeof fakeWebApp>);
    expect(inside.colorScheme()).toBe("light");
    const browser = await load({ ...fakeWebApp("6.0"), platform: "unknown" });
    expect(browser.colorScheme()).toBe("dark");
    const changed = vi.fn();
    browser.onThemeChange(changed)();
    expect(dark).toHaveBeenCalledWith("(prefers-color-scheme: dark)");
  });

  it("have no secondary button before Bot API 7.10", async () => {
    const { hasNativeButton, secondaryButton } = await load(fakeWebApp("7.7"));
    expect(hasNativeButton("main")).toBe(true);
    expect(hasNativeButton("secondary")).toBe(false);
    expect(secondaryButton({ text: "Later", onClick: () => undefined })).toBeNull();
  });

  it("stack vertical swipe locks so nested sheets don't re-enable them early", async () => {
    const webApp = fakeWebApp("8.0");
    const { disableVerticalSwipes } = await load(webApp);
    const outer = disableVerticalSwipes();
    const inner = disableVerticalSwipes();
    expect(webApp.disableVerticalSwipes).toHaveBeenCalledOnce();
    inner();
    inner();
    expect(webApp.enableVerticalSwipes).not.toHaveBeenCalled();
    outer();
    expect(webApp.enableVerticalSwipes).toHaveBeenCalledOnce();
  });

  it("guard full screen behind Bot API 8.0", async () => {
    const modern = fakeWebApp("8.0");
    expect((await load(modern)).requestFullscreen()).toBe(true);
    expect(modern.requestFullscreen).toHaveBeenCalledOnce();
    const older = fakeWebApp("7.10");
    expect((await load(older)).requestFullscreen()).toBe(false);
    expect(older.requestFullscreen).not.toHaveBeenCalled();
  });

  it("resolve a scanned QR code and close the scanner", async () => {
    const webApp = fakeWebApp("8.0");
    webApp.showScanQrPopup.mockImplementation((_params: unknown, callback: (data: string) => boolean) => callback("SKU-1042"));
    const { scanQr } = await load(webApp);
    expect(await scanQr("Point at the barcode")).toBe("SKU-1042");
    expect(webApp.closeScanQrPopup).toHaveBeenCalled();
    expect(webApp.offEvent).toHaveBeenCalledWith("scanQrPopupClosed", expect.any(Function));
  });

  it("read the start parameter", async () => {
    expect((await load(fakeWebApp("8.0"))).startParam()).toBe("payslip-12");
  });

  it("keep drafts in CloudStorage, or in localStorage where there is none", async () => {
    const webApp = fakeWebApp("8.0");
    const cloud = (await load(webApp)).cloudStorage;
    expect(await cloud.set("kassa_draft", "{\"cash\":\"1250000\"}")).toBe(true);
    expect(await cloud.get("kassa_draft")).toBe("{\"cash\":\"1250000\"}");
    expect(await cloud.keys()).toEqual(["kassa_draft"]);
    await cloud.remove("kassa_draft");
    expect(await cloud.get("kassa_draft")).toBeNull();
    expect(webApp.CloudStorage.setItem).toHaveBeenCalled();

    const local = (await load()).cloudStorage;
    expect(await local.set("kassa_draft", "x")).toBe(true);
    expect(localStorage.getItem("daybook.cloud.kassa_draft")).toBe("x");
    expect(await local.get("kassa_draft")).toBe("x");
    expect(await local.keys()).toEqual(["kassa_draft"]);
    await local.remove("kassa_draft");
    expect(await local.get("kassa_draft")).toBeNull();

    // Telegram's limits apply on both paths.
    expect(await local.set("bad key!", "x")).toBe(false);
    expect(await local.set("big", "x".repeat(4097))).toBe(false);
  });
});
