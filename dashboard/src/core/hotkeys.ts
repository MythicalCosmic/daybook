/**
 * Keyboard shortcuts: one window listener, combos like "mod+k", "?", "[", "shift+n" and two-key
 * sequences like "g t". Letters are read from the physical key when the layout isn't Latin, so
 * ⌘K still works with a Russian or Uzbek Cyrillic keyboard.
 */
import { onBeforeUnmount, onMounted, shallowReactive } from "vue";

export type HotkeyGroup = "general" | "navigation" | "page";

export interface HotkeyOptions {
  /** i18n key describing the shortcut (listed in the shortcuts dialog when set). */
  description?: string;
  group?: HotkeyGroup;
  /** Fire while focus is in a text field (mod combos only make sense here). */
  allowInInputs?: boolean;
  /** Fire while a dialog, drawer or sheet is open. */
  allowInDialogs?: boolean;
  enabled?: () => boolean;
  /** Keep the browser's default action. */
  preventDefault?: boolean;
}

interface Stroke {
  key: string;
  mod: boolean;
  shift: boolean;
  alt: boolean;
}

interface Binding {
  id: number;
  combo: string;
  strokes: Stroke[];
  handler: (event: KeyboardEvent) => void;
  options: HotkeyOptions;
}

export interface RegisteredHotkey {
  id: number;
  combo: string;
  description: string;
  group: HotkeyGroup;
}

const SEQUENCE_TIMEOUT = 1000;
const bindings: Binding[] = [];
/** Shortcuts with a description, for the shortcuts dialog. */
export const registeredHotkeys = shallowReactive<RegisteredHotkey[]>([]);

let nextId = 1;
let listening = false;
let pending: { key: string; at: number } | null = null;

export function isMac(): boolean {
  if (typeof navigator === "undefined") return false;
  const platform = (navigator as Navigator & { userAgentData?: { platform?: string } }).userAgentData?.platform ?? navigator.platform;
  return /mac|iphone|ipad|ipod/i.test(platform);
}

export function parseCombo(combo: string): Stroke[] {
  return combo
    .trim()
    .split(/\s+/)
    .map((part) => {
      const keys = part === "+" ? ["+"] : part.split("+").map((k) => k.toLowerCase());
      const key = keys[keys.length - 1] ?? "";
      return {
        key: key === "space" ? " " : key,
        mod: keys.includes("mod"),
        shift: keys.includes("shift"),
        alt: keys.includes("alt"),
      };
    });
}

const CODE_KEYS: Record<string, [plain: string, shifted: string]> = {
  BracketLeft: ["[", "{"],
  BracketRight: ["]", "}"],
  Slash: ["/", "?"],
  Comma: [",", "<"],
  Period: [".", ">"],
  Semicolon: [";", ":"],
  Quote: ["'", '"'],
  Backquote: ["`", "~"],
  Minus: ["-", "_"],
  Equal: ["=", "+"],
};

/** The key as a US layout would name it: "k", "[", "?", "enter", "escape", "arrowdown". */
export function normalizeKey(event: Pick<KeyboardEvent, "key" | "code" | "shiftKey">): string {
  const key = event.key ?? "";
  if (key.length === 1 && /[\x20-\x7e]/.test(key)) return key.toLowerCase();
  if (key.length > 1) return key.toLowerCase();
  const code = event.code ?? "";
  if (/^Key[A-Z]$/.test(code)) return code.slice(3).toLowerCase();
  if (/^Digit\d$/.test(code)) return code.slice(5);
  const mapped = CODE_KEYS[code];
  if (mapped) return event.shiftKey ? mapped[1] : mapped[0];
  return key.toLowerCase();
}

/** The US-layout character of the physical key, for punctuation shortcuts on other layouts. */
function codeKey(event: Pick<KeyboardEvent, "code" | "shiftKey">): string | undefined {
  const mapped = CODE_KEYS[event.code ?? ""];
  return mapped ? (event.shiftKey ? mapped[1] : mapped[0]) : undefined;
}

/** Keys whose character already implies Shift ("?" is Shift+/), so the combo needn't say "shift". */
const SHIFTED_CHARS = new Set(["?", "{", "}", "<", ">", ":", '"', "~", "_", "+", "!", "@", "#", "$", "%", "^", "&", "*", "(", ")"]);

export function strokeMatches(stroke: Stroke, event: KeyboardEvent, mac = isMac()): boolean {
  const key = normalizeKey(event);
  // Punctuation ("?", "[") may sit elsewhere on a Russian layout: accept the physical US key too.
  if (key !== stroke.key && !(/^[^a-z0-9]$/.test(stroke.key) && codeKey(event) === stroke.key)) return false;
  const modPressed = mac ? event.metaKey : event.ctrlKey;
  const otherMod = mac ? event.ctrlKey : event.metaKey;
  if (stroke.mod !== modPressed || otherMod) return false;
  if (stroke.alt !== event.altKey) return false;
  if (!SHIFTED_CHARS.has(stroke.key) && stroke.shift !== event.shiftKey) return false;
  return true;
}

export function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  const tag = target.tagName;
  if (tag === "TEXTAREA" || tag === "SELECT") return true;
  if (tag !== "INPUT") return false;
  const type = (target as HTMLInputElement).type;
  return !["checkbox", "radio", "button", "submit", "reset", "range", "color", "file"].includes(type);
}

