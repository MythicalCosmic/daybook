import { ChevronRight } from "lucide-react";

import { useMyTeam } from "../api/hooks";
import type { TeamMember } from "../api/types";
import { useI18n, type Translate } from "../i18n";
import { nameInitials } from "../lib/team";
import { CORE, useNavigation } from "../state/navigation";
import { useMember } from "../state/session";
import { haptic } from "../telegram";
import { LoadError } from "../ui";

/** A department head's people (apps.members.departments): who has what open, what is late, and
 * what they finished this week. A person opens their work. */
export function MyTeam() {
  const { t } = useI18n();
  const member = useMember();
  const navigation = useNavigation();
  const team = useMyTeam(member.companyId);
  const data = team.data;

  return (
    <div className="detail-layer">
      <div className="screen screen--detail">
        <div style={{ padding: "0 4px" }}>
          <div className="muted" style={{ fontSize: 14, fontWeight: 600 }}>{data?.departments.join(" · ") || member.company.name}</div>
          <h1 className="heading" style={{ fontSize: 30, lineHeight: 1.1 }}>{t("myTeam.title")}</h1>
        </div>
        {!data ? (
          team.isError ? (
            <LoadError compact error={team.error} onRetry={() => void team.refetch()} />
          ) : (
            <div className="skeleton" style={{ height: 220 }} />
          )
        ) : data.people.length === 0 ? (
          <div className="card" style={{ padding: 18 }}>
            <span className="muted" style={{ fontSize: 15 }}>{t("myTeam.empty")}</span>
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {data.people.map((person) => (
              <PersonRow
                key={person.id}
                person={person}
                t={t}
                onOpen={() => {
                  haptic();
                  navigation.push({ feature: CORE, page: "teamPerson", params: { id: person.id } });
                }}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function PersonRow({ person, t, onOpen }: { person: TeamMember; t: Translate; onOpen: () => void }) {
  return (
    <button className="card" onClick={onOpen} style={{ padding: 14, display: "flex", alignItems: "center", gap: 12, textAlign: "left" }}>
      <span className="avatar" style={{ width: 44, height: 44, fontSize: 16, flex: "none" }}>
        {nameInitials(person.name)}
      </span>
      <span style={{ display: "flex", flexDirection: "column", gap: 4, minWidth: 0, flex: 1 }}>
        <span style={{ fontWeight: 700, fontSize: 16 }}>{person.name}</span>
        {person.position && <span className="muted" style={{ fontSize: 13 }}>{person.position}</span>}
        <span style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
          <span className="tag tag-neutral">{t("myTeam.open", { count: person.open })}</span>
          {person.late > 0 && <span className="tag tag-accent">{t("myTeam.late", { count: person.late })}</span>}
          <span className="tag tag-sage">{t("myTeam.done", { count: person.done_week })}</span>
        </span>
      </span>
      <ChevronRight size={18} strokeWidth={2.5} style={{ flex: "none" }} />
    </button>
  );
}
