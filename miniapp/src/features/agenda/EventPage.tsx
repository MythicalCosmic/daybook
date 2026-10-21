import { BellRing, Building2, CalendarDays, CircleX, MapPin, Repeat } from "lucide-react";

import type { PageProps } from "../registry";
import { useI18n } from "../../i18n";
import { useFeatureT } from "../../i18n/feature";
import { clock, dayKey, dayMonth } from "../../lib/time";
import { useNavigation } from "../../state/navigation";
import { initials, useMember } from "../../state/session";
import { useToast } from "../../state/toast";
import { haptic } from "../../telegram";
import { Badge, Banner, BottomBar, Card, ListCard, ListRow, PageHeader, Screen, ScreenSkeleton, SectionHead, Segmented, cx } from "../../ui";
import { useAnswer, useEvent, type AgendaEvent, type Answer } from "./api";
import "./agenda.css";
import { colorClass, dayName } from "./lib";
import { messages } from "./messages";

const ANSWER_TONE: Record<Answer, "sage" | "accent" | "neutral"> = { going: "sage", declined: "accent", pending: "neutral" };

/** One company event: when, where, who comes, and my answer. */
export function EventPage({ params }: PageProps) {
  const t = useFeatureT(messages);
  const { locale } = useI18n();
  const member = useMember();
  const navigation = useNavigation();
  const toast = useToast();
  const id = Number(params.id);
  const query = useEvent(member.companyId, id);
  const answer = useAnswer(member.companyId, id);

  if (!query.data) {
    return (
      <Screen variant="detail">
        <ScreenSkeleton variant="detail" delay={150} />
      </Screen>
    );
  }
  const event = query.data;
  const today = dayKey(new Date(), member.timeZone);
  const words = { today: t("today"), tomorrow: t("tomorrow") };
  const invited = event.my_response !== null && !event.cancelled;

  const reply = (response: Exclude<Answer, "pending">) =>
    answer.mutate(response, {
      onSuccess: () => {
        haptic.notify("success");
        toast(t(response === "going" ? "answer.saved.going" : "answer.saved.declined"), { tone: "success" });
      },
      onError: () => {
        haptic.notify("error");
        toast(t("answer.failed"), { tone: "error" });
      },
    });

  return (
    <>
      <Screen variant="detail">
        <PageHeader kicker={t(`kind.${event.kind}`)} title={event.title} onBack={navigation.pop} />
        {event.cancelled && <Banner tone="accent" icon={CircleX} title={t("cancelled")} body={event.cancel_reason || undefined} />}

        <Card>
          <div className="agm-facts">
            <div className="agm-fact">
              <span className={cx("agm-bar", colorClass(event.color))} aria-hidden />
              <span>{when(event, today, member.timeZone, locale, words, t("allDay"))}</span>
            </div>
            {event.repeat !== "none" && (
              <div className="agm-fact">
                <Repeat size={19} strokeWidth={2.4} aria-hidden />
                <span>{t(`repeat.${event.repeat}`)}</span>
              </div>
            )}
            {event.place && (
              <div className="agm-fact">
                <MapPin size={19} strokeWidth={2.4} aria-hidden />
                <span>{event.place}</span>
              </div>
            )}
            {event.branch && (
              <div className="agm-fact">
                <Building2 size={19} strokeWidth={2.4} aria-hidden />
                <span>{event.branch.name}</span>
              </div>
            )}
            {invited && (
              <div className="agm-fact">
                <BellRing size={19} strokeWidth={2.4} aria-hidden />
                <span>{reminderText(event.remind_before, t)}</span>
              </div>
            )}
          </div>
        </Card>

        {event.description && (
          <Card>
            <p className="agm-description">{event.description}</p>
          </Card>
        )}

        {invited && event.my_response !== "pending" && (
          <>
            <SectionHead size="small">{t("answer.question")}</SectionHead>
            <Segmented
              options={[
                { value: "going", label: t("answer.going") },
                { value: "declined", label: t("answer.declined") },
              ]}
              value={event.my_response as "going" | "declined"}
              onChange={(value) => reply(value)}
              label={t("answer.question")}
            />
          </>
        )}

        {event.attendees.length > 0 && (
          <>
            <SectionHead>{t("attendees", { count: event.attendees.length })}</SectionHead>
            <ListCard>
              {event.attendees.map((attendee) => {
                const [first = "", last = ""] = attendee.member.name.split(" ");
                return (
                  <ListRow
                    key={attendee.member.id}
                    icon={<span className="agm-person">{initials(first, last)}</span>}
                    title={attendee.member.name}
                    subtitle={attendee.member.position ?? undefined}
                    value={<Badge tone={ANSWER_TONE[attendee.response]} size="small">{t(attendee.response === "going" ? "answer.going" : attendee.response === "declined" ? "answer.declined" : "answer.pending")}</Badge>}
                  />
                );
              })}
            </ListCard>
            <p className="agm-hint">{t("counts", { going: event.responses.going, pending: event.responses.pending })}</p>
          </>
        )}
      </Screen>
      {/* Outside the scrolling screen, so it stays at the bottom however far one scrolls. */}
      {invited && event.my_response === "pending" && (
        <BottomBar
          primary={{ text: t("answer.going"), onClick: () => reply("going"), loading: answer.isPending && answer.variables === "going", icon: CalendarDays, shine: true }}
          secondary={{ text: t("answer.declined"), onClick: () => reply("declined"), loading: answer.isPending && answer.variables === "declined" }}
        />
      )}
    </>
  );
}

function when(event: AgendaEvent, today: string, timeZone: string, locale: string, words: { today: string; tomorrow: string }, allDay: string): string {
  const first = event.all_day ? event.start.slice(0, 10) : dayKey(event.start, timeZone);
  const day = `${dayName(first, today, timeZone, locale, words)}, ${dayMonth(`${first}T12:00:00Z`, timeZone, locale)}`;
  if (event.all_day) {
    const last = event.end?.slice(0, 10);
    return last && last !== first ? `${day} – ${dayMonth(`${last}T12:00:00Z`, timeZone, locale)}` : `${day} · ${allDay}`;
  }
  const start = clock(event.start, timeZone, locale);
  return event.end ? `${day} · ${start} – ${clock(event.end, timeZone, locale)}` : `${day} · ${start}`;
}

function reminderText(minutes: number | null, t: ReturnType<typeof useFeatureT<keyof typeof messages.en>>): string {
  if (minutes === null) return t("reminder.none");
  if (minutes === 0) return t("reminder.atStart");
  if (minutes % 1440 === 0) return t("reminder.days", { count: minutes / 1440 });
  if (minutes % 60 === 0) return t("reminder.hours", { count: minutes / 60 });
  return t("reminder.minutes", { count: minutes });
}
