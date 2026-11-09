/**
 * The leaderboard (PLAN-LEARNING §7.6, §12.2): this week, this month or all time, for the company
 * or my branch. The top three stand on a podium with their pictures; then the list (staff see the
 * top ten, managers everyone they see) and my own place. Ties go to whoever got there first.
 */
import { Crown, EyeOff, Trophy } from "lucide-react";
import { useState } from "react";

import { useNavigation } from "../../state/navigation";
import { useMember } from "../../state/session";
import { Avatar, Card, EmptyState, LoadError, PageHeader, Screen, ScreenSkeleton, Segmented, cx } from "../../ui";
import type { PageProps } from "../registry";
import { useLeaderboard, type BoardRow, type BoardScope, type Period } from "./api";
import { useRecognitionT } from "./parts";
import "./recognition.css";

const PERIODS: readonly Period[] = ["week", "month", "all"];
const SCOPES: readonly BoardScope[] = ["company", "branch"];

export default function LeaderboardPage(_: PageProps) {
  const t = useRecognitionT();
  const member = useMember();
  const navigation = useNavigation();
  const [period, setPeriod] = useState<Period>("week");
  const [scope, setScope] = useState<BoardScope>("company");
  const board = useLeaderboard(member.companyId, period, scope);
  const data = board.data;
  // The company may keep staff to their branch: the server answers with the scope it used.
  const shownScope = data?.scope ?? scope;
  const forced = data !== undefined && data.scope !== scope;

  return (
    <Screen variant="detail" className="rcg-screen">
      <PageHeader title={t("board.title")} kicker={member.company.name} onBack={navigation.pop} />
      <Segmented
        options={PERIODS.map((value) => ({ value, label: t(`period.${value}`) }))}
        value={period}
        onChange={setPeriod}
        label={t("board.title")}
        fit
      />
      <Segmented
        options={SCOPES.map((value) => ({ value, label: t(`scope.${value}`), disabled: forced && value !== shownScope }))}
        value={shownScope}
        onChange={setScope}
        size="small"
        className="rcg-scope"
      />

      {board.isPending ? (
        <ScreenSkeleton variant="list" delay={150} />
      ) : !data ? (
        <LoadError error={board.error} onRetry={() => void board.refetch()} />
      ) : !data.visible ? (
        <EmptyState icon={EyeOff} tone="sage" title={t("board.title")} body={t("board.hidden")} />
      ) : (
        <>
          <Card className="rcg-me" layout="row" data-testid="board-me">
            <span className="rcg-me-label">{t("board.me")}</span>
            {data.me.place ? (
              <span className="rcg-me-value num">
                #{data.me.place} · {t("points", { count: data.me.points })}
              </span>
            ) : (
              <span className="rcg-me-none">{t("board.meNone")}</span>
            )}
          </Card>
          {data.rows.length === 0 ? (
            <EmptyState icon={Trophy} title={t("board.title")} body={t("board.empty")} />
          ) : (
            <>
              <Podium rows={data.rows.slice(0, 3)} me={member.id} />
              {data.rows.length > 3 && (
                <Card padding="list" className="rcg-board">
                  {data.rows.slice(3).map((row) => (
                    <BoardLine key={row.member.id} row={row} me={row.member.id === member.id} />
                  ))}
                </Card>
              )}
            </>
          )}
        </>
      )}
    </Screen>
  );
}

/** Second, first, third, standing on steps of three heights. */
function Podium({ rows, me }: { rows: BoardRow[]; me: number }) {
  const t = useRecognitionT();
  const order = [rows[1], rows[0], rows[2]].filter((row): row is BoardRow => row !== undefined);
  return (
    <div className="rcg-podium" data-testid="podium">
      {order.map((row) => (
        <div key={row.member.id} className={cx("rcg-podium-place", `rcg-podium-place--${row.place}`, row.member.id === me && "rcg-podium-place--me")}>
          <span className="rcg-podium-who">
            {row.place === 1 && <Crown size={22} strokeWidth={2.4} className="rcg-podium-crown" aria-hidden />}
            <Avatar name={row.member.name} src={row.member.avatar_url} size={row.place === 1 ? "lg" : "md"} />
          </span>
          <span className="rcg-podium-name">{row.member.name.split(" ")[0]}</span>
          <span className="rcg-podium-points num">{t("points", { count: row.points })}</span>
          <span className="rcg-podium-step num" aria-label={`#${row.place}`}>
            {row.place}
          </span>
        </div>
      ))}
    </div>
  );
}

function BoardLine({ row, me }: { row: BoardRow; me: boolean }) {
  const t = useRecognitionT();
  return (
    <div className={cx("list-item rcg-board-row", me && "rcg-board-row--me")}>
      <span className="rcg-board-place num">{row.place}</span>
      <Avatar name={row.member.name} src={row.member.avatar_url} size="sm" />
      <span className="rcg-board-who">
        <span className="rcg-board-name">{row.member.name}</span>
        <span className="rcg-board-level">
          {t("level", { number: row.level.number })} · {row.level.name}
        </span>
      </span>
      <span className="rcg-board-points num">{row.points}</span>
    </div>
  );
}
