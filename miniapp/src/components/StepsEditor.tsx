import { Plus, X } from "lucide-react";
import { useId, useLayoutEffect, useRef } from "react";

import { useI18n } from "../i18n";

const STEPS_MAX = 50;

let lastKey = 0;
const newKey = (): number => (lastKey += 1);

/**
 * Checklist steps for a new task: a line each, added and removed in place (the (+) sheet, and
 * each task the AI heard).
 *
 * The parent holds only the texts; each row's key is kept here beside them, so removing a middle
 * step leaves every other input (its text, its cursor, its focus, the phone's keyboard) where it
 * was. A row keyed by its position would hand the next step's text to the removed one's input.
 */
export function StepsEditor({ steps, onChange }: { steps: string[]; onChange: (steps: string[]) => void }) {
  const { t } = useI18n();
  const id = useId();
  const keys = useRef<number[]>([]);
  // One key per step, also when the parent changed the list itself (cleared, or filled in).
  if (keys.current.length !== steps.length) keys.current = steps.map((_, index) => keys.current[index] ?? newKey());
  const inputs = useRef(new Map<number, HTMLInputElement>());
  const rows = useRef(new Map<number, HTMLDivElement>());
  const addButton = useRef<HTMLButtonElement>(null);
  // Where focus goes after the row holding it was removed: the step that took its place, the one
  // before it, or "Add a step" when none is left.
  const focusAfter = useRef<number | "add" | null>(null);

  useLayoutEffect(() => {
    const target = focusAfter.current;
    if (target === null) return;
    focusAfter.current = null;
    (target === "add" ? addButton.current : inputs.current.get(target))?.focus();
  });

  const set = (index: number, text: string) => onChange(steps.map((step, at) => (at === index ? text : step)));
  const add = () => {
    keys.current = [...keys.current, newKey()];
    onChange([...steps, ""]);
  };
  const remove = (index: number) => {
    const removed = keys.current[index];
    const rest = keys.current.filter((_, at) => at !== index);
    if (removed !== undefined && rows.current.get(removed)?.contains(document.activeElement)) {
      focusAfter.current = rest[index] ?? rest[index - 1] ?? "add";
    }
    keys.current = rest;
    onChange(steps.filter((_, at) => at !== index));
  };

  return (
    <div className="field">
      <span className="field-label" id={`${id}-steps`}>{t("detail.checklist")}</span>
      <div className="plus-steps" role="group" aria-labelledby={`${id}-steps`}>
        {steps.map((step, index) => {
          const key = keys.current[index]!;
          return (
            <div
              key={key}
              className="plus-step"
              ref={(row) => {
                if (row) rows.current.set(key, row);
                else rows.current.delete(key);
              }}
            >
              <input
                ref={(input) => {
                  if (input) inputs.current.set(key, input);
                  else inputs.current.delete(key);
                }}
                className="input"
                value={step}
                maxLength={200}
                aria-label={t("add.step", { n: index + 1 })}
                placeholder={t("add.stepPlaceholder")}
                autoFocus={index === steps.length - 1 && !step}
                onChange={(event) => set(index, event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && step.trim() && steps.length < STEPS_MAX) add();
                }}
              />
              <button
                type="button"
                className="btn btn-ghost btn-icon plus-step-remove"
                aria-label={t("add.stepRemove", { n: index + 1 })}
                onClick={() => remove(index)}
              >
                <X size={18} strokeWidth={2.5} />
              </button>
            </div>
          );
        })}
        {steps.length < STEPS_MAX && (
          <button ref={addButton} type="button" className="btn btn-secondary plus-step-add" onClick={add}>
            <Plus size={17} strokeWidth={2.6} aria-hidden />
            <span>{t("add.stepAdd")}</span>
          </button>
        )}
      </div>
    </div>
  );
}
