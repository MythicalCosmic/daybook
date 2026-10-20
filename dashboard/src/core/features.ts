/**
 * Per-company module switches (`Company.features`, plan §3.2). A module that declares `feature` is
 * hidden, with its routes, widgets and commands, while the company has the switch off.
 *
 * §3.2 defines finance, sales, stock, attendance, hr, payroll and ai. The §13 modules (projects,
 * knowledge, calendar, CRM) are listed so their packages can opt in; until the backend adds those
 * switches the catalog does not tie any module to them (see core/catalog.ts).
 */
export const FEATURES = [
  "finance",
  "sales",
  "stock",
  "attendance",
  "hr",
  "payroll",
  "ai",
  "projects",
  "knowledge",
  "calendar",
  "crm",
] as const;

export type CompanyFeature = (typeof FEATURES)[number];

export interface FeatureSubject {
  features: readonly string[];
}

export function hasFeature(subject: FeatureSubject | null | undefined, feature?: CompanyFeature): boolean {
  if (feature === undefined) return true;
  if (!subject) return false;
  return subject.features.includes(feature);
}
