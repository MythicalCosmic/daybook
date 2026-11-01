import { Plus, X } from "lucide-react";
import { useId } from "react";

import { useI18n } from "../i18n";

const STEPS_MAX = 50;

/**
 * Checklist steps for a new task: a line each, added and removed in place (the (+) sheet, and
 * each task the AI heard).
 */
export function StepsEditor({ steps, onChange }: { steps: string[]; onChange: (steps: string[]) => void }) {
  const { t } = useI18n();
  const id = useId();
  const set = (index: number, text: string) => onChange(steps.map((step, at) => (at === index ? text : step)));
  return (
    <div className="field">
      <span className="field-label" id={`${id}-steps`}>{t("detail.checklist")}</span>
      <div className="plus-steps" role="group" aria-labelledby={`${id}-steps`}>
        {steps.map((step, index) => (
          <div key={index} className="plus-step">
            <input
              className="input"
              value={step}
              maxLength={200}
              aria-label={t("add.step", { n: index + 1 })}
              placeholder={t("add.stepPlaceholder")}
              autoFocus={index === steps.length - 1 && !step}
              onChange={(event) => set(index, event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && step.trim() && steps.length < STEPS_MAX) onChange([...steps, ""]);
              }}
            />
            <button
              type="button"
              className="btn btn-ghost btn-icon plus-step-remove"
              aria-label={t("add.stepRemove", { n: index + 1 })}
              onClick={() => onChange(steps.filter((_, at) => at !== index))}
            >
              <X size={18} strokeWidth={2.5} />
            </button>
          </div>
        ))}
        {steps.length < STEPS_MAX && (
          <button type="button" className="btn btn-secondary plus-step-add" onClick={() => onChange([...steps, ""])}>
            <Plus size={17} strokeWidth={2.6} aria-hidden />
            <span>{t("add.stepAdd")}</span>
          </button>
        )}
      </div>
    </div>
  );
}
