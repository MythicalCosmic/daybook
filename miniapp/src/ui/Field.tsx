import { ChevronDown } from "lucide-react";
import { createContext, useContext, useId, type ComponentPropsWithRef, type ReactNode } from "react";

import { useI18n } from "../i18n";
import { cx } from "./cx";

type FieldState = { id: string; describedBy?: string; invalid: boolean };

const FieldContext = createContext<FieldState | null>(null);

/**
 * A labelled form row. The control inside (Input, Textarea, Select, MoneyInput) picks up the id,
 * the hint or error description and the invalid state on its own.
 */
export function Field({
  label,
  hint,
  error,
  optional = false,
  id,
  className,
  children,
}: {
  label?: ReactNode;
  hint?: ReactNode;
  /** Replaces the hint and marks the control invalid. */
  error?: ReactNode;
  /** Adds "(optional)" after the label. */
  optional?: boolean;
  id?: string;
  className?: string;
  children: ReactNode;
}) {
  const { t } = useI18n();
  const generated = useId();
  const controlId = id ?? generated;
  const hintId = `${controlId}-hint`;
  const errorId = `${controlId}-error`;
  const state: FieldState = {
    id: controlId,
    describedBy: error ? errorId : hint ? hintId : undefined,
    invalid: Boolean(error),
  };
  return (
    <div className={cx("field", className)}>
      {label && (
        <label htmlFor={controlId}>
          {label}
          {optional && <span className="ui-field-optional"> {t("ui.optional")}</span>}
        </label>
      )}
      <FieldContext.Provider value={state}>{children}</FieldContext.Provider>
      {error ? (
        <div className="ui-field-error" id={errorId} role="alert">
          {error}
        </div>
      ) : hint ? (
        <div className="ui-field-hint" id={hintId}>
          {hint}
        </div>
      ) : null}
    </div>
  );
}

/** The id and ARIA wiring a control inside a Field should carry. */
export function useFieldControl(own: { id?: string; invalid?: boolean } = {}) {
  const field = useContext(FieldContext);
  const invalid = own.invalid ?? field?.invalid ?? false;
  return {
    id: own.id ?? field?.id,
    "aria-describedby": field?.describedBy,
    "aria-invalid": invalid || undefined,
  };
}

type InputProps = ComponentPropsWithRef<"input"> & { invalid?: boolean; num?: boolean };

/** The pill text input (`.input`). `num` uses tabular figures. */
export function Input({ className, invalid, num, id, ...rest }: InputProps) {
  const control = useFieldControl({ id, invalid });
  return <input className={cx("input", num && "num", className)} {...control} {...rest} />;
}

type TextareaProps = ComponentPropsWithRef<"textarea"> & { invalid?: boolean };

export function Textarea({ className, invalid, id, ...rest }: TextareaProps) {
  const control = useFieldControl({ id, invalid });
  return <textarea className={cx("input", className)} {...control} {...rest} />;
}

type SelectProps = ComponentPropsWithRef<"select"> & { invalid?: boolean };

/** A native select in the pill style, with a chevron so it reads as a choice. */
export function Select({ className, invalid, id, ...rest }: SelectProps) {
  const control = useFieldControl({ id, invalid });
  return (
    <div className="ui-select">
      <select className={cx("input", className)} {...control} {...rest} />
      <ChevronDown className="ui-select-chevron" size={18} strokeWidth={2.5} aria-hidden />
    </div>
  );
}
