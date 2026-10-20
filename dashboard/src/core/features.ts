/**
 * Per-company module switches (`Company.features`, plan §3.2): the only module switch. A module that
 * declares `feature` is hidden, with its routes, widgets and commands, while the company has the
 * switch off. Existing companies start with none on; the demo company has every one.
 * The §13 modules (projects, knowledge, calendar, CRM) are not switched.
 */
export const FEATURES = ["finance", "sales", "stock", "attendance", "hr", "payroll", "ai", "recognition"] as const;

export type CompanyFeature = (typeof FEATURES)[number];

export interface FeatureSubject {
  features: readonly string[];
}

export function hasFeature(subject: FeatureSubject | null | undefined, feature?: CompanyFeature): boolean {
  if (feature === undefined) return true;
  if (!subject) return false;
  return subject.features.includes(feature);
}
