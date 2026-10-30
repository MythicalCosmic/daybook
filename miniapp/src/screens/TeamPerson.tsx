import { useTeamPerson } from "../api/hooks";
import type { Task } from "../api/types";
import { TaskRow } from "../components/TaskRow";
import { useI18n } from "../i18n";
import { useViewContext } from "../lib/useNow";
import { useNavigation } from "../state/navigation";
import { useMember } from "../state/session";
import { LoadError } from "../ui";

/** One of a head's people: their open work, then what they finished in the last 7 days with its
 * proof photo. Each task opens as usual (photo, report and comments there). */
export function TeamPerson({ memberId }: { memberId: number }) {
  const { t } = useI18n();
  const ctx = useViewContext();
  const member = useMember();
  const navigation = useNavigation();
  const person = useTeamPerson(member.companyId, memberId);
  const data = person.data;
  const open = (task: Task) => navigation.openTask(task.id);

  return (
    <div className="detail-layer">
      <div className="screen screen--detail">
        {!data ? (
          person.isError ? (
            <LoadError compact error={person.error} onRetry={() => void person.refetch()} />
          ) : (
            <div className="skeleton" style={{ height: 260 }} />
          )
        ) : (
          <>
            <div style={{ padding: "0 4px" }}>
              <div className="muted" style={{ fontSize: 14, fontWeight: 600 }}>
                {[data.person.position, data.person.department].filter(Boolean).join(" · ")}
              </div>
              <h1 className="heading" style={{ fontSize: 28, lineHeight: 1.1 }}>{data.person.name}</h1>
            </div>

            <div className="section-head section-head--small">{t("myTeam.openSection", { count: data.open.length })}</div>
            {data.open.length === 0 ? (
              <div className="muted" style={{ fontSize: 15, padding: "0 4px" }}>{t("myTeam.nothingOpen")}</div>
            ) : (
              <div className="card list-card">
                {data.open.map((task) => (
                  <TaskRow key={task.id} task={task} ctx={ctx} onOpen={() => open(task)} />
                ))}
              </div>
            )}

            <div className="section-head section-head--small">{t("myTeam.doneSection", { count: data.done.length })}</div>
            {data.done.length === 0 ? (
              <div className="muted" style={{ fontSize: 15, padding: "0 4px" }}>{t("myTeam.nothingDone")}</div>
            ) : (
              <div className="card list-card">
                {data.done.map((task) => (
                  <TaskRow
                    key={task.id}
                    task={task}
                    ctx={ctx}
                    onOpen={() => open(task)}
                    wrapMeta
                    trailing={
                      task.proof_thumb || task.proof_photo ? (
                        <img src={task.proof_thumb ?? task.proof_photo ?? ""} alt={t("myTeam.photo")} style={{ width: 44, height: 44, borderRadius: 10, objectFit: "cover", flex: "none" }} />
                      ) : undefined
                    }
                  />
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