function overlayOpen(): boolean {
  return !!document.querySelector('[role="dialog"][data-state="open"], [role="alertdialog"][data-state="open"]');
}

function eligible(binding: Binding, event: KeyboardEvent, typing: boolean, inDialog: boolean): boolean {
  if (binding.options.enabled && !binding.options.enabled()) return false;
  if (typing && !binding.options.allowInInputs) return false;
  if (inDialog && !binding.options.allowInDialogs) return false;
  if (event.defaultPrevented && !binding.options.allowInDialogs) return false;
  return true;
}

function fire(binding: Binding, event: KeyboardEvent): void {
  if (binding.options.preventDefault !== false) event.preventDefault();
  binding.handler(event);
}

/**
 * The binding that answers: a page's own shortcut (`group: "page"`) before a shell-wide one with
 * the same keys, whichever registered last, so the Tasks page's N makes a task even though the top
 * bar's quick add (N for an expense) loads after the page; the newest first within each.
 */
function findBinding(matches: (binding: Binding) => boolean): Binding | undefined {
  return bindings.find((b) => b.options.group === "page" && matches(b)) ?? bindings.find((b) => b.options.group !== "page" && matches(b));
}

export function handleKeydown(event: KeyboardEvent): void {
  if (event.isComposing || event.repeat) return;
  const typing = isTypingTarget(event.target);
  const inDialog = overlayOpen();
  const now = Date.now();

  if (pending && now - pending.at <= SEQUENCE_TIMEOUT) {
    const first = pending.key;
    pending = null;
    const hit = findBinding(
      (b) => b.strokes.length === 2 && b.strokes[0]!.key === first && strokeMatches(b.strokes[1]!, event) && eligible(b, event, typing, inDialog),
    );
    if (hit) {
      fire(hit, event);
      return;
    }
  }
  pending = null;

  const single = findBinding((b) => b.strokes.length === 1 && strokeMatches(b.strokes[0]!, event) && eligible(b, event, typing, inDialog));
  if (single) {
    fire(single, event);
    return;
  }

  const startsSequence = bindings.some(
    (b) => b.strokes.length === 2 && strokeMatches(b.strokes[0]!, event) && eligible(b, event, typing, inDialog),
  );
  if (startsSequence) pending = { key: normalizeKey(event), at: now };
}

function ensureListening(): void {
  if (listening || typeof window === "undefined") return;
  window.addEventListener("keydown", handleKeydown);
  listening = true;
}

/** Registers a shortcut; returns the function that removes it. */
export function registerHotkey(combo: string, handler: (event: KeyboardEvent) => void, options: HotkeyOptions = {}): () => void {
  ensureListening();
  const binding: Binding = { id: nextId++, combo, strokes: parseCombo(combo), handler, options };
  bindings.unshift(binding); // the newest registration wins within its group; a page's beats a global (findBinding)
  if (options.description) {
    registeredHotkeys.push({ id: binding.id, combo, description: options.description, group: options.group ?? "page" });
  }
  return () => {
    const index = bindings.indexOf(binding);
    if (index >= 0) bindings.splice(index, 1);
    const listed = registeredHotkeys.findIndex((h) => h.id === binding.id);
    if (listed >= 0) registeredHotkeys.splice(listed, 1);
  };
}

/** `registerHotkey` tied to the calling component's lifetime. */
export function useHotkey(combo: string, handler: (event: KeyboardEvent) => void, options: HotkeyOptions = {}): void {
  let remove: (() => void) | null = null;
  onMounted(() => {
    remove = registerHotkey(combo, handler, options);
  });
  onBeforeUnmount(() => remove?.());
}

const MAC_SYMBOLS: Record<string, string> = { mod: "⌘", shift: "⇧", alt: "⌥", ctrl: "⌃" };
const PC_NAMES: Record<string, string> = { mod: "Ctrl", shift: "Shift", alt: "Alt", ctrl: "Ctrl" };
const KEY_NAMES: Record<string, string> = {
  enter: "↵",
  escape: "Esc",
  esc: "Esc",
  arrowup: "↑",
  arrowdown: "↓",
  arrowleft: "←",
  arrowright: "→",
  backspace: "⌫",
  tab: "Tab",
  " ": "Space",
  space: "Space",
};

/** Display labels for one key name: "mod" → "⌘" or "Ctrl", "k" → "K". */
export function keyLabel(key: string, mac = isMac()): string {
  const lower = key.toLowerCase();
  if (lower in MAC_SYMBOLS) return mac ? MAC_SYMBOLS[lower]! : PC_NAMES[lower]!;
  if (lower in KEY_NAMES) return KEY_NAMES[lower]!;
  return key.length === 1 ? key.toUpperCase() : key[0]!.toUpperCase() + key.slice(1);
}

/** "mod+shift+k" → ["⌘", "⇧", "K"]; "g t" → ["G", "T"]. */
export function formatCombo(combo: string, mac = isMac()): string[] {
  return combo
    .trim()
    .split(/\s+/)
    .flatMap((part) => (part === "+" ? ["+"] : part.split("+")))
    .map((key) => keyLabel(key, mac));
}

/** Test helper: forget every binding and pending sequence. */
export function resetHotkeys(): void {
  bindings.splice(0, bindings.length);
  registeredHotkeys.splice(0, registeredHotkeys.length);
  pending = null;
}
