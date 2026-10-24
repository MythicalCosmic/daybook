/**
 * Nothing typed is lost to a gesture (audit M-6): a sheet stops the swipe that minimises the app,
 * and a draft makes Telegram ask before closing; both come back when they're gone.
 */
import { cleanup, render } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

function stubTelegram() {
  const webApp = {
    platform: "android",
    initData: "",
    initDataUnsafe: {},
    isVersionAtLeast: () => true,
    disableVerticalSwipes: vi.fn(),
    enableVerticalSwipes: vi.fn(),
    enableClosingConfirmation: vi.fn(),
    disableClosingConfirmation: vi.fn(),
    MainButton: undefined,
    SecondaryButton: undefined,
  };
  vi.stubGlobal("Telegram", { WebApp: webApp });
  return webApp;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.resetModules();
});

describe("guards against losing a draft", () => {
  it("a sheet blocks the swipe-down while it's open", async () => {
    const webApp = stubTelegram();
    vi.resetModules();
    const { Sheet } = await import("../ui/Sheet");
    const view = render(<Sheet onClose={() => undefined}>Hello</Sheet>);
    expect(webApp.disableVerticalSwipes).toHaveBeenCalledOnce();
    view.unmount();
    expect(webApp.enableVerticalSwipes).toHaveBeenCalledOnce();
  });

  it("a draft makes closing ask first, until it's sent or cleared", async () => {
    const webApp = stubTelegram();
    vi.resetModules();
    const { useDraftGuard } = await import("./useDraftGuard");
    let setText: (text: string) => void = () => undefined;
    function Form() {
      const [text, set] = useState("");
      setText = set;
      useDraftGuard(Boolean(text));
      return <span>{text}</span>;
    }
    const { act } = await import("@testing-library/react");
    render(<Form />);
    expect(webApp.enableClosingConfirmation).not.toHaveBeenCalled();
    act(() => setText("Terminal receipt is missing"));
    expect(webApp.enableClosingConfirmation).toHaveBeenCalledOnce();
    act(() => setText(""));
    expect(webApp.disableClosingConfirmation).toHaveBeenCalledOnce();
  });
});
