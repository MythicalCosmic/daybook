/**
 * "Jihozlarim" (Me → My equipment): what the company gave me, each with its state when given and
 * "I have it" until I confirm. Never a value: what it costs is the owner's business.
 */
import { Check, Package } from "lucide-react";

import { useI18n } from "../../i18n";
import { dayMonthYear } from "../../lib/time";
import { useNavigation } from "../../state/navigation";
import { useMember } from "../../state/session";
import { Badge, Button, Card, EmptyState, LoadError, PageHeader, Screen, ScreenSkeleton } from "../../ui";
import { useAcknowledge, useMine, type MineItem } from "./api";
import { useMineT, type MineKey } from "./text";
import "./assets.css";

export default function MinePage() {
  const t = useMineT();
  const member = useMember();
  const navigation = useNavigation();
  const mine = useMine(member.companyId);
  const header = <PageHeader kicker={member.company.name} title={t("me.equipment")} subtitle={t("page.subtitle")} onBack={navigation.pop} />;
  if (!mine.data) {
    return (
      <Screen variant="detail">
        {header}
        {mine.isError ? <LoadError error={mine.error} onRetry={() => void mine.refetch()} onBack={navigation.pop} /> : <ScreenSkeleton variant="list" delay={150} />}
      </Screen>
    );
  }
  if (mine.data.length === 0) {
    return (
      <Screen variant="detail">
        {header}
        <EmptyState icon={Package} tone="sage" title={t("page.empty")} body={t("page.emptyBody")} />
      </Screen>
    );
  }
  return (
    <Screen variant="detail">
      {header}
      <p className="ft-quiet">{t("page.intro")}</p>
      {mine.data.map((item) => (
        <MineRow key={item.id} item={item} />
      ))}
    </Screen>
  );
}

function MineRow({ item }: { item: MineItem }) {
  const t = useMineT();
  const { locale } = useI18n();
  const member = useMember();
  const acknowledge = useAcknowledge(member.companyId);
  const details = [`${item.number} · ${item.category}`, t("row.given", { day: dayMonthYear(item.issued_on, "UTC", locale, new Date()) })];
  if (item.serial) details.push(t("row.serial", { serial: item.serial }));
  return (
    <Card className="mine-card" data-testid="mine-item">
      <div className="mine-head">
        <span className={item.acknowledged_at ? "mine-icon mine-icon--done" : "mine-icon"}>
          <Package size={18} aria-hidden="true" />
        </span>
        <div className="mine-text">
          <div className="mine-title">{item.model ? `${item.name} · ${item.model}` : item.name}</div>
          {details.map((line) => (
            <div key={line} className="mine-line">
              {line}
            </div>
          ))}
          {item.note && <div className="mine-line">{item.note}</div>}
        </div>
      </div>
      <div className="mine-foot">
        <Badge tone="neutral" size="small">
          {t(`condition.${item.condition}` as MineKey)}
        </Badge>
        {item.acknowledged_at ? (
          <Badge tone="sage" size="small">
            {t("row.confirmed")}
          </Badge>
        ) : (
          <Button size="md" variant="primary" icon={<Check size={16} />} loading={acknowledge.isPending} onClick={() => acknowledge.mutate(item.id)}>
            {t("row.confirm")}
          </Button>
        )}
      </div>
    </Card>
  );
}
