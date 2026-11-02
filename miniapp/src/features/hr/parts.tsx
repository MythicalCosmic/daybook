/** Pieces the HR pages and Home share: the contract to read, a document that needs renewing, a document row. */
import { FilePen, Stethoscope } from "lucide-react";

import { useI18n } from "../../i18n";
import { dayMonthYear } from "../../lib/time";
import { Badge, Banner, type BadgeTone } from "../../ui";
import { EntryRow } from "../EntryRow";
import type { Contract, DocumentState, HrDocument } from "./api";
import { documentName, kindIcon, stateLabel, useHrT } from "./text";

/** "Please read your contract": Home and the HR page, until "I've read it". */
export function ContractBanner({ contract, onOpen, size = "md" }: { contract: Contract; onOpen: () => void; size?: "md" | "lg" }) {
  const t = useHrT();
  return (
    <Banner
      size={size}
      tone={size === "md" ? "accent" : "plain"}
      iconTone="accent"
      icon={FilePen}
      title={t("home.contract")}
      body={t("home.contractBody", { number: contract.number })}
      chevron
      wrap
      onClick={onOpen}
    />
  );
}

/** A document that ran out or soon will: "Medical book: 12 days left · upload the renewed one". */
export function DocumentBanner({ document, onOpen, size = "md" }: { document: HrDocument; onOpen: () => void; size?: "md" | "lg" }) {
  const t = useHrT();
  const name = documentName(t, document);
  const title =
    document.state === "expired" ? t("home.expired", { kind: name }) : t("home.expiring", { kind: name, count: Math.max(0, document.days_left ?? 0) });
  return (
    <Banner
      size={size}
      tone={size === "md" ? "accent" : "plain"}
      iconTone="accent"
      icon={document.kind === "medical_book" || document.kind === "medical_exam" ? Stethoscope : kindIcon(document.kind)}
      title={title}
      body={t("home.documentBody")}
      chevron
      wrap
      onClick={onOpen}
    />
  );
}

const STATE_TONE: Record<DocumentState, BadgeTone> = { valid: "sage", expiring: "accent", expired: "accent", no_expiry: "neutral" };

/** A document in the list: its kind, number and end date, where it stands, and whether HR checked it. */
export function DocumentRow({ document, onOpen }: { document: HrDocument; onOpen: () => void }) {
  const t = useHrT();
  const { locale } = useI18n();
  return (
    <EntryRow
      icon={kindIcon(document.kind)}
      tone={document.state === "expired" || document.state === "expiring" ? "accent" : "sage"}
      title={documentName(t, document)}
      details={[
        document.number && t("document.number", { number: document.number }),
        document.expires_on && t("document.until", { date: dayMonthYear(document.expires_on, "UTC", locale) }),
      ]}
      chips={
        <>
          <Badge tone={STATE_TONE[document.state]} size="small">
            {stateLabel(t, document)}
          </Badge>
          {!document.verified && (
            <Badge tone="neutral" size="small">
              {t("document.unverified")}
            </Badge>
          )}
        </>
      }
      onOpen={onOpen}
      className="hr-row"
    />
  );
}
