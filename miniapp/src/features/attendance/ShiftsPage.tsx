/**
 * "My shifts": my published shifts for the next three weeks. A coming shift opens the request
 * sheet (ask a colleague to cover it or swap); open shifts and requests for me link to Swaps.
 */
import { CalendarDays, CalendarX2, Repeat2 } from "lucide-react";

import { useI18n } from "../../i18n";
import { dayKey } from "../../lib/time";
import { useNavigation } from "../../state/navigation";
import { useMember } from "../../state/session";
import { Badge, Banner, EmptyState, ListCard, ListRow, LoadError, PageHeader, Screen, SkeletonList } from "../../ui";
import { useMyShifts, useToday } from "./api";
import { shiftDay, shiftLine } from "./lib";
import { codeLabel, usePageT } from "./pageText";
import { duration } from "./text";
import type { Shift } from "./types";
import "./attendance.css";

export default function ShiftsPage() {
  const t = usePageT();
  const member = useMember();
  const navigation = useNavigation();
  const shifts = useMyShifts(member.companyId);
  const today = useToday(member.companyId);
  const day = today.data;
  const now = Date.now();

  const askFor = (shift: Shift) =>
    navigation.openSheet({ kind: "feature", feature: "attendance", sheet: "swap", params: { shift: shift.id } });

  return (
    <Screen variant="detail">
      <PageHeader kicker={t("me.attendance")} title={t("link.shifts")} subtitle={t("shifts.subtitle")} onBack={navigation.pop} />

      {day && day.requests + day.open_shifts > 0 && (
        <Banner
          size="lg"
          tone="sage"
          icon={Repeat2}
          title={day.requests ? t("home.requests", { count: day.requests }) : t("home.openShifts", { count: day.open_shifts })}
          body={day.requests ? t("home.requestsBody") : t("home.openShiftsBody")}
          onClick={() => navigation.push({ feature: "attendance", page: "swaps" })}
        />
      )}

      {shifts.isPending ? (
        <SkeletonList count={5} />
      ) : shifts.isError ? (
        <LoadError error={shifts.error} onRetry={() => void shifts.refetch()} />
      ) : !shifts.data?.length ? (
        <EmptyState icon={CalendarX2} tone="sage" title={t("shifts.empty")} body={t("shifts.emptyBody")} />
      ) : (
        <>
          <p className="att-hint">{t("shifts.hint")}</p>
          <ListCard>
            {shifts.data.map((shift) => (
              <ShiftRow key={shift.id} shift={shift} now={now} onAsk={askFor} />
            ))}
          </ListCard>
        </>
      )}
    </Screen>
  );
}

function ShiftRow({ shift, now, onAsk }: { shift: Shift; now: number; onAsk: (shift: Shift) => void }) {
  const t = usePageT();
  const { locale } = useI18n();
  const member = useMember();
  const isToday = shift.date === dayKey(new Date(now), member.timeZone);
  const askable = shift.status === "planned" && !shift.swap_pending && new Date(shift.starts_at).getTime() > now;
  const badge =
    shift.status === "leave" ? (
      <Badge size="small">{codeLabel(t, "leave")}</Badge>
    ) : shift.swap_pending ? (
      <Badge tone="accent" size="small" icon={Repeat2}>
        {t("shift.swapPending")}
      </Badge>
    ) : isToday ? (
      <Badge tone="sage" size="small">
        {t("shift.today")}
      </Badge>
    ) : (
      <span className="att-choice-sub">{duration(t, shift.minutes)}</span>
    );
  return (
    <ListRow
      icon={CalendarDays}
      title={shiftDay(shift, member.timeZone, locale)}
      // The position only when it isn't the person's usual one: the same word on every row is noise.
      subtitle={[shiftLine(shift), shift.position?.name !== member.position?.name && shift.position?.name].filter(Boolean).join(" · ")}
      value={badge}
      onClick={askable ? () => onAsk(shift) : undefined}
      chevron={askable}
    />
  );
}
