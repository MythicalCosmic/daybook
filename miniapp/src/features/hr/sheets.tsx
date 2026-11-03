/**
 * The HR sheets: my details (the few I may change), an emergency contact, uploading a document,
 * and one document with its file and "Upload a renewed one".
 */
import { Check, FileText, Trash, Upload } from "lucide-react";
import { useState } from "react";

import { useI18n } from "../../i18n";
import { addDays, dayKey, dayMonthYear } from "../../lib/time";
import { useDraftGuard } from "../../lib/useDraftGuard";
import { useNavigation } from "../../state/navigation";
import { useMember } from "../../state/session";
import { confirm } from "../../telegram";
import { Badge, Button, DateInput, Field, Input, PdfLink, PhotoInput, Segmented, Select, SheetTitle } from "../../ui";
import type { SheetProps } from "../registry";
import { SheetFacts, SheetMissing, useFeedback } from "../states";
import { useDocuments, useProfile, useRemoveContact, useSaveContact, useUpdateProfile, useUploadDocument, type Contact, type DocumentKind, type Profile } from "./api";
import { cardTyping, contactDraft, isPdf, profileChanges, profileForm, UPLOAD_KINDS, uploadDraft, type ProfileForm } from "./lib";
import { kindLabel, shortMask, stateLabel, useHrT, type HrKey } from "./text";
import "./hr.css";

// — my details —

export function ProfileSheet({ close }: SheetProps) {
  const member = useMember();
  const profile = useProfile(member.companyId);
  if (!profile.data) return <SheetMissing pending={profile.isPending} error={profile.error} onRetry={() => void profile.refetch()} />;
  return <ProfileFormSheet profile={profile.data} close={close} />;
}

function ProfileFormSheet({ profile, close }: { profile: Profile; close: () => void }) {
  const t = useHrT();
  const member = useMember();
  const update = useUpdateProfile(member.companyId);
  const feedback = useFeedback();
  const [form, setForm] = useState<ProfileForm>(() => profileForm(profile));
  const [tried, setTried] = useState(false);
  const { changes, problems } = profileChanges(form, profile);
  const changed = Object.keys(changes).length > 0;
  useDraftGuard(changed);
  const set = (patch: Partial<ProfileForm>) => setForm((current) => ({ ...current, ...patch }));
  const problem = (name: (typeof problems)[number], key: HrKey) => (tried && problems.includes(name) ? t(key) : undefined);

  const save = () => {
    setTried(true);
    if (problems.length || update.isPending) return;
    if (!changed) {
      close();
      return;
    }
    update.mutate(changes, {
      onSuccess: () => {
        feedback.ok(t("profile.saved"));
        close();
      },
      onError: feedback.fail,
    });
  };

  return (
    <>
      <SheetTitle>{t("profile.title")}</SheetTitle>
      <Field label={t("field.phone")} error={problem("phone", "contact.phoneProblem")}>
        <Input type="tel" inputMode="tel" autoComplete="tel" value={form.phone} maxLength={30} placeholder={t("contact.phonePlaceholder")} onChange={(event) => set({ phone: event.target.value })} />
      </Field>
      <Field label={t("field.email")} error={problem("email", "profile.emailProblem")}>
        <Input type="email" inputMode="email" autoComplete="email" value={form.email} maxLength={254} onChange={(event) => set({ email: event.target.value })} />
      </Field>
      <Field label={t("field.city")}>
        <Input autoComplete="address-level2" value={form.city} maxLength={100} onChange={(event) => set({ city: event.target.value })} />
      </Field>
      <Field label={t("field.address")}>
        <Input autoComplete="street-address" value={form.address} maxLength={255} onChange={(event) => set({ address: event.target.value })} />
      </Field>
      <Field label={t("profile.birthdayLabel")}>
        <Segmented
          options={[
            { value: "show", label: t("profile.birthdayShow") },
            { value: "hide", label: t("profile.birthdayHide") },
          ]}
          value={form.showBirthday ? "show" : "hide"}
          onChange={(value) => set({ showBirthday: value === "show" })}
          label={t("profile.birthdayLabel")}
        />
      </Field>
      <Field
        label={t("profile.cardLabel")}
        hint={profile.payout_card ? t("profile.cardHint", { card: shortMask(profile.payout_card) }) : t("profile.cardHintNone")}
        error={problem("card", "profile.cardProblem")}
      >
        <Input num inputMode="numeric" autoComplete="cc-number" value={cardTyping(form.card)} placeholder="0000 0000 0000 0000" onChange={(event) => set({ card: cardTyping(event.target.value) })} />
      </Field>
      <Button variant="primary" size="lg" block icon={Check} loading={update.isPending} onClick={save}>
        {t("profile.save")}
      </Button>
    </>
  );
}

