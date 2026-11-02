/**
 * My contract (the bot's `hr.contract` link, sent when one comes into force): its terms, the PDF
 * or scan, and "Tanishdim" (I've read it) while it asks for that.
 */
import { CheckCheck, CircleCheck, FilePen, FileX } from "lucide-react";

import { useI18n } from "../../i18n";
import { errorText } from "../../lib/actions";
import { decimalPoint } from "../../lib/money";
import { dayMonthYear } from "../../lib/time";
import { useNavigation } from "../../state/navigation";
import { useMember } from "../../state/session";
import { useToast } from "../../state/toast";
import { confirm, haptic } from "../../telegram";
import { Badge, Banner, BottomBar, EmptyState, ListCard, ListRow, LoadError, PageHeader, PdfLink, Screen, ScreenSkeleton, type BadgeTone } from "../../ui";
import { contractPdf, useAcknowledgeContract, useContract, type Contract } from "./api";
import { useHrT, type HrKey } from "./text";
import "./hr.css";

const STATUS_TONE: Record<Contract["status"], BadgeTone> = { active: "sage", ended: "neutral", terminated: "neutral", draft: "neutral" };

export default function ContractPage() {
  const t = useHrT();
  const { t: appT, lang, locale } = useI18n();
  const member = useMember();
  const navigation = useNavigation();
  const toast = useToast();
  const contract = useContract(member.companyId);
  const acknowledge = useAcknowledgeContract(member.companyId);
  const header = (data?: Contract) => (
    <PageHeader
      kicker={t("row.contract")}
      title={data ? `№ ${data.number}` : t("row.contract")}
      subtitle={
        data && (
          <Badge tone={STATUS_TONE[data.status]} size="small">
            {t(`contract.status.${data.status}` as HrKey)}
          </Badge>
        )
      }
      onBack={navigation.pop}
    />
  );

  if (contract.data === undefined) {
    return (
      <Screen variant="detail">
        {header()}
        {contract.isError ? (
          <LoadError error={contract.error} onRetry={() => void contract.refetch()} onBack={navigation.pop} />
        ) : (
          <ScreenSkeleton variant="detail" delay={150} />
        )}
      </Screen>
    );
  }
  if (contract.data === null) {
    return (
      <Screen variant="detail">
        {header()}
        <EmptyState icon={FilePen} tone="sage" title={t("contract.none")} body={t("contract.noneBody")} />
      </Screen>
    );
  }

  const data = contract.data;
  const date = (day: string) => dayMonthYear(day, "UTC", locale);
  const read = async () => {
    if (acknowledge.isPending || !(await confirm(t("contract.ackAsk")))) return;
    acknowledge.mutate(data.id, {
      onSuccess: () => {
        haptic.notify("success");
        toast(t("contract.ackToast"), { tone: "success" });
      },
      onError: (error) => {
        haptic.notify("error");
        toast(errorText(error, appT), { tone: "error" });
      },
    });
  };
  const probation = data.probation_passed_at
    ? t("contract.probationPassed")
    : data.probation_until
      ? t("contract.probationUntil", { date: date(data.probation_until) })
      : null;

  return (
    <>
      <Screen variant="detail">
        {header(data)}
        {data.needs_acknowledgement ? (
          <Banner tone="accent" icon={FilePen} title={t("contract.read")} body={t("contract.readBody")} />
        ) : (
          data.acknowledged_at && (
            <Banner tone="sage" icon={CircleCheck} title={t("contract.acked", { date: dayMonthYear(data.acknowledged_at, member.timeZone, locale) })} />
          )
        )}

        <ListCard className="hr-details">
          <ListRow title={t("contract.kindLabel")} value={t(`contract.kind.${data.kind}` as HrKey)} />
          {data.position && <ListRow title={t("contract.position")} value={data.position} />}
          <ListRow title={t("contract.starts")} value={date(data.starts_on)} />
          <ListRow title={t("contract.ends")} value={data.ends_on ? date(data.ends_on) : t("contract.noEnd")} />
          {data.terminated_on && <ListRow title={t("contract.terminatedOn")} value={date(data.terminated_on)} />}
          {probation && <ListRow title={t("contract.probation")} value={probation} />}
          {data.weekly_hours && (
            <ListRow title={t("contract.hours")} value={t("contract.hoursValue", { hours: String(Number(data.weekly_hours)).replace(".", decimalPoint(lang)) })} />
          )}
        </ListCard>

        {data.file ? (
          <PdfLink href={contractPdf(member.companyId)} title={t("contract.pdf")} subtitle={t("contract.pdfSub")} />
        ) : (
          <Banner icon={FileX} title={t("contract.noFile")} />
        )}
      </Screen>
      {data.needs_acknowledgement && (
        <BottomBar primary={{ text: t("contract.ackButton"), onClick: () => void read(), loading: acknowledge.isPending, icon: CheckCheck, shine: true }} />
      )}
    </>
  );
}
