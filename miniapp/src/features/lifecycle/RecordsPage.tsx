/**
 * "Intizom" (Me → My record): the warnings and reprimands given to me, those still counting first,
 * each with where it stands. Calm: an empty page says so kindly.
 */
import { ShieldCheck } from "lucide-react";

import { useI18n } from "../../i18n";
import { dayMonthYear } from "../../lib/time";
import { useNavigation } from "../../state/navigation";
import { useMember } from "../../state/session";
import { Badge, EmptyState, LoadError, PageHeader, Screen, ScreenSkeleton, SectionHead, type BadgeTone } from "../../ui";
import { EntryRow } from "../EntryRow";
import { useFeatureOpen } from "../useFeatureOpen";
import { useRecords, type DisciplinaryRecord } from "./api";
import { recordStage, splitRecords, type RecordStage } from "./lib";
import { categoryLabel, kindIcon, kindLabel, useRecordT } from "./text";
import "./lifecycle.css";

const STAGE_TONE: Record<RecordStage, BadgeTone> = { toRead: "accent", done: "sage", past: "neutral", withdrawn: "neutral" };

export default function RecordsPage() {
  const t = useRecordT();
  const member = useMember();
  const navigation = useNavigation();
  const records = useRecords(member.companyId);
  const header = <PageHeader kicker={member.company.name} title={t("me.record")} subtitle={t("page.subtitle")} onBack={navigation.pop} />;

  if (!records.data) {
    return (
      <Screen variant="detail">
        {header}
        {records.isError ? <LoadError error={records.error} onRetry={() => void records.refetch()} onBack={navigation.pop} /> : <ScreenSkeleton variant="list" delay={150} />}
      </Screen>
    );
  }
  if (records.data.length === 0) {
    return (
      <Screen variant="detail">
        {header}
        <EmptyState icon={ShieldCheck} tone="sage" title={t("page.empty")} body={t("page.emptyBody")} />
      </Screen>
    );
  }
  const { current, earlier } = splitRecords(records.data);
  return (
    <Screen variant="detail">
      {header}
      <p className="ft-quiet">{t("page.intro")}</p>
      {current.length > 0 && (
        <>
          <SectionHead size="small" count={current.length}>
            {t("page.current")}
          </SectionHead>
          {current.map((record) => (
            <RecordRow key={record.id} record={record} />
          ))}
        </>
      )}
      {earlier.length > 0 && (
        <>
          <SectionHead size="small">{t("page.earlier")}</SectionHead>
          {earlier.map((record) => (
            <RecordRow key={record.id} record={record} />
          ))}
        </>
      )}
    </Screen>
  );
}

function RecordRow({ record }: { record: DisciplinaryRecord }) {
  const t = useRecordT();
  const { locale } = useI18n();
  const go = useFeatureOpen("lifecycle");
  const stage = recordStage(record);
  return (
    <EntryRow
      icon={kindIcon(record.kind)}
      tone={stage === "toRead" ? "accent" : stage === "done" ? "sage" : "plain"}
      title={kindLabel(t, record.kind)}
      details={[`${categoryLabel(t, record.category)} · ${dayMonthYear(record.issued_on, "UTC", locale, new Date())}`]}
      chips={
        <>
          <Badge tone={STAGE_TONE[stage]} size="small">
            {t(`stage.${stage}`)}
          </Badge>
          {record.employee_response && (
            <Badge tone="neutral" size="small">
              {t("row.explained")}
            </Badge>
          )}
        </>
      }
      onOpen={() => go.page("record", { id: record.id })}
      className="lc-row"
    />
  );
}
