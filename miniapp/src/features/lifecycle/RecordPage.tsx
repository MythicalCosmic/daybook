/**
 * One record (the bot's `lifecycle.record:<id>` link): what it says, by whom and until when it
 * counts, "Tanishdim" while it waits for that, and my explanation (written once). Opening it
 * marks it read.
 */
import { CheckCheck, CircleCheck, PenLine, Undo2, Wallet } from "lucide-react";

import { hasModule } from "../../api/membership";
import { useI18n } from "../../i18n";
import { errorText } from "../../lib/actions";
import { dayMonthYear } from "../../lib/time";
import { useNavigation } from "../../state/navigation";
import { useMember } from "../../state/session";
import { useToast } from "../../state/toast";
import { haptic } from "../../telegram";
import { Banner, BottomBar, Button, Card, LoadError, PageHeader, Screen, ScreenSkeleton } from "../../ui";
import type { PageProps } from "../registry";
import { SheetFacts } from "../states";
import { useFeatureOpen } from "../useFeatureOpen";
import { useAcknowledgeRecord, useRecord } from "./api";
import { canExplain, recordStage } from "./lib";
import { categoryLabel, kindLabel, useRecordT } from "./text";
import "./lifecycle.css";

export default function RecordPage({ params }: PageProps) {
  const t = useRecordT();
  const { t: appT, locale } = useI18n();
  const member = useMember();
  const navigation = useNavigation();
  const toast = useToast();
  const go = useFeatureOpen("lifecycle");
  const id = Number(params.id);
  const record = useRecord(member.companyId, id);
  const acknowledge = useAcknowledgeRecord(member.companyId);

  if (!record.data) {
    return (
      <Screen variant="detail">
        {record.isError ? (
          <LoadError error={record.error} onRetry={() => void record.refetch()} onBack={navigation.pop} />
        ) : (
          <ScreenSkeleton variant="detail" delay={150} />
        )}
      </Screen>
    );
  }

  const data = record.data;
  const stage = recordStage(data);
  const day = (value: string) => dayMonthYear(value, "UTC", locale, new Date());
  const moment = (value: string) => dayMonthYear(value, member.timeZone, locale, new Date());
  const read = () => {
    if (acknowledge.isPending) return;
    acknowledge.mutate(data.id, {
      onSuccess: () => {
        haptic.notify("success");
        toast(t("record.ackToast"), { tone: "success" });
      },
      onError: (error) => {
        haptic.notify("error");
        toast(errorText(error, appT), { tone: "error" });
      },
    });
  };

  return (
    <>
      <Screen variant="detail">
        <PageHeader
          kicker={categoryLabel(t, data.category)}
          title={kindLabel(t, data.kind)}
          subtitle={data.issued_by ? t("record.issuedBy", { date: day(data.issued_on), name: data.issued_by }) : t("record.issued", { date: day(data.issued_on) })}
          onBack={navigation.pop}
        />

        {stage === "withdrawn" && (
          <Banner tone="sage" icon={Undo2} title={t("record.withdrawn")} body={data.withdraw_reason ? t("record.withdrawnBody", { reason: data.withdraw_reason }) : undefined} />
        )}
        {stage === "toRead" && <Banner tone="accent" icon={PenLine} title={t("record.ask")} body={t("record.askBody")} />}
        {data.acknowledged_at && stage !== "withdrawn" && <Banner tone="sage" icon={CircleCheck} title={t("record.acked", { date: moment(data.acknowledged_at) })} />}

        <Card className="lc-text">
          <p className="ft-text">{data.description}</p>
          <SheetFacts
            lines={[
              t("record.incident", { date: day(data.incident_on) }),
              stage === "past" ? t("record.countsDone") : stage !== "withdrawn" && data.expires_on && t("record.counts", { date: day(data.expires_on) }),
            ]}
          />
        </Card>

        {data.has_fine && stage !== "withdrawn" && (
          <Banner
            icon={Wallet}
            title={t("record.fine")}
            body={hasModule(member, "payroll") ? t("record.fineBody") : undefined}
            chevron={hasModule(member, "payroll")}
            onClick={hasModule(member, "payroll") ? () => navigation.push({ feature: "wallet", page: "adjustments" }) : undefined}
          />
        )}

        {data.employee_response ? (
          <Card tone="outline" className="lc-yours">
            <div className="lc-yours-head">{t("record.yours", { date: moment(data.responded_at ?? data.issued_on) })}</div>
            <p className="ft-text">{data.employee_response}</p>
          </Card>
        ) : (
          canExplain(data) && (
            <Button variant="secondary" block icon={PenLine} onClick={() => go.sheet("explain", { id: data.id })}>
              {t("record.explain")}
            </Button>
          )
        )}
      </Screen>
      {stage === "toRead" && (
        <BottomBar primary={{ text: t("record.ackButton"), onClick: read, loading: acknowledge.isPending, icon: CheckCheck, shine: true }} />
      )}
    </>
  );
}
