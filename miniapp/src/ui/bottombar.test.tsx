import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

type WebApp = Window["Telegram"]["WebApp"];

function fakeButton() {
  const handlers: (() => void)[] = [];
  return {
    handlers,
    setParams: vi.fn(),
    showProgress: vi.fn(),
    hideProgress: vi.fn(),
    onClick: vi.fn((handler: () => void) => handlers.push(handler)),
    offClick: vi.fn((handler: () => void) => handlers.splice(handlers.indexOf(handler), 1)),
    show: vi.fn(),
    hide: vi.fn(),
  };
}

async function setup(version = "7.10", platform = "ios") {
  vi.resetModules();
  const main = fakeButton();
  const secondary = fakeButton();
  const at = (wanted: string) => {
    const [a, b] = version.split(".").map(Number);
    const [c, d] = wanted.split(".").map(Number);
    return a > c || (a === c && b >= d);
  };
  const webApp = { platform, isVersionAtLeast: at, MainButton: main, SecondaryButton: secondary };
  vi.stubGlobal("Telegram", { WebApp: webApp as unknown as WebApp });
  const { BottomBar } = await import("./BottomBar");
  return { BottomBar, main, secondary };
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("bottom bar", () => {
  it("uses Telegram's buttons when the client has them, and draws nothing in the page", async () => {
    const { BottomBar, main, secondary } = await setup();
    const send = vi.fn();
    const { container } = render(<BottomBar primary={{ text: "Send", onClick: send }} secondary={{ text: "Later", onClick: () => undefined }} />);
    expect(container.innerHTML).toBe("");
    expect(main.setParams).toHaveBeenLastCalledWith(expect.objectContaining({ text: "Send", is_active: true, color: "#c67139" }));
    expect(secondary.setParams).toHaveBeenLastCalledWith(expect.objectContaining({ text: "Later", position: "left" }));
    expect(main.show).toHaveBeenCalled();
    main.handlers.at(-1)!();
    expect(send).toHaveBeenCalledOnce();
  });

  it("hands the button back to the page when a sheet that borrowed it closes", async () => {
    const { BottomBar, main } = await setup();
    const pageAction = vi.fn();
    const sheetAction = vi.fn();
    const page = render(<BottomBar primary={{ text: "Ask for an advance", onClick: pageAction }} />);
    const sheet = render(<BottomBar primary={{ text: "Send request", onClick: sheetAction, loading: true }} />);
    expect(main.setParams).toHaveBeenLastCalledWith(expect.objectContaining({ text: "Send request", is_active: false }));
    expect(main.showProgress).toHaveBeenCalled();
    main.handlers.at(-1)!();
    expect(sheetAction).not.toHaveBeenCalled(); // busy: presses are ignored

    sheet.unmount();
    expect(main.setParams).toHaveBeenLastCalledWith(expect.objectContaining({ text: "Ask for an advance", is_active: true }));
    expect(main.hide).not.toHaveBeenCalled();
    main.handlers.at(-1)!();
    expect(pageAction).toHaveBeenCalledOnce();

    page.unmount();
    expect(main.hide).toHaveBeenCalledOnce();
    expect(main.handlers).toHaveLength(0);
  });

  it("follows text and state changes without hiding the button", async () => {
    const { BottomBar, main } = await setup();
    const view = render(<BottomBar primary={{ text: "Close the till", onClick: () => undefined, disabled: true }} />);
    view.rerender(<BottomBar primary={{ text: "Close the till", onClick: () => undefined }} />);
    expect(main.setParams).toHaveBeenLastCalledWith(expect.objectContaining({ is_active: true }));
    expect(main.hide).not.toHaveBeenCalled();
  });

  it("falls back to buttons in the page when the client can't draw both", async () => {
    const { BottomBar, main } = await setup("7.7");
    const { container } = render(<BottomBar primary={{ text: "Send", onClick: () => undefined }} secondary={{ text: "Later", onClick: () => undefined }} />);
    expect([...container.querySelectorAll(".action-bar button")].map((button) => button.textContent)).toEqual(["Later", "Send"]);
    expect(main.show).not.toHaveBeenCalled();
  });

  it("draws its buttons in the page in a plain browser, where telegram-web-app.js has nobody to draw them", async () => {
    const { BottomBar, main } = await setup("6.0", "unknown");
    const send = vi.fn();
    const { container, getByRole } = render(<BottomBar primary={{ text: "Send", onClick: send }} />);
    expect(container.querySelector(".action-bar")).not.toBeNull();
    getByRole("button", { name: "Send" }).click();
    expect(send).toHaveBeenCalledOnce();
    expect(main.show).not.toHaveBeenCalled();
  });
});
