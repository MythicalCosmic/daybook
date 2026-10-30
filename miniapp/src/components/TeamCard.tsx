import { Users } from "lucide-react";

import { useMyTeam } from "../api/hooks";
import { useI18n } from "../i18n";
import { CORE, useNavigation } from "../state/navigation";
import { useMember } from "../state/session";
import { haptic } from "../telegram";
import { Banner } from "../ui";

/**
 * A department head's way into My team where they look for it, at the top of Home and Tasks:
 * their departments, how many people, how many of their tasks are late. Nothing for someone who
 * heads no department.
 */
export function TeamCard() {
  const { t } = useI18n();
  const member = useMember();
  const navigation = useNavigation();
  const heads = member.heads ?? [];
  const team = useMyTeam(member.companyId, heads.length > 0);
  if (heads.length === 0) return null;
  const people = team.data?.people;
  const late = (people ?? []).reduce((sum, person) => sum + person.late, 0);
  const body = [
    heads.join(", "),
    people && t("myTeam.people", { count: people.length }),
    late > 0 && t("myTeam.late", { count: late }),
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <Banner
      size="lg"
      icon={Users}
      title={t("myTeam.title")}
      body={body}
      wrap
      onClick={() => {
        haptic();
        navigation.push({ feature: CORE, page: "myTeam" });
      }}
    />
  );
}
