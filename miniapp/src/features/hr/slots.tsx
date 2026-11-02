/**
 * What HR puts on Home and Me: a card while the contract waits for "Tanishdim", a card for a
 * document that ran out (or soon will), and the Me row's bubble for both.
 */
import type { MeItemStatus, SlotProps } from "../registry";
import { useFeatureOpen } from "../useFeatureOpen";
import { useContract, useDocuments } from "./api";
import { needingAttention } from "./lib";
import { ContractBanner, DocumentBanner } from "./parts";

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
  return <DocumentBanner size="lg" document={first} onOpen={() => go.page("documents")} />;
}

/** Me → My documents: a bubble for the contract to read and each document that needs renewing. */
export function useMeStatus({ member }: SlotProps): MeItemStatus {
  const contract = useContract(member.companyId);
  const documents = useDocuments(member.companyId);
  const count = (contract.data?.needs_acknowledgement ? 1 : 0) + needingAttention(documents.data).length;
  return { badge: count || null };
}
