/** What expenses puts on Me: the row's value is the money the company still owes me back. */
import { useI18n } from "../../i18n";
import { formatMoney } from "../../lib/money";
import type { MeItemStatus, SlotProps } from "../registry";
import { useClaimWallet } from "./api";
import { positive } from "./lib";
import { useExpensesT } from "./text";

/** Me → My expenses: "450K UZS owed" while approved money is still to come back; nothing otherwise. */
export function useMeStatus({ member }: SlotProps): MeItemStatus {
  const t = useExpensesT();
  const { lang } = useI18n();
  const wallet = useClaimWallet(member.companyId);
  const owed = positive(wallet.data?.owed_to_me);
  return { value: owed && wallet.data ? t("me.owed", { amount: formatMoney(owed, wallet.data.currency, lang, { compact: true }) }) : undefined };
}
