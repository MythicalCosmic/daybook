/**
 * What "Hujjatlarim" works out without React: the profile form (what changed, what is wrong),
 * an emergency contact's checks, which document needs the person, and the upload's checks.
 * The server checks everything again; these only keep the person from a pointless round trip.
 */
import type { ContactDraft, DocumentKind, DocumentUpload, HrDocument, Profile, ProfileChanges } from "./api";

// — my details —

export type ProfileForm = { phone: string; email: string; city: string; address: string; showBirthday: boolean; card: string };

export function profileForm(profile: Profile): ProfileForm {
  return {
    phone: profile.personal_phone,
    email: profile.email,
    city: profile.city,
    address: profile.address,
    showBirthday: profile.show_birthday,
    // The card comes back masked: the field is for a new number only.
    card: "",
  };
}

/** "+998 90 123 45 67" as people write it (the server's rule): 7 digits at least. */
export function phoneOk(text: string): boolean {
  const value = text.trim();
  return /^\+?[\d ()-]{7,20}$/.test(value) && value.replace(/\D/g, "").length >= 7;
}

const emailOk = (text: string) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(text.trim());

/** A card's digits as typed, grouped by four: "8600 1234 5678 9012". */
export function cardTyping(raw: string): string {
  return raw
    .replace(/\D/g, "")
    .slice(0, 19)
    .replace(/(\d{4})(?=\d)/g, "$1 ");
}

export type ProfileProblem = "phone" | "email" | "card";

/** The fields that changed, as the server takes them, and which ones are wrong. */
export function profileChanges(form: ProfileForm, profile: Profile): { changes: ProfileChanges; problems: ProfileProblem[] } {
  const changes: ProfileChanges = {};
  const problems: ProfileProblem[] = [];
  const phone = form.phone.trim();
  const email = form.email.trim();
  const card = form.card.replace(/\D/g, "");
  if (phone && !phoneOk(phone)) problems.push("phone");
  if (email && !emailOk(email)) problems.push("email");
  if (card && (card.length < 16 || card.length > 19)) problems.push("card");
  if (phone !== profile.personal_phone) changes.personal_phone = phone;
  if (email !== profile.email) changes.email = email;
  if (form.city.trim() !== profile.city) changes.city = form.city.trim();
  if (form.address.trim() !== profile.address) changes.address = form.address.trim();
  if (form.showBirthday !== profile.show_birthday) changes.show_birthday = form.showBirthday;
  if (card) changes.payout_card = card;
  return { changes, problems };
}

// — emergency contacts —

export const MAX_CONTACTS = 3;

export type ContactProblem = "name" | "phone";

export function contactDraft(input: { name: string; relation: string; phone: string }): { draft: ContactDraft } | { problems: ContactProblem[] } {
  const name = input.name.trim().replace(/\s+/g, " ");
  const phone = input.phone.trim();
  const problems: ContactProblem[] = [];
  if (!name) problems.push("name");
  if (!phoneOk(phone)) problems.push("phone");
  if (problems.length) return { problems };
  return { draft: { name, relation: input.relation.trim(), phone } };
}

// — documents —

/** Documents that need the person: expired, then expiring, the soonest first. */
export function needingAttention(documents: readonly HrDocument[] | undefined): HrDocument[] {
  const rank = (document: HrDocument) => (document.state === "expired" ? 0 : 1);
  return (documents ?? [])
    .filter((document) => document.state === "expired" || document.state === "expiring")
    .sort((a, b) => rank(a) - rank(b) || (a.days_left ?? 0) - (b.days_left ?? 0));
}

/** The kinds offered for an upload: what a pharmacy asks for most, first. */
export const UPLOAD_KINDS: readonly DocumentKind[] = [
  "medical_book",
  "medical_exam",
  "pharmacist_certificate",
  "qualification_category",
  "pharmacy_diploma",
  "medical_diploma",
  "diploma",
  "state_registration",
  "work_book",
  "passport",
  "id_card",
  "military_id",
  "nda",
  "photo",
  "other",
];

export type UploadForm = { kind: DocumentKind; file: File | null; number: string; expires: string | null };

/** The upload as the API takes it, or null until there is a file. */
export function uploadDraft(form: UploadForm): DocumentUpload | null {
  if (!form.file) return null;
  const number = form.number.trim();
  return { kind: form.kind, file: form.file, ...(number ? { number } : {}), ...(form.expires ? { expires_on: form.expires } : {}) };
}

/** Whether a picked file is a PDF (shown as a file row; a picture shows its thumbnail). */
export const isPdf = (file: File): boolean => file.type === "application/pdf" || /\.pdf$/i.test(file.name);
