import { BookOpenCheck, Search } from "lucide-react";
import { useState } from "react";

import { useI18n } from "../../i18n";
import { useFeatureT } from "../../i18n/feature";
import { daysFromToday, dayMonth } from "../../lib/time";
import { useNavigation } from "../../state/navigation";
import { useMember } from "../../state/session";
import { haptic } from "../../telegram";
import { EmptyState, Input, ListCard, ListRow, PageHeader, Screen, ScreenSkeleton, SectionHead } from "../../ui";
import { useKbHome, useKbSearch, type KbPageRow } from "./api";
import "./knowledge.css";
import { messages } from "./messages";

const emoji = (value: string) => <span className="kbm-emoji">{value || "📄"}</span>;

/** The knowledge base in the app: search, what to read, the spaces and what changed lately. */
export function KnowledgeHome() {
  const t = useFeatureT(messages);
  const { locale } = useI18n();
  const member = useMember();
  const navigation = useNavigation();
  const home = useKbHome(member.companyId);
  const [query, setQuery] = useState("");
  const search = useKbSearch(member.companyId, query);
  const searching = query.trim().length >= 2;

  const openPage = (page: KbPageRow) => {
    haptic.select();
    navigation.push({ feature: "knowledge", page: "page", params: { id: page.id } });
  };
  const updated = (row: KbPageRow) => {
    const days = daysFromToday(row.updated_at, new Date(), member.timeZone);
    return days === 0 ? t("updatedToday") : t("updated", { date: dayMonth(row.updated_at, member.timeZone, locale) });
  };

  return (
    <Screen variant="detail">
      <PageHeader kicker={member.company.name} title={t("title")} onBack={navigation.pop} />
      <div className="kbm-search">
        <Search className="kbm-search-icon" size={19} strokeWidth={2.4} aria-hidden />
        <Input type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t("search")} aria-label={t("search")} />
      </div>

      {searching ? (
        search.data && search.data.length === 0 ? (
          <p className="kbm-hint">{t("search.none")}</p>
        ) : (
          <ListCard>
            {(search.data ?? []).map((row) => (
              <ListRow key={row.id} icon={emoji(row.emoji)} title={row.title} subtitle={`${row.space.icon} ${row.space.name}`} onClick={() => openPage(row)} />
            ))}
          </ListCard>
        )
      ) : !home.data ? (
        <ScreenSkeleton variant="list" delay={150} />
      ) : home.data.spaces.length === 0 ? (
        <EmptyState icon={BookOpenCheck} tone="sage" title={t("empty.title")} body={t("empty.body")} />
      ) : (
        <>
          {home.data.to_read.length > 0 && (
            <>
              <SectionHead count={home.data.to_read.length}>{t("toRead.title")}</SectionHead>
              {/* Each page says "read it to the end and confirm" itself; the list needs no hint. */}
              {home.data.to_read.map((row) => (
                <ListRow key={row.id} variant="card" tone="accent" icon={emoji(row.emoji)} title={row.title} subtitle={`${row.space.icon} ${row.space.name} · ${t("mustRead")}`} alert onClick={() => openPage(row)} />
              ))}
            </>
          )}

          <SectionHead>{t("spaces")}</SectionHead>
          <ListCard>
            {home.data.spaces.map((space) => (
              <ListRow
                key={space.id}
                icon={<span className="kbm-space-icon">{space.icon || "📁"}</span>}
                title={space.name}
                subtitle={space.description || t("pages", { count: space.counts.pages })}
                value={space.description ? String(space.counts.pages) : undefined}
                onClick={() => {
                  haptic.select();
                  navigation.push({ feature: "knowledge", page: "space", params: { id: space.id } });
                }}
              />
            ))}
          </ListCard>

          {home.data.recent.length > 0 && (
            <>
              <SectionHead>{t("recent")}</SectionHead>
              <ListCard>
                {home.data.recent.map((row) => (
                  <ListRow key={row.id} icon={emoji(row.emoji)} title={row.title} subtitle={`${row.space.name} · ${updated(row)}`} onClick={() => openPage(row)} />
                ))}
              </ListCard>
            </>
          )}
        </>
      )}
    </Screen>
  );
}
