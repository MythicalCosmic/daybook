/** The HR feature's translator and the wording its screens share. */
import { Award, BookUser, FileText, GraduationCap, IdCard, Stethoscope, type LucideIcon } from "lucide-react";

import { useFeatureT, type FeatureTranslate } from "../../i18n/feature";
import type { DocumentKind, HrDocument } from "./api";
import { messages } from "./messages";

export type HrKey = keyof typeof messages.en;
export type HrT = FeatureTranslate<HrKey>;

export const useHrT = (): HrT => useFeatureT(messages);

export const kindLabel = (t: HrT, kind: DocumentKind | string): string => t(`kind.${kind}` as HrKey);

/** A document's name: its kind, and its own title when it has one ("Other: Driving licence"). */
export const documentName = (t: HrT, document: Pick<HrDocument, "kind" | "title">): string =>
  document.title ? `${kindLabel(t, document.kind)}: ${document.title}` : kindLabel(t, document.kind);

/** Where a document stands, in a word or two ("12 days left"). */
export function stateLabel(t: HrT, document: Pick<HrDocument, "state" | "days_left">): string {
  if (document.state === "expiring") return t("state.expiring", { count: Math.max(0, document.days_left ?? 0) });
  return t(`state.${document.state}` as HrKey);
}

const ICONS: Partial<Record<DocumentKind, LucideIcon>> = {
  passport: IdCard,
  id_card: IdCard,
  military_id: IdCard,
  diploma: GraduationCap,
  pharmacy_diploma: GraduationCap,
  medical_diploma: GraduationCap,
  pharmacist_certificate: Award,
  qualification_category: Award,
  state_registration: Award,
  medical_book: Stethoscope,
  medical_exam: Stethoscope,
  work_book: BookUser,
};

export const kindIcon = (kind: DocumentKind): LucideIcon => ICONS[kind] ?? FileText;

/** "••••••••••••4242" → "•••• 4242": the server masks; this only shortens the dots. */
export const shortMask = (masked: string): string => masked.replace(/•{4,}/, "•••• ");
