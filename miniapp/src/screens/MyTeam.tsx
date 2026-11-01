import { ChevronRight } from "lucide-react";

import { useMyTeam } from "../api/hooks";
import type { TeamMember } from "../api/types";
import { useI18n, type Translate } from "../i18n";
import { CORE, useNavigation } from "../state/navigation";
import { useMember } from "../state/session";
import { haptic } from "../telegram";
import { Avatar, Card, CardButton, LoadError, PageHeader, Screen, Skeleton } from "../ui";

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
      <Screen variant="detail">
        <PageHeader kicker={data?.departments.join(" · ") || member.company.name} title={t("myTeam.title")} onBack={navigation.pop} />
        {!data ? (
          team.isError ? (
            <LoadError compact error={team.error} onRetry={() => void team.refetch()} />
          ) : (
            <Skeleton height={220} />
          )
        ) : data.people.length === 0 ? (
          <Card>
            <span className="muted">{t("myTeam.empty")}</span>
          </Card>
        ) : (
          <div className="team-people">
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
      </Screen>
    </div>
  );
}

/** One person as a row: who they are on the left, their numbers under the name, a chevron. */
function PersonRow({ person, t, onOpen }: { person: TeamMember; t: Translate; onOpen: () => void }) {
  return (
    <CardButton layout="row" className="team-person" onClick={onOpen}>
      <Avatar name={person.name} size="md" />
      <span className="team-person-main">
        <span className="row-title">{person.name}</span>
        {person.position && <span className="row-meta">{person.position}</span>}
        <span className="team-person-tags">
          <span className="tag tag-neutral">{t("myTeam.open", { count: person.open })}</span>
          {person.late > 0 && <span className="tag tag-accent">{t("myTeam.late", { count: person.late })}</span>}
          <span className="tag tag-sage">{t("myTeam.done", { count: person.done_week })}</span>
        </span>
      </span>
      <ChevronRight size={18} strokeWidth={2.5} className="team-person-chevron" aria-hidden />
    </CardButton>
  );
}
