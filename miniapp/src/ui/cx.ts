type ClassPart = string | boolean | number | bigint | null | undefined;

/** Join class names, skipping everything that isn't a non-empty string: cx("btn", primary && "btn-primary"). */
export function cx(...parts: ClassPart[]): string {
  return parts.filter((part): part is string => typeof part === "string" && part !== "").join(" ");
}
