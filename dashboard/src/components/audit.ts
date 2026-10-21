/**
 * Audit details in a chosen order. Postgres stores JSON keys shortest first, so a row's details
 * come back as `{last_day, first_day}`; `AuditTrail`'s `field-order` (and other history lists)
 * put them back. Fields `order` names come first, in its order; the rest keep theirs.
 */
export function inFieldOrder<T>(entries: Array<[string, T]>, order: readonly string[]): Array<[string, T]> {
  if (!order.length) return entries;
  const rank = (field: string) => {
    const index = order.indexOf(field);
    return index === -1 ? order.length : index;
  };
  // Array.prototype.sort is stable, so unnamed fields keep the order they came in.
  return [...entries].sort((a, b) => rank(a[0]) - rank(b[0]));
}
