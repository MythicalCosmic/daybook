import { useTeamPerson } from "../api/hooks";
import type { Task } from "../api/types";
import { TaskRow } from "../components/TaskRow";
import { useViewContext } from "../lib/useNow";
import { useNavigation } from "../state/navigation";
import { useMember } from "../state/session";
import { LoadError, PageHeader, Screen, SectionHead, Skeleton } from "../ui";

/** One of a head's people: their open work, then what they finished in the last 7 days with its
 * proof photo. Each task opens as usual (photo, report and comments there). */
export function TeamPerson({ memberId }: { memberId: number }) {
  const ctx = useViewContext();
  const { t } = ctx;
  const member = useMember();
  const navigation = useNavigation();
  const person = useTeamPerson(member.companyId, memberId);
  const data = person.data;
  const open = (task: Task) => navigation.openTask(task.id);

  return (
    <div className="detail-layer">
      <Screen variant="detail">
        {!data ? (
          person.isError ? (
            <LoadError compact error={person.error} onRetry={() => void person.refetch()} onBack={navigation.pop} />
          ) : (
            <Skeleton height={260} />
          )
        ) : (
          <>
            <PageHeader
              kicker={[data.person.position, data.person.department].filter(Boolean).join(" · ")}
              title={data.person.name}
              onBack={navigation.pop}
            />

            <SectionHead size="small">{t("myTeam.openSection", { count: data.open.length })}</SectionHead>
            {data.open.length === 0 ? (
              <div className="muted team-person-none">{t("myTeam.nothingOpen")}</div>
            ) : (
              <div className="card list-card">
                {data.open.map((task) => (
                  <TaskRow key={task.id} task={task} ctx={ctx} onOpen={() => open(task)} />
                ))}
              </div>
            )}

            <SectionHead size="small">{t("myTeam.doneSection", { count: data.done.length })}</SectionHead>
            {data.done.length === 0 ? (
              <div className="muted team-person-none">{t("myTeam.nothingDone")}</div>
            ) : (
              <div className="card list-card">
                {data.done.map((task) => (
                  <TaskRow
                    key={task.id}
                    task={task}
                    ctx={ctx}
                    onOpen={() => open(task)}
                    wrapMeta
                    // The server sends the photo itself as the thumb until the small copy is made.
                    trailing={task.proof_thumb ? <img className="row-thumb" src={task.proof_thumb} alt={t("myTeam.photo")} loading="lazy" decoding="async" /> : undefined}
                  />
                ))}
              </div>
            )}
          </>
        )}
      </Screen>
    </div>
  );
}
