/**
 * One rule to read (the bot's `hr.policy:<id>` button opens it): what it asks and by when, what
 * changed in this version, the text, the attached document, and "O‘qidim va roziman" (I have read
 * it and agree) with a confirm while it waits for my signature; once signed, when I signed it.
 */
import { CheckCheck, CircleCheck, PenLine, ScrollText, TriangleAlert } from "lucide-react";
import { useMemo } from "react";

import { useI18n } from "../../i18n";
import { errorText } from "../../lib/actions";
import { dayMonthYear } from "../../lib/time";
import { useNavigation } from "../../state/navigation";
import { useMember } from "../../state/session";
import { useToast } from "../../state/toast";
import { confirm, haptic } from "../../telegram";
import { Badge, Banner, BottomBar, Card, LoadError, PageHeader, PdfLink, Screen, ScreenSkeleton } from "../../ui";
import { safeHtml } from "../knowledge/safeHtml";
import "../knowledge/knowledge.css";
import type { PageProps } from "../registry";
import { STATE_TONES } from "./PoliciesPage";
import { policyFile, useMyPolicy, useSignPolicy, type MyPolicyDetail } from "./policies";
import { useHrT, type HrKey } from "./text";
import "./hr.css";

export default function PolicyPage({ params }: PageProps) {
  const t = useHrT();
  const { t: appT, locale } = useI18n();
  const member = useMember();
  const navigation = useNavigation();
  const toast = useToast();
  const id = Number(params.id);
  const policy = useMyPolicy(member.companyId, id);
  const sign = useSignPolicy(member.companyId, id);
  const body = useMemo(() => safeHtml(policy.data?.body ?? ""), [policy.data?.body]);

  const header = (data?: MyPolicyDetail) => (
    <PageHeader
      kicker={data ? t(`policy.category.${data.category}` as HrKey) : t("policies.title")}
      title={data?.title ?? t("policies.title")}
      subtitle={
        data && (
          <span className="hr-badges">
            <Badge tone={STATE_TONES[data.state]} size="small">
              {t(`policy.state.${data.state}` as HrKey)}
            </Badge>
            <span>{t("policy.published", { number: data.number, date: dayMonthYear(data.published_at, member.timeZone, locale) })}</span>
          </span>
        )
      }
      onBack={navigation.pop}
    />
  );

  if (!policy.data) {
    return (
      <Screen variant="detail">
        {header()}
        {policy.isError ? <LoadError error={policy.error} onRetry={() => void policy.refetch()} onBack={navigation.pop} /> : <ScreenSkeleton variant="detail" delay={150} />}
      </Screen>
    );
  }

  const data = policy.data;
  const day = (value: string) => dayMonthYear(value, "UTC", locale);
  const owed = data.state === "waiting" || data.state === "late";
  const agree = async () => {
    if (sign.isPending || !(await confirm(t("policy.confirm", { title: data.title })))) return;
    sign.mutate(data.version_id, {
      onSuccess: () => {
        haptic.notify("success");
        toast(t("policy.signedToast"), { tone: "success" });
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
        {header(data)}
        {data.state === "waiting" && <Banner tone="accent" icon={PenLine} title={t("policy.ask")} body={data.due_on ? t("policy.askBody", { date: day(data.due_on) }) : undefined} />}
        {data.state === "late" && <Banner tone="accent" icon={TriangleAlert} title={t("policy.late")} body={data.due_on ? t("policy.lateBody", { date: day(data.due_on) }) : undefined} />}
        {data.state === "signed" && data.signed_at && (
          <Banner
            tone="sage"
            icon={CircleCheck}
            title={t("policy.signedBanner", { date: dayMonthYear(data.signed_at, member.timeZone, locale) })}
            body={data.signed_number && data.signed_number !== data.number ? t("policy.signedOlder", { number: data.signed_number }) : undefined}
          />
        )}
        {data.state === "to_read" && <Banner icon={ScrollText} title={t("policy.toReadBanner")} />}

        {data.change_note && data.number > 1 && (
          <Card className="hr-change">
            <div className="hr-change-label">{t("policy.whatChanged")}</div>
            <p className="hr-change-text">{data.change_note}</p>
          </Card>
        )}

        {/* Cleaned by the server's allow-list, then again by safeHtml. */}
        {body && <article className="kbm-article" dangerouslySetInnerHTML={{ __html: body }} />}

        {data.has_file && <PdfLink href={policyFile(member.companyId, data.id)} title={t("policy.file")} subtitle={t("policy.fileSub")} />}
      </Screen>
      {/* Outside the scrolling screen, so it stays at the bottom however far one reads. */}
      {owed && <BottomBar primary={{ text: t("policy.sign"), onClick: () => void agree(), loading: sign.isPending, icon: CheckCheck, shine: true }} />}
    </>
  );
}
