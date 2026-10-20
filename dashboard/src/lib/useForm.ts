/**
 * Forms with zod 4 and no form library (plan §6.4): field errors, server error mapping, dirty
 * tracking and submit state.
 *
 *   const form = useForm(schema, { name: "" }, { onSubmit: (values) => api.create(cid, values) });
 *   <TextInput v-model="form.values.name" :error="form.errors.name" @blur="form.touch('name')" />
 *   <UiButton :loading="form.submitting.value" @click="form.submit">Save</UiButton>
 *
 * Schema messages may be i18n keys (`z.string().min(1, "common.form.required")`); they are
 * translated when shown. A 400 from the server lands on the same fields; `{detail}` becomes
 * `formError` (the HTTP layer already toasts it for writes unless the call passed `toast: false`).
 */
import { computed, reactive, ref, shallowRef, toRaw, type ComputedRef, type Ref } from "vue";
import type { z } from "zod";

import { isApiError, type FieldErrors } from "@/api/http";
import { i18n } from "@/i18n";

export type FormErrors = Record<string, string | undefined>;

export interface UseFormOptions<Out> {
  onSubmit?: (values: Out) => unknown | Promise<unknown>;
  /** Validate a field as soon as it changes after its first blur. Default true. */
  validateOnChange?: boolean;
}

export interface UseForm<In extends Record<string, unknown>, Out> {
  values: In;
  errors: FormErrors;
  formError: Ref<string | null>;
  submitting: Ref<boolean>;
  submitCount: Ref<number>;
  dirty: ComputedRef<boolean>;
  touched: Record<string, boolean>;
  validate: () => Out | null;
  touch: (field: keyof In & string) => void;
  submit: (event?: Event) => Promise<boolean>;
  reset: (next?: Partial<In>) => void;
  setErrors: (errors: FieldErrors | FormErrors) => void;
}

function translate(message: string): string {
  const looksLikeKey = /^[a-z][\w-]*(\.[\w-]+)+$/i.test(message);
  return looksLikeKey && i18n.global.te(message) ? i18n.global.t(message) : message;
}

function clone<T>(value: T): T {
  return structuredClone(toRaw(value));
}

/** A comparable fingerprint of form values; files and dates compare by identity-ish fields. */
function snapshot(value: unknown): string {
  return JSON.stringify(value, (_key, item: unknown) => {
    if (typeof File !== "undefined" && item instanceof File) return `file:${item.name}:${item.size}:${item.lastModified}`;
    if (item instanceof Date) return `date:${item.toISOString()}`;
    return item;
  });
}

/** First message per dotted path from a zod error. */
export function zodErrors(error: z.ZodError): FormErrors {
  const out: FormErrors = {};
  for (const issue of error.issues) {
    const key = issue.path.map(String).join(".") || "_form";
    out[key] ??= translate(issue.message);
  }
  return out;
}

export function useForm<S extends z.ZodType, In extends Record<string, unknown> = z.input<S> & Record<string, unknown>>(
  schema: S,
  initial: In,
  options: UseFormOptions<z.output<S>> = {},
): UseForm<In, z.output<S>> {
  // The last saved values: kept as a copy (for reset) and as a fingerprint (for dirty).
  const saved = shallowRef(clone(initial));
  const baseline = computed(() => snapshot(saved.value));
  const values = reactive(clone(initial)) as In;
  const errors = reactive<FormErrors>({});
  const touched = reactive<Record<string, boolean>>({});
  const formError = ref<string | null>(null);
  const submitting = ref(false);
  const submitCount = ref(0);

  // Reading through the reactive proxy (not toRaw) so the comparison tracks every field.
  const dirty = computed(() => snapshot(values) !== baseline.value);

  function clearErrors(): void {
    for (const key of Object.keys(errors)) delete errors[key];
    formError.value = null;
  }

  function setErrors(next: FieldErrors | FormErrors): void {
    for (const [key, value] of Object.entries(next)) {
      const message = Array.isArray(value) ? value[0] : value;
      if (key === "non_field_errors" || key === "_form") formError.value = message ? translate(message) : null;
      else errors[key] = message ? translate(message) : undefined;
    }
  }

  function validate(): z.output<S> | null {
    const result = schema.safeParse(toRaw(values));
    clearErrors();
    if (result.success) return result.data;
    setErrors(zodErrors(result.error));
    return null;
  }

  function touch(field: string): void {
    touched[field] = true;
    if (options.validateOnChange === false) return;
    const result = schema.safeParse(toRaw(values));
    const fieldErrors = result.success ? {} : zodErrors(result.error);
    errors[field] = fieldErrors[field];
  }

  async function submit(event?: Event): Promise<boolean> {
    event?.preventDefault();
    if (submitting.value) return false;
    submitCount.value += 1;
    const parsed = validate();
    if (parsed === null) return false;
    if (!options.onSubmit) return true;
    submitting.value = true;
    try {
      await options.onSubmit(parsed);
      saved.value = clone(values);
      return true;
    } catch (error) {
      if (isApiError(error)) {
        setErrors(error.fieldErrors);
        if (error.detail) formError.value = error.detail;
      } else {
        throw error;
      }
      return false;
    } finally {
      submitting.value = false;
    }
  }

  function reset(next?: Partial<In>): void {
    saved.value = { ...clone(saved.value), ...(next ?? {}) } as In;
    for (const key of Object.keys(values)) delete (values as Record<string, unknown>)[key];
    Object.assign(values, clone(saved.value));
    for (const key of Object.keys(touched)) delete touched[key];
    clearErrors();
    submitCount.value = 0;
  }

  return { values, errors, formError, submitting, submitCount, dirty, touched, validate, touch, submit, reset, setErrors };
}