// — an emergency contact —

export function ContactSheet({ params, close }: SheetProps) {
  const member = useMember();
  const profile = useProfile(member.companyId);
  const id = params.id !== undefined ? Number(params.id) : null;
  const contact = id === null ? null : profile.data?.emergency_contacts.find((row) => row.id === id);
  if (!profile.data || contact === undefined) return <SheetMissing pending={profile.isPending} error={profile.error} onRetry={() => void profile.refetch()} />;
  return <ContactForm contact={contact} close={close} />;
}

function ContactForm({ contact, close }: { contact: Contact | null; close: () => void }) {
  const t = useHrT();
  const member = useMember();
  const save = useSaveContact(member.companyId);
  const remove = useRemoveContact(member.companyId);
  const feedback = useFeedback();
  const [name, setName] = useState(contact?.name ?? "");
  const [relation, setRelation] = useState(contact?.relation ?? "");
  const [phone, setPhone] = useState(contact?.phone ?? "");
  const [tried, setTried] = useState(false);
  const result = contactDraft({ name, relation, phone });
  const problems = "problems" in result ? result.problems : [];
  useDraftGuard(name !== (contact?.name ?? "") || relation !== (contact?.relation ?? "") || phone !== (contact?.phone ?? ""));

  const submit = () => {
    setTried(true);
    if (!("draft" in result) || save.isPending) return;
    save.mutate(
      { id: contact?.id ?? null, draft: result.draft },
      {
        onSuccess: () => {
          feedback.ok(t("contact.saved"));
          close();
        },
        onError: feedback.fail,
      },
    );
  };
  const drop = async () => {
    if (!contact || remove.isPending || !(await confirm(t("contact.removeAsk")))) return;
    remove.mutate(contact.id, {
      onSuccess: () => {
        feedback.ok(t("contact.removed"));
        close();
      },
      onError: feedback.fail,
    });
  };

  return (
    <>
      <SheetTitle>{contact ? t("contact.edit") : t("contact.new")}</SheetTitle>
      <Field label={t("contact.name")} error={tried && problems.includes("name") ? t("contact.nameProblem") : undefined}>
        <Input autoComplete="name" value={name} maxLength={150} onChange={(event) => setName(event.target.value)} autoFocus={!contact} />
      </Field>
      <Field label={t("contact.relation")} optional>
        <Input value={relation} maxLength={60} placeholder={t("contact.relationPlaceholder")} onChange={(event) => setRelation(event.target.value)} />
      </Field>
      <Field label={t("field.phone")} error={tried && problems.includes("phone") ? t("contact.phoneProblem") : undefined}>
        <Input type="tel" inputMode="tel" autoComplete="tel" value={phone} maxLength={30} placeholder={t("contact.phonePlaceholder")} onChange={(event) => setPhone(event.target.value)} />
      </Field>
      <Button variant="primary" size="lg" block icon={Check} loading={save.isPending} onClick={submit}>
        {t("contact.save")}
      </Button>
      {contact && (
        <Button variant="ghost" block icon={Trash} loading={remove.isPending} onClick={() => void drop()} className="hr-remove">
          {t("contact.remove")}
        </Button>
      )}
    </>
  );
}

// — uploading a document —

/** Kinds that usually run out: their upload asks for the end date first. */
const EXPIRING: ReadonlySet<DocumentKind> = new Set(["medical_book", "medical_exam", "pharmacist_certificate", "qualification_category", "passport", "id_card"]);

