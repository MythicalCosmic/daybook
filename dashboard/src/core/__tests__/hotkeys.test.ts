import { afterEach, describe, expect, it, vi } from "vitest";

import { formatCombo, handleKeydown, isTypingTarget, keyLabel, normalizeKey, parseCombo, registerHotkey, registeredHotkeys, resetHotkeys } from "@/core/hotkeys";

function press(key: string, init: KeyboardEventInit = {}, target: EventTarget = document.body): KeyboardEvent {
  const event = new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true, ...init });
  Object.defineProperty(event, "target", { value: target });
  handleKeydown(event);
  return event;
}

afterEach(() => {
  resetHotkeys();
  vi.useRealTimers();
  document.body.innerHTML = "";
});

describe("parsing and display", () => {
  it("parses combos and sequences", () => {
    expect(parseCombo("mod+k")).toEqual([{ key: "k", mod: true, shift: false, alt: false }]);
    expect(parseCombo("g t")).toHaveLength(2);
    expect(parseCombo("shift+?")[0]).toMatchObject({ key: "?", shift: true });
  });

  it("reads letters from the physical key on a Cyrillic layout", () => {
    expect(normalizeKey({ key: "л", code: "KeyK", shiftKey: false })).toBe("k");
    expect(normalizeKey({ key: "х", code: "BracketLeft", shiftKey: false })).toBe("[");
    expect(normalizeKey({ key: "K", code: "KeyK", shiftKey: true })).toBe("k");
    expect(normalizeKey({ key: "Enter", code: "Enter", shiftKey: false })).toBe("enter");
  });

  it("labels keys for Mac and PC", () => {
    expect(formatCombo("mod+shift+k", true)).toEqual(["⌘", "⇧", "K"]);
    expect(formatCombo("mod+k", false)).toEqual(["Ctrl", "K"]);
    expect(formatCombo("g t", false)).toEqual(["G", "T"]);
    expect(keyLabel("esc", false)).toBe("Esc");
    expect(keyLabel("arrowdown", false)).toBe("↓");
  });

  it("knows when someone is typing", () => {
    const input = document.createElement("input");
    const checkbox = Object.assign(document.createElement("input"), { type: "checkbox" });
    const editable = document.createElement("div");
    editable.contentEditable = "true";
    Object.defineProperty(editable, "isContentEditable", { value: true });
    expect(isTypingTarget(input)).toBe(true);
    expect(isTypingTarget(checkbox)).toBe(false);
    expect(isTypingTarget(editable)).toBe(true);
    expect(isTypingTarget(document.body)).toBe(false);
  });
});

describe("dispatch", () => {
  it("fires mod combos with Ctrl off a Mac, even from a text field when allowed", () => {
    const open = vi.fn();
    registerHotkey("mod+k", open, { allowInInputs: true });
    press("k", { ctrlKey: true });
    press("k", { ctrlKey: true }, document.createElement("input"));
    press("k");
    expect(open).toHaveBeenCalledTimes(2);
  });

  it("ignores plain keys while typing", () => {
    const help = vi.fn();
    registerHotkey("?", help);
    press("?", { shiftKey: true }, document.createElement("textarea"));
    expect(help).not.toHaveBeenCalled();
    press("?", { shiftKey: true });
    expect(help).toHaveBeenCalledTimes(1);
  });

  it("matches punctuation by the physical key on other layouts", () => {
    const help = vi.fn();
    registerHotkey("?", help);
    press(",", { shiftKey: true, code: "Slash" });
    expect(help).toHaveBeenCalledTimes(1);
  });

  it("runs two-key sequences within a second", () => {
    vi.useFakeTimers();
    const go = vi.fn();
    registerHotkey("g t", go);
    press("g");
    press("t");
    expect(go).toHaveBeenCalledTimes(1);
    press("g");
    vi.advanceTimersByTime(1100);
    press("t");
    expect(go).toHaveBeenCalledTimes(1);
  });

  it("stays quiet while a dialog is open unless allowed", () => {
    const page = vi.fn();
    const palette = vi.fn();
    registerHotkey("n", page);
    registerHotkey("mod+k", palette, { allowInDialogs: true });
    document.body.innerHTML = '<div role="dialog" data-state="open"></div>';
    press("n");
    press("k", { ctrlKey: true });
    expect(page).not.toHaveBeenCalled();
    expect(palette).toHaveBeenCalledTimes(1);
  });

  it("lets the newest registration win and cleans up", () => {
    const global = vi.fn();
    const local = vi.fn();
    registerHotkey("n", global);
    const remove = registerHotkey("n", local, { description: "tasks.new", group: "page" });
    expect(registeredHotkeys.map((h) => h.description)).toEqual(["tasks.new"]);
    press("n");
    expect(local).toHaveBeenCalledTimes(1);
    expect(global).not.toHaveBeenCalled();
    remove();
    press("n");
    expect(global).toHaveBeenCalledTimes(1);
    expect(registeredHotkeys).toHaveLength(0);
  });

  it("respects enabled() and prevents the browser default", () => {
    let on = false;
    const toggle = vi.fn();
    registerHotkey("[", toggle, { enabled: () => on });
    press("[");
    on = true;
    const event = press("[");
    expect(toggle).toHaveBeenCalledTimes(1);
    expect(event.defaultPrevented).toBe(true);
  });
});
