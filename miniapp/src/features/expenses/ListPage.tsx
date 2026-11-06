/**
 * Me → My expenses: what the company owes me back and the company cash I hold, then my claims,
 * newest first, each with where it stands (and Cancel while it waits). With none yet, an
 * invitation to add the first one.
 */
import { Plus, ReceiptText } from "lucide-react";

import { useNavigation } from "../../state/navigation";
import { useMember } from "../../state/session";
import { Button, EmptyState, LoadError, PageHeader, Screen, ScreenSkeleton } from "../../ui";
import { useFeatureOpen } from "../useFeatureOpen";
import { useClaims, useClaimWallet } from "./api";
import { ClaimRow, WalletSummary } from "./parts";
import { useExpensesT } from "./text";
import "./expenses.css";

export default function ListPage() {
  const t = useExpensesT();
  const member = useMember();
  const navigation = useNavigation();
  const go = useFeatureOpen("expenses");
  const claims = useClaims(member.companyId);
  const wallet = useClaimWallet(member.companyId);
  const add = () => go.sheet("new");

  return (
    <Screen variant="detail">
      <PageHeader kicker={member.company.name} title={t("me.expenses")} onBack={navigation.pop} />
      {claims.isPending ? (
        <ScreenSkeleton variant="list" delay={150} />
      ) : claims.isError && !claims.data ? (
        <LoadError error={claims.error} onRetry={() => void claims.refetch()} onBack={navigation.pop} />
      ) : (
        <>
          <WalletSummary wallet={wallet} hasClaims={claims.data.length > 0} />
          {claims.data.length === 0 ? (
            <EmptyState icon={ReceiptText} title={t("list.empty")} body={t("list.emptyBody")} action={{ label: t("list.add"), onClick: add, icon: Plus }} />
          ) : (
            <>
              <Button variant="secondary" block icon={Plus} onClick={add}>
                {t("list.new")}
              </Button>
              {claims.data.map((claim) => (
                <ClaimRow key={claim.id} claim={claim} onOpen={() => go.sheet("claim", { id: claim.id })} />
              ))}
            </>
          )}
        </>
      )}
    </Screen>
  );
}