export function UploadSheet({ params, close }: SheetProps) {
  const t = useHrT();
  const member = useMember();
  const upload = useUploadDocument(member.companyId);
  const feedback = useFeedback();
  const today = dayKey(new Date(), member.timeZone);
  const asked = UPLOAD_KINDS.find((kind) => kind === params.kind);
  const [kind, setKind] = useState<DocumentKind>(asked ?? "medical_book");
  const [file, setFile] = useState<File | null>(null);
  const [number, setNumber] = useState("");
  const [hasEnd, setHasEnd] = useState(EXPIRING.has(asked ?? "medical_book"));
  // A medical book is good for a year: the likeliest end date is a year from today.
  const [expires, setExpires] = useState(addDays(today, 365));
  useDraftGuard(Boolean(file || number.trim()));
  const draft = uploadDraft({ kind, file, number, expires: hasEnd ? expires : null });

  const submit = () => {
    if (!draft || upload.isPending) return;
    upload.mutate(draft, {
      onSuccess: () => {
        feedback.ok(t("upload.done"));
        close();
      },
      onError: feedback.fail,
    });
  };

  return (
    <>
      <SheetTitle kicker={t("upload.kicker")}>{t("documents.upload")}</SheetTitle>
      <Field label={t("upload.kind")}>
        <Select
          value={kind}
          onChange={(event) => {
            const next = event.target.value as DocumentKind;
            setKind(next);
            setHasEnd(EXPIRING.has(next));
          }}
        >
          {UPLOAD_KINDS.map((option) => (
            <option key={option} value={option}>
              {kindLabel(t, option)}
            </option>
          ))}
        </Select>
      </Field>
      <Field label={t("upload.file")} hint={t("upload.fileHint")}>
        {file && isPdf(file) ? (
          <div className="ui-photo">
            <span className="ui-photo-thumb hr-pdf-thumb" aria-hidden>
              <FileText size={26} strokeWidth={2.2} />
            </span>
            <div className="ui-photo-text">
              <div className="ui-photo-title">{t("upload.pdf")}</div>
              <div className="ui-photo-name">{file.name}</div>
            </div>
            <RemoveFile onRemove={() => setFile(null)} />
          </div>
        ) : (
          <PhotoInput value={file} onChange={setFile} capture="environment" accept="image/*,application/pdf" label={t("upload.pick")} />
        )}
      </Field>
      <Field label={t("upload.number")} optional>
        <Input value={number} maxLength={40} autoCapitalize="characters" onChange={(event) => setNumber(event.target.value)} />
      </Field>
      <Field label={t("upload.expiry")}>
        <Segmented
          options={[
            { value: "none", label: t("upload.noExpiry") },
            { value: "date", label: t("upload.hasExpiry") },
          ]}
          value={hasEnd ? "date" : "none"}
          onChange={(value) => setHasEnd(value === "date")}
          label={t("upload.expiry")}
        />
        {hasEnd && <DateInput value={expires} onChange={setExpires} label={t("upload.expiry")} min={today} today={today} long className="hr-date" />}
      </Field>
      <Button variant="primary" size="lg" block icon={Upload} disabled={!draft} loading={upload.isPending} onClick={submit}>
        {t("upload.submit")}
      </Button>
    </>
  );
}

function RemoveFile({ onRemove }: { onRemove: () => void }) {
  const { t } = useI18n();
  return (
    <button type="button" className="btn btn-ghost" onClick={onRemove}>
      {t("ui.photo.remove")}
    </button>
  );
}

// — one document —

export function DocumentSheet({ params }: SheetProps) {
  const t = useHrT();
  const { locale } = useI18n();
  const member = useMember();
  const navigation = useNavigation();
  const documents = useDocuments(member.companyId);
  const document = documents.data?.find((row) => row.id === Number(params.id));
  if (!document) return <SheetMissing pending={documents.isPending} error={documents.error} onRetry={() => void documents.refetch()} />;

  const date = (day: string) => dayMonthYear(day, "UTC", locale);
  // Signed links run out within minutes: a tap asks for the list again and opens the fresh one.
  const fresh = async () => {
    const latest = await documents.refetch();
    const link = latest.data?.find((row) => row.id === document.id)?.file;
    if (!link) throw new Error("No file");
    return link;
  };
  return (
    <>
      {/* A document with its own title says its kind above it; otherwise the kind is the title. */}
      <SheetTitle kicker={document.title ? kindLabel(t, document.kind) : undefined}>{document.title || kindLabel(t, document.kind)}</SheetTitle>
      <div className="hr-badges">
        <Badge tone={document.state === "valid" ? "sage" : document.state === "no_expiry" ? "neutral" : "accent"} size="small">
          {stateLabel(t, document)}
        </Badge>
        <Badge tone={document.verified ? "sage" : "neutral"} size="small">
          {t(document.verified ? "document.verified" : "document.unverified")}
        </Badge>
      </div>
      <SheetFacts
        lines={[
          document.number && t("document.number", { number: document.number }),
          document.level && t(`level.${document.level}` as HrKey),
          document.issued_on && t("document.issued", { date: date(document.issued_on) }),
          document.expires_on && t("document.validUntil", { date: date(document.expires_on) }),
        ]}
      />
      {document.file ? <PdfLink href={fresh} title={t("document.open")} subtitle={t("document.openSub")} /> : <p className="ft-hint">{t("document.noFile")}</p>}
      <Button
        variant="secondary"
        block
        icon={Upload}
        onClick={() => navigation.openSheet({ kind: "feature", feature: "hr", sheet: "upload", params: { kind: document.kind } })}
      >
        {t("document.renew")}
      </Button>
    </>
  );
}
