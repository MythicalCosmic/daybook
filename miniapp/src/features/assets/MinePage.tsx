/**
 * "Jihozlarim" (Me → My equipment): what the company gave me, each with the photo taken when it was
 * given (tap to see it whole), its state then, and "I have it" until I confirm; once confirmed it
 * says when. Never a value: what it costs is the owner's business.
 */
import { Check, Package } from "lucide-react";
import { useState } from "react";

import { useI18n } from "../../i18n";
import { dayMonthYear } from "../../lib/time";
import { useNavigation } from "../../state/navigation";
import { useMember } from "../../state/session";
import { Badge, Button, Card, EmptyState, LoadError, PageHeader, Screen, ScreenSkeleton, Sheet } from "../../ui";
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
  const [viewing, setViewing] = useState(false);
  const day = (value: string) => dayMonthYear(value, member.timeZone, locale, new Date());
  const details = [`${item.number} · ${item.category}`, t("row.given", { day: dayMonthYear(item.issued_on, "UTC", locale, new Date()) })];
  if (item.serial) details.push(t("row.serial", { serial: item.serial }));
  const title = item.model ? `${item.name} · ${item.model}` : item.name;
  return (
    <Card className="mine-card" data-testid="mine-item">
      <div className="mine-head">
        {item.photo_url ? (
          <button type="button" className="mine-photo" onClick={() => setViewing(true)} aria-label={t("row.photo", { name: item.name })} data-testid="mine-photo">
            <img src={item.photo_url} alt="" />
          </button>
        ) : (
          <span className={item.acknowledged_at ? "mine-icon mine-icon--done" : "mine-icon"}>
            <Package size={18} aria-hidden="true" />
          </span>
        )}
        <div className="mine-text">
          <div className="mine-title">{title}</div>
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
            {t("row.confirmedOn", { day: day(item.acknowledged_at) })}
          </Badge>
        ) : (
          <Button size="md" variant="primary" icon={<Check size={16} />} loading={acknowledge.isPending} onClick={() => acknowledge.mutate(item.id)}>
            {t("row.confirm")}
          </Button>
        )}
      </div>
      {viewing && item.photo_url && (
        <Sheet onClose={() => setViewing(false)} title={title}>
          <img className="mine-photo-full" src={item.photo_url} alt={t("row.photoAlt", { name: item.name })} />
          <p className="ft-quiet">{t("row.photoNote")}</p>
        </Sheet>
      )}
    </Card>
  );
}
