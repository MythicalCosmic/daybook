import { CalendarClock } from "lucide-react";

import type { SlotProps } from "../registry";
import { useI18n } from "../../i18n";
import { useFeatureT } from "../../i18n/feature";
import { addDays, dayKey } from "../../lib/time";
import { useNavigation } from "../../state/navigation";
import { haptic } from "../../telegram";
import { Banner } from "../../ui";
import { eventIdOf, useCalendar } from "./api";
import { dayName, timeLabel } from "./lib";
import { messages } from "./messages";

/**
 * Home: the next event I'm invited to today or tomorrow, one tap from answering. The line says
 * when, then "Are you coming?" while I haven't answered, or where it is once I have.
 */
export function NextEventCard({ member }: SlotProps) {
  const t = useFeatureT(messages);
  const { locale } = useI18n();
  const navigation = useNavigation();
  const timeZone = member.company.timezone;
  const today = dayKey(new Date(), timeZone);
  const calendar = useCalendar(member.company.id, today, addDays(today, 1));
  const mine = new Set(calendar.data?.mine ?? []);
  const now = Date.now();
  const next = (calendar.data?.items ?? []).find((item) => mine.has(item.id) && (item.all_day || Date.parse(item.end ?? item.start) >= now));
  if (!next) return null;
  const id = eventIdOf(next);
  const first = next.all_day ? next.start.slice(0, 10) : dayKey(next.start, timeZone);
  const whenText = `${dayName(first, today, timeZone, locale, { today: t("today"), tomorrow: t("tomorrow") })} ${timeLabel(next, timeZone, locale, t("allDay"))}`;
  const answer = calendar.data?.answers?.[next.id];
  const extra = answer === "pending" ? t("answer.question") : answer === "declined" ? t("answer.declined") : next.subtitle;
  return (
    <Banner
      iconTone="sage"
      size="lg"
      icon={CalendarClock}
      title={next.title}
      body={[whenText, extra].filter(Boolean).join(" · ")}
      wrap
      onClick={
        id
          ? () => {
              haptic.select();
              navigation.push({ feature: "agenda", page: "event", params: { id } });
            }
          : undefined
      }
    />
  );
}
