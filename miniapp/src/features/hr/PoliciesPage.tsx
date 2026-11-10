/**
 * "Qoidalar" (Me → Rules, or the bot's `hr.policies` link): the rules of my position, what to sign
 * first (late ones on top), then the signed ones and those only to read. A row opens the rule.
 */
import { BookOpenCheck, BookText, Pill, Scale, ShieldCheck, Thermometer, type LucideIcon } from "lucide-react";

import { useI18n } from "../../i18n";
import { dayMonthYear } from "../../lib/time";
import { useNavigation } from "../../state/navigation";
import { useMember } from "../../state/session";
import { Badge, EmptyState, LoadError, PageHeader, Screen, ScreenSkeleton, SectionHead, type BadgeTone } from "../../ui";
import { EntryRow } from "../EntryRow";
import { useFeatureOpen } from "../useFeatureOpen";
import { toSign, useMyPolicies, type MyPolicy, type PolicyCategory, type PolicyState } from "./policies";
import { useHrT, type HrKey, type HrT } from "./text";
import "./hr.css";

export const CATEGORY_ICONS: Record<PolicyCategory, LucideIcon> = {
  dispensing: Pill,
  storage: Thermometer,
  safety: ShieldCheck,
  conduct: Scale,
  other: BookText,
};

export const STATE_TONES: Record<PolicyState, BadgeTone> = { waiting: "accent", late: "accent", signed: "sage", to_read: "neutral" };

/** What a row says under the title: the deadline, when it was signed, or its version. */
export function policyLine(t: HrT, row: MyPolicy, timeZone: string, locale: string): string {
  const day = (value: string) => dayMonthYear(value, "UTC", locale);
  if (row.state === "late" && row.due_on) return t("policies.lateSince", { date: day(row.due_on) });
  if (row.state === "waiting" && row.due_on) return t("policies.dueOn", { date: day(row.due_on) });
  if (row.state === "signed" && row.signed_at) return t("policies.signedOn", { date: dayMonthYear(row.signed_at, timeZone, locale) });
  return t("policies.version", { number: row.number });
}

export default function PoliciesPage() {
  const t = useHrT();
  const { locale } = useI18n();
  const member = useMember();
  const navigation = useNavigation();
  const go = useFeatureOpen("hr");
  const policies = useMyPolicies(member.companyId);
  const header = <PageHeader kicker={member.company.name} title={t("policies.title")} onBack={navigation.pop} />;

  if (!policies.data) {
    return (
      <Screen variant="detail">
        {header}
        {policies.isError ? <LoadError error={policies.error} onRetry={() => void policies.refetch()} onBack={navigation.pop} /> : <ScreenSkeleton variant="detail" delay={150} />}
      </Screen>
    );
  }

  const rows = policies.data;
  const pending = toSign(rows);
  const signed = rows.filter((row) => row.state === "signed");
  const toRead = rows.filter((row) => row.state === "to_read");
  const list = (items: MyPolicy[]) =>
    items.map((row) => (
      <EntryRow
        key={row.id}
        icon={CATEGORY_ICONS[row.category]}
        tone={row.state === "signed" ? "sage" : row.state === "to_read" ? "plain" : "accent"}
        title={row.title}
        details={[t(`policy.category.${row.category}` as HrKey), policyLine(t, row, member.timeZone, locale)]}
        chips={
          <Badge tone={STATE_TONES[row.state]} size="small">
            {t(`policy.state.${row.state}` as HrKey)}
          </Badge>
        }
        onOpen={() => go.page("policy", { id: row.id })}
        className="hr-row"
      />
    ));

  return (
    <Screen variant="detail">
      {header}
      {rows.length === 0 ? (
        <EmptyState icon={BookOpenCheck} tone="sage" title={t("policies.empty")} body={t("policies.emptyBody")} />
      ) : (
        <>
          {pending.length > 0 && (
            <>
              <SectionHead count={pending.length}>{t("policies.toSign")}</SectionHead>
              {list(pending)}
            </>
          )}
          {signed.length > 0 && (
            <>
              <SectionHead count={signed.length}>{t("policies.signed")}</SectionHead>
              {list(signed)}
            </>
          )}
          {toRead.length > 0 && (
            <>
              <SectionHead count={toRead.length}>{t("policies.toRead")}</SectionHead>
              {list(toRead)}
            </>
          )}
        </>
      )}
    </Screen>
  );
}
