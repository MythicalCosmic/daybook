import { describe, expect, it, vi } from "vitest";
import { z } from "zod";

import { ApiError } from "@/api/http";
import { i18n } from "@/i18n";
import { useForm, zodErrors } from "@/lib/useForm";

const schema = z.object({
  name: z.string().trim().min(1, "common.form.required"),
  amount: z.string().regex(/^\d+(\.\d{1,2})?$/, "Enter an amount like 1250000.00"),
});

describe("useForm", () => {
  it("validates with zod and translates i18n-key messages", () => {
    i18n.global.locale.value = "en";
    const form = useForm(schema, { name: "", amount: "12,5" });
    expect(form.validate()).toBeNull();
    expect(form.errors.name).toBe("Required");
    expect(form.errors.amount).toBe("Enter an amount like 1250000.00");
  });

  it("submits parsed values, tracks dirty state and resets", async () => {
    const onSubmit = vi.fn();
    const form = useForm(schema, { name: "Rent", amount: "100" }, { onSubmit });
    expect(form.dirty.value).toBe(false);
    form.values.name = "  Rent October  ";
    expect(form.dirty.value).toBe(true);
    await expect(form.submit()).resolves.toBe(true);
    expect(onSubmit).toHaveBeenCalledWith({ name: "Rent October", amount: "100" });
    expect(form.dirty.value).toBe(false);
    form.values.amount = "5";
    form.reset();
    expect(form.values.amount).toBe("100");
    expect(form.submitCount.value).toBe(0);
  });

  it("puts server field errors on the fields and detail in formError", async () => {
    const form = useForm(schema, { name: "Rent", amount: "100" }, {
      onSubmit: () => {
        throw new ApiError(400, { amount: ["The period is locked."], detail: "Check the fields." });
      },
    });
    await expect(form.submit()).resolves.toBe(false);
    expect(form.errors.amount).toBe("The period is locked.");
    expect(form.formError.value).toBe("Check the fields.");
    expect(form.submitting.value).toBe(false);
  });

  it("maps non_field_errors to formError", () => {
    const form = useForm(schema, { name: "a", amount: "1" });
    form.setErrors({ non_field_errors: ["Nobody approves their own claim."] });
    expect(form.formError.value).toBe("Nobody approves their own claim.");
  });

  it("validates one field on blur", () => {
    i18n.global.locale.value = "ru";
    const form = useForm(schema, { name: "", amount: "1" });
    form.touch("name");
    expect(form.touched.name).toBe(true);
    expect(form.errors.name).toBe("Обязательное поле");
    expect(form.errors.amount).toBeUndefined();
    i18n.global.locale.value = "en";
  });

  it("rethrows errors that aren't API errors", async () => {
    const form = useForm(schema, { name: "a", amount: "1" }, {
      onSubmit: () => {
        throw new TypeError("bug");
      },
    });
    await expect(form.submit()).rejects.toThrow("bug");
  });

  it("joins nested paths", () => {
    const nested = z.object({ lines: z.array(z.object({ qty: z.number().positive("bad") })) });
    const result = nested.safeParse({ lines: [{ qty: 1 }, { qty: -1 }] });
    expect(result.success).toBe(false);
    if (!result.success) expect(zodErrors(result.error)).toEqual({ "lines.1.qty": "bad" });
  });
});
