import { Delete } from "lucide-react";
import { useEffect, useRef, type KeyboardEvent, type ReactNode } from "react";

import { useI18n } from "../i18n";
import { currencyLabel, decimalPoint, formatTyping, type Currency } from "../lib/money";
import { haptic } from "../telegram";
import { cx } from "./cx";

export type PadKey = "0" | "1" | "2" | "3" | "4" | "5" | "6" | "7" | "8" | "9" | "000" | "." | "back";

/**
 * What a key press does to the typing state ("1250000", "35.5"). Pure, so the keypad and tests
 * agree: no leading zeros, at most two decimals, `000` only after a non-zero digit.
 */
export function pressKey(value: string, key: PadKey, options: { decimals?: boolean; maxDigits?: number } = {}): string {
  const maxDigits = options.maxDigits ?? 12;
  const [whole, fraction] = value.split(".");
  if (key === "back") return value.slice(0, -1);
  if (key === ".") {
    if (!options.decimals || fraction !== undefined) return value;
    return `${whole || "0"}.`;
  }
  if (fraction !== undefined) {
    if (key === "000" || fraction.length >= 2) return value;
    return `${value}${key}`;
  }
  if (key === "000") {
    if (!whole || whole === "0") return value;
    return whole.length + 3 <= maxDigits ? `${whole}000` : value;
  }
  if (whole === "0") return key;
  return whole.length < maxDigits ? `${whole}${key}` : value;
}

/** The pad key a physical keyboard key stands for (desktop Telegram), or null. */
export function keyFromKeyboard(key: string, decimals: boolean): PadKey | null {
  if (/^[0-9]$/.test(key)) return key as PadKey;
  if (key === "Backspace" || key === "Delete") return "back";
  if (decimals && (key === "." || key === ",")) return ".";
  return null;
}

/**
 * The big on-screen keypad for amounts (closing the till, an expense, an advance): the grouped
 * amount on top and a 000 key, because UZS amounts end in zeros. Holding ⌫ clears. On desktop,
 * the number keys and Backspace type into it once one of its keys has focus.
 */
export function NumberPad({
  value,
  onChange,
  currency = "UZS",
  decimals,
  maxDigits = 12,
  label,
  hint,
}: {
  value: string;
  onChange: (value: string) => void;
  currency?: Currency | string;
  /** Show a decimal key instead of 000; on by default for dollars. */
  decimals?: boolean;
  maxDigits?: number;
  /** What the amount is ("Cash in the drawer"). */
  label?: ReactNode;
  /** A line under the amount (the expected total, a limit). */
  hint?: ReactNode;
}) {
  const { t, lang } = useI18n();
  const allowDecimals = decimals ?? currency === "USD";
  const latest = useRef(value);
  latest.current = value;
  const clearTimer = useRef<number | undefined>(undefined);
  const cleared = useRef(false);
  useEffect(() => () => window.clearTimeout(clearTimer.current), []);

  const press = (key: PadKey) => {
    const next = pressKey(latest.current, key, { decimals: allowDecimals, maxDigits });
    if (next === latest.current) {
      haptic.notify("warning");
      return;
    }
    haptic.select();
    latest.current = next;
    onChange(next);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.altKey || event.ctrlKey || event.metaKey) return;
    const key = keyFromKeyboard(event.key, allowDecimals);
    if (!key) return;
    event.preventDefault();
    if (key === "back" && !latest.current) return;
    press(key);
  };

  const keys: PadKey[] = ["1", "2", "3", "4", "5", "6", "7", "8", "9", allowDecimals ? "." : "000", "0", "back"];
  const unit = currencyLabel(currency, lang);
  const empty = !value;

  return (
    <div className="ui-numpad" onKeyDown={onKeyDown}>
      <div className="ui-numpad-display">
        {label && <div className="ui-numpad-label">{label}</div>}
        <div className={cx("ui-numpad-amount", empty && "ui-numpad-amount--empty")} aria-live="polite">
          <span className="heading num">{empty ? "0" : formatTyping(value, lang)}</span>
          <span className="ui-numpad-unit">{unit}</span>
        </div>
        {hint && <div className="ui-numpad-hint">{hint}</div>}
      </div>
      <div className="ui-numpad-keys">
        {keys.map((key) =>
          key === "back" ? (
            <button
              key={key}
              type="button"
              className="ui-key ui-key--action"
              aria-label={t("ui.numpad.delete")}
              disabled={empty}
              onClick={() => {
                // The click that ends a long press has already cleared everything.
                if (cleared.current) cleared.current = false;
                else press("back");
              }}
              onPointerDown={() => {
                cleared.current = false;
                clearTimer.current = window.setTimeout(() => {
                  if (!latest.current) return;
                  cleared.current = true;
                  haptic.impact("medium");
                  latest.current = "";
                  onChange("");
                }, 600);
              }}
              onPointerUp={() => window.clearTimeout(clearTimer.current)}
              onPointerLeave={() => window.clearTimeout(clearTimer.current)}
              onPointerCancel={() => window.clearTimeout(clearTimer.current)}
            >
              <Delete size={24} strokeWidth={2.2} aria-hidden />
            </button>
          ) : (
            <button key={key} type="button" className={cx("ui-key", key === "000" && "ui-key--small")} onClick={() => press(key)}>
              {key === "." ? decimalPoint(lang) : key}
            </button>
          ),
        )}
      </div>
    </div>
  );
}
