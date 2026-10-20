/**
 * Wiring between FormField and the control inside it: the control takes the field's id (so the
 * label points at it), `aria-describedby` (hint and error) and the invalid/disabled state, without
 * the page passing them twice. A control used on its own falls back to its own props.
 */
import { computed, inject, provide, useId, type ComputedRef, type InjectionKey } from "vue";

export interface FieldContext {
  id: string;
  describedBy: ComputedRef<string | undefined>;
  invalid: ComputedRef<boolean>;
  disabled: ComputedRef<boolean>;
  required: ComputedRef<boolean>;
  /** Id of the visible label, for controls that are not labelable elements (button triggers, groups). */
  labelId: string;
}

const FIELD_KEY: InjectionKey<FieldContext> = Symbol("ui-field");

export function provideField(context: FieldContext): void {
  provide(FIELD_KEY, context);
}

export interface ControlProps {
  id?: string;
  invalid?: boolean;
  disabled?: boolean;
}

/** The ids and state a control renders with, merged from its FormField (if any) and its own props. */
export function useControl(props: ControlProps) {
  const field = inject(FIELD_KEY, null);
  const ownId = useId();
  const id = computed(() => props.id ?? field?.id ?? ownId);
  return {
    field,
    id,
    labelId: computed(() => field?.labelId),
    describedBy: computed(() => field?.describedBy.value),
    invalid: computed(() => !!props.invalid || !!field?.invalid.value),
    disabled: computed(() => !!props.disabled || !!field?.disabled.value),
    required: computed(() => !!field?.required.value),
  };
}

/** Data attributes for `.ui-control` (styles in styles/controls.css). */
export function controlState(state: { invalid?: boolean; disabled?: boolean; readonly?: boolean; focused?: boolean }) {
  return {
    "data-invalid": state.invalid ? "" : undefined,
    "data-disabled": state.disabled ? "" : undefined,
    "data-readonly": state.readonly ? "" : undefined,
    "data-focused": state.focused ? "" : undefined,
  };
}

export type ControlSize = "sm" | "md" | "lg";

export const controlSizeClass: Record<ControlSize, string> = { sm: "ui-control-sm", md: "", lg: "ui-control-lg" };

/** Icon size that fits each control size. */
export const controlIconSize: Record<ControlSize, number> = { sm: 14, md: 16, lg: 18 };
