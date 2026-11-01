/**
 * Nothing typed is lost to a gesture (audit M-6): a sheet stops the swipe that minimises the app,
 * and a draft makes Telegram ask before closing; both come back when they're gone.
 */
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
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
    const { I18nProvider } = await import("../i18n");
    const view = render(
      <I18nProvider lang="en">
        <Sheet onClose={() => undefined}>Hello</Sheet>
      </I18nProvider>,
    );
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
    render(<Form />);
    expect(webApp.enableClosingConfirmation).not.toHaveBeenCalled();
    act(() => setText("Terminal receipt is missing"));
    expect(webApp.enableClosingConfirmation).toHaveBeenCalledOnce();
    act(() => setText(""));
    expect(webApp.disableClosingConfirmation).toHaveBeenCalledOnce();
  });

  /** A sheet holding a reason field that guards its draft, on a fresh graph that reads the stub. */
  async function sheetWithReason(onClose: () => void) {
    vi.resetModules();
    const { Sheet } = await import("../ui/Sheet");
    const { I18nProvider } = await import("../i18n");
    const { useDraftGuard } = await import("./useDraftGuard");
    function Reason() {
      const [text, setText] = useState("");
      useDraftGuard(Boolean(text));
      return <textarea aria-label="Why?" value={text} onChange={(event) => setText(event.target.value)} />;
    }
    render(
      <I18nProvider lang="en">
        <Sheet onClose={onClose} label="Send back">
          <Reason />
        </Sheet>
      </I18nProvider>,
    );
    return { field: screen.getByRole("textbox", { name: "Why?" }), backdrop: document.querySelector(".sheet-backdrop")! };
  }

  it("a sheet with something typed asks before a tap beside it or Escape closes it", async () => {
    const webApp = stubTelegram();
    const answers = [false, true];
    const showConfirm = vi.fn((_message: string, done: (ok: boolean) => void) => done(answers.shift()!));
    Object.assign(webApp, { showConfirm });
    const onClose = vi.fn();
    const { field, backdrop } = await sheetWithReason(onClose);
    fireEvent.change(field, { target: { value: "The photo is blurry" } });

    // With the keyboard up, a tap beside the sheet only puts the keyboard away.
    act(() => field.focus());
    fireEvent.click(backdrop);
    expect(document.activeElement).not.toBe(field);
    expect(showConfirm).not.toHaveBeenCalled();

    // Then it asks; Cancel keeps the sheet and the text.
    fireEvent.click(backdrop);
    expect(showConfirm).toHaveBeenCalledWith("Close it? What you entered won't be saved.", expect.any(Function));
    await act(async () => undefined);
    expect(onClose).not.toHaveBeenCalled();
    expect(field).toHaveProperty("value", "The photo is blurry");

    // Escape asks the same; OK closes it.
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(onClose).toHaveBeenCalledOnce());
    expect(showConfirm).toHaveBeenCalledTimes(2);
  });

  it("a sheet with nothing typed closes at once, without a question", async () => {
    const webApp = stubTelegram();
    const showConfirm = vi.fn();
    Object.assign(webApp, { showConfirm });
    const onClose = vi.fn();
    const { field, backdrop } = await sheetWithReason(onClose);
    act(() => field.focus());
    fireEvent.click(backdrop);
    expect(onClose).toHaveBeenCalledOnce();
    expect(showConfirm).not.toHaveBeenCalled();
  });
});
