import { useLayoutEffect, useRef, type ComponentPropsWithRef } from "react";

import { useI18n, type Lang } from "../i18n";
import { currencyLabel, formatTyping, sanitizeTyping, type Currency } from "../lib/money";
import { cx } from "./cx";
import { useFieldControl } from "./Field";

type Props = Omit<ComponentPropsWithRef<"input">, "value" | "onChange" | "type" | "size"> & {
  /** The typing state: digits, an optional "." and up to two decimals ("1250000", "35.5"). */
  value: string;
  onChange: (value: string) => void;
  currency?: Currency | string;
  /** Allow tiyin/cents; on by default for dollars only. */
  decimals?: boolean;
  maxDigits?: number;
  size?: "md" | "lg";
  invalid?: boolean;
};

/** Characters the person typed (digits and the decimal point), as opposed to grouping. */
const typed = (lang: Lang) => (lang === "en" ? /[\d.]/ : /[\d.,]/);

/** How many typed characters sit before `caret`, so the caret can return there after regrouping. */
function typedBefore(text: string, caret: number, lang: Lang): number {
  const pattern = typed(lang);
  return [...text.slice(0, caret)].filter((char) => pattern.test(char)).length;
}

function caretAfter(display: string, count: number, lang: Lang): number {
  if (count <= 0) return 0;
  const pattern = typed(lang);
  let seen = 0;
  for (let index = 0; index < display.length; index += 1) {
    if (pattern.test(display[index])) seen += 1;
    if (seen >= count) return index + 1;
  }
  return display.length;
}

/**
 * A money field that groups digits as you type ("1 250 000") and shows the currency inside the
 * pill. `value`/`onChange` carry the plain typing state; `amountFromTyping` turns it into an
 * amount for the API.
 */
export function MoneyInput({
  value,
  onChange,
  currency = "UZS",
  decimals,
  maxDigits,
  size = "md",
  invalid,
  className,
  id,
  placeholder = "0",
  ...rest
}: Props) {
  const { lang } = useI18n();
  const control = useFieldControl({ id, invalid });
  const input = useRef<HTMLInputElement | null>(null);
  const caret = useRef<number | null>(null);
  const allowDecimals = decimals ?? currency === "USD";
  const display = formatTyping(value, lang);

  useLayoutEffect(() => {
    if (caret.current === null || !input.current || document.activeElement !== input.current) return;
    input.current.setSelectionRange(caret.current, caret.current);
    caret.current = null;
  });

  return (
    <div className={cx("ui-money-input", size === "lg" && "ui-money-input--lg", className)}>
      <input
        ref={input}
        className="input num"
        inputMode={allowDecimals ? "decimal" : "numeric"}
        autoComplete="off"
        placeholder={placeholder}
        value={display}
        {...control}
        {...rest}
        onChange={(event) => {
          const raw = event.target.value;
          const count = typedBefore(raw, event.target.selectionStart ?? raw.length, lang);
          const next = sanitizeTyping(raw, lang, { decimals: allowDecimals, maxDigits });
          caret.current = caretAfter(formatTyping(next, lang), count, lang);
          onChange(next);
        }}
      />
      <span className="ui-money-suffix" aria-hidden>
        {currencyLabel(currency, lang)}
      </span>
    </div>
  );
}
