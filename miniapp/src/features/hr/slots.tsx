/**
 * What HR puts on Home and Me: a card while the contract waits for "Tanishdim", a card for a
 * document that ran out (or soon will), a card for rules to read and sign, and the Me rows'
 * bubbles.
 */
import { BookOpenCheck } from "lucide-react";

import { useI18n } from "../../i18n";
import { dayMonthYear } from "../../lib/time";
import { Banner } from "../../ui";
import type { MeItemStatus, SlotProps } from "../registry";
import { useFeatureOpen } from "../useFeatureOpen";
import { useContract, useDocuments } from "./api";
import { needingAttention, RENEW_DIRECTLY } from "./lib";
import { ContractBanner, DocumentBanner } from "./parts";
import { toSign, useMyPolicies } from "./policies";
import { useHrT } from "./text";

export function ContractCard({ member }: SlotProps) {
  const go = useFeatureOpen("hr");
  const contract = useContract(member.companyId);
  if (!contract.data?.needs_acknowledgement) return null;
  return <ContractBanner size="lg" contract={contract.data} onOpen={() => go.page("contract")} />;
}

export function DocumentCard({ member }: SlotProps) {
  const go = useFeatureOpen("hr");
  const documents = useDocuments(member.companyId);
  const first = needingAttention(documents.data)[0];
  if (!first) return null;
  // A pharmacist's certificate: "Upload my renewed certificate" opens the upload for that kind.
  if (RENEW_DIRECTLY.includes(first.kind)) {
    return <DocumentBanner size="lg" document={first} renew onOpen={() => go.sheet("upload", { kind: first.kind })} />;
  }
  return <DocumentBanner size="lg" document={first} onOpen={() => go.page("documents")} />;
}

/** Me → My documents: a bubble for the contract to read and each document that needs renewing. */
export function useMeStatus({ member }: SlotProps): MeItemStatus {
  const contract = useContract(member.companyId);
  const documents = useDocuments(member.companyId);
  const count = (contract.data?.needs_acknowledgement ? 1 : 0) + needingAttention(documents.data).length;
  return { badge: count || null };
}

/**
 * Rules to read and sign, on Home until they are signed: one rule opens itself, several open the
 * list; a late one says so.
 */
export function PoliciesCard({ member }: SlotProps) {
  const t = useHrT();
  const { locale } = useI18n();
  const go = useFeatureOpen("hr");
  const policies = useMyPolicies(member.companyId);
  const pending = toSign(policies.data);
  const first = pending[0];
  if (!first) return null;
  const late = pending.some((row) => row.state === "late");
  const due = pending.map((row) => row.due_on).filter((day): day is string => Boolean(day)).sort()[0];
  return (
    <Banner
      size="lg"
      tone="plain"
      iconTone="accent"
      icon={BookOpenCheck}
      title={pending.length === 1 ? t("home.policy", { title: first.title }) : t("home.policies", { count: pending.length })}
      body={late ? t("home.policyLate") : due ? t("home.policyBody", { date: dayMonthYear(due, "UTC", locale) }) : undefined}
      chevron
      wrap
      onClick={() => (pending.length === 1 ? go.page("policy", { id: first.id }) : go.page("policies"))}
    />
  );
}

/** Me → Rules: a bubble for each rule still to sign. */
export function usePoliciesStatus({ member }: SlotProps): MeItemStatus {
  const policies = useMyPolicies(member.companyId);
  return { badge: toSign(policies.data).length || null };
}
