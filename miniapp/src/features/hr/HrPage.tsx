/**
 * "Hujjatlarim" (Me → My documents): who I am here, my contract and documents (with what needs
 * me), my details with the few I may change, and my emergency contacts.
 */
import { BookOpenCheck, FilePen, FolderOpen, Phone, Plus } from "lucide-react";

import { useI18n } from "../../i18n";
import { dayMonthLong, dayMonthYear } from "../../lib/time";
import { useNavigation } from "../../state/navigation";
import { useMember } from "../../state/session";
import { Avatar, Badge, Button, Card, ListCard, ListRow, LoadError, PageHeader, Screen, ScreenSkeleton, SectionHead } from "../../ui";
import { useFeatureOpen } from "../useFeatureOpen";
import { useContract, useDocuments, useProfile, type Profile } from "./api";
import { MAX_CONTACTS, needingAttention } from "./lib";
import { toSign, useMyPolicies } from "./policies";
import { attentionText, shortMask, useHrT, type HrKey } from "./text";
import "./hr.css";

export default function HrPage() {
  const t = useHrT();
  const { locale } = useI18n();
  const member = useMember();
  const navigation = useNavigation();
  const go = useFeatureOpen("hr");
  const profile = useProfile(member.companyId);
  const contract = useContract(member.companyId);
  const documents = useDocuments(member.companyId);
  const policies = useMyPolicies(member.companyId);
  const pending = toSign(policies.data);
  const header = <PageHeader kicker={member.company.name} title={t("me.documents")} onBack={navigation.pop} />;

  if (!profile.data) {
    return (
      <Screen variant="detail">
        {header}
        {profile.isError ? <LoadError error={profile.error} onRetry={() => void profile.refetch()} onBack={navigation.pop} /> : <ScreenSkeleton variant="detail" delay={150} />}
      </Screen>
    );
  }

  const data = profile.data;
  // The rows below say what needs the person (Home has the cards): the most urgent document first.
  const first = needingAttention(documents.data)[0];
  return (
    <Screen variant="detail">
      {header}
      <Who profile={data} />

      <SectionHead>{t("section.papers")}</SectionHead>
      <ListCard>
        <ListRow
          icon={FilePen}
          title={t("row.contract")}
          subtitle={
            contract.isPending
              ? undefined
              : contract.data
                ? `№ ${contract.data.number} · ${t(`contract.status.${contract.data.status}` as HrKey)}`
                : t("row.contractNone")
          }
          value={contract.data?.needs_acknowledgement ? <Badge tone="accent" size="small">{t("row.toRead")}</Badge> : undefined}
          onClick={() => go.page("contract")}
        />
        <ListRow
          icon={FolderOpen}
          title={t("row.documents")}
          subtitle={first ? attentionText(t, first) : undefined}
          alert={Boolean(first)}
          className="hr-wrap"
          value={documents.data ? String(documents.data.length) : undefined}
          onClick={() => go.page("documents")}
        />
        {policies.data && policies.data.length > 0 && (
          <ListRow
            icon={BookOpenCheck}
            title={t("row.policies")}
            subtitle={pending[0] ? pending[0].title : t("row.policiesAll")}
            alert={pending.some((row) => row.state === "late")}
            className="hr-wrap"
            value={
              pending.length ? (
                <Badge tone="accent" size="small">
                  {t("row.policiesToSign", { count: pending.length })}
                </Badge>
              ) : undefined
            }
            onClick={() => go.page("policies")}
          />
        )}
      </ListCard>

      <SectionHead action={{ label: t("details.edit"), onClick: () => go.sheet("profile") }}>{t("section.details")}</SectionHead>
      <Details profile={data} locale={locale} />
      <p className="ft-hint">{t("details.hrOnly")}</p>

      <SectionHead count={data.emergency_contacts.length || undefined}>{t("section.contacts")}</SectionHead>
      {data.emergency_contacts.length === 0 ? (
        <p className="ft-quiet">{t("contacts.empty")}</p>
      ) : (
        <ListCard>
          {data.emergency_contacts.map((contact) => (
            <ListRow
              key={contact.id}
              icon={Phone}
              title={contact.name}
              subtitle={[contact.relation, contact.phone].filter(Boolean).join(" · ")}
              onClick={() => go.sheet("contact", { id: contact.id })}
            />
          ))}
        </ListCard>
      )}
      {data.emergency_contacts.length < MAX_CONTACTS && (
        <Button variant="secondary" block icon={Plus} onClick={() => go.sheet("contact")}>
          {t("contacts.add")}
        </Button>
      )}
    </Screen>
  );
}

/** Who I am here: name, position and department, since when and how. */
function Who({ profile }: { profile: Profile }) {
  const t = useHrT();
  const { locale } = useI18n();
  const member = useMember();
  const name = [profile.first_name, profile.last_name].filter(Boolean).join(" ");
  const facts = [
    profile.hire_date && t("profile.since", { date: dayMonthYear(profile.hire_date, "UTC", locale) }),
    t(`employment.${profile.employment_type}` as HrKey),
  ].filter(Boolean);
  return (
    <Card className="hr-who">
      <Avatar name={name || member.first_name} size="lg" />
      <div className="hr-who-text">
        <div className="hr-who-name">{name}</div>
        {(profile.position || profile.department) && <div className="hr-who-line">{[profile.position, profile.department].filter(Boolean).join(" · ")}</div>}
        <div className="hr-who-facts">{facts.join(" · ")}</div>
      </div>
    </Card>
  );
}

/** My details as HR has them; the edit sheet changes the ones that are mine to change. */
function Details({ profile, locale }: { profile: Profile; locale: string }) {
  const t = useHrT();
  const shown = (value: string) => (value ? value : <span className="hr-empty">{t("field.empty")}</span>);
  const birthday = profile.birth_date
    ? t(profile.show_birthday ? "birthday.shown" : "birthday.hidden", { date: dayMonthLong(profile.birth_date, "UTC", locale) })
    : "";
  return (
    <ListCard className="hr-details">
      <ListRow title={t("field.phone")} value={shown(profile.personal_phone)} />
      <ListRow title={t("field.email")} value={shown(profile.email)} />
      <ListRow title={t("field.city")} value={shown(profile.city)} />
      <ListRow title={t("field.address")} value={shown(profile.address)} />
      <ListRow title={t("field.birthday")} value={shown(birthday)} />
      <ListRow title={t("field.card")} value={shown(profile.payout_card ? shortMask(profile.payout_card) : "")} />
      <ListRow title={t("field.pinfl")} value={shown(profile.pinfl ? shortMask(profile.pinfl) : "")} />
      <ListRow title={t("field.passport")} value={shown(profile.passport)} />
    </ListCard>
  );
}
