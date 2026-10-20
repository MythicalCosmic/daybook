import { CalendarDays, Flag } from "lucide-react";

import { useI18n } from "../../i18n";
import { useFeatureT } from "../../i18n/feature";
import { dayMonth } from "../../lib/time";
import { useMember } from "../../state/session";
import { Badge, CardButton, ProgressRing } from "../../ui";
import type { Project } from "./api";
import { colorClass, healthTone } from "./lib";
import { messages } from "./messages";
import "./projects.css";

/** One project: key, name, health (or status), progress ring, my open cards, next milestone. */
export function ProjectRow({ project, onOpen, compact = false }: { project: Project; onOpen: () => void; compact?: boolean }) {
  const t = useFeatureT(messages);
  const { locale } = useI18n();
  const member = useMember();
  const tone = healthTone(project.health);
  const live = project.status === "active";
  return (
    <CardButton className={`prj-card ${colorClass(project.color)}`} padding="flush" onClick={onOpen}>
      <span className="prj-head">
        <span className="prj-head-text">
          <span className="prj-key">{project.key}</span>
          <span className="prj-name">{project.name}</span>
        </span>
        {project.health && live ? (
          <Badge size="small" tone={tone === "neutral" ? "neutral" : tone}>
            {t(`health.${project.health}`)}
          </Badge>
        ) : !live ? (
          <Badge size="small">{t(`status.${project.status}` as "status.planning")}</Badge>
        ) : null}
      </span>
      <span className="prj-progress-row">
        <ProgressRing value={project.progress.done} total={project.progress.total} size={52} stroke={6} tone={project.health === "on_track" ? "sage" : "accent"} label={`${project.progress.percent}%`} />
        <span className="prj-progress-text">
          <span className="prj-strong">{t("cards", { done: project.progress.done, total: project.progress.total })}</span>
          <span className={project.my_open ? "prj-meta prj-meta--alert" : "prj-meta"}>
            {project.my_open ? t("myOpen", { count: project.my_open }) : t("myNone")}
          </span>
          {!compact && project.next_milestone?.due_on && (
            <span className="prj-meta">
              <Flag size={12} strokeWidth={2.4} aria-hidden /> {t("next", { name: project.next_milestone.name, date: dayMonth(`${project.next_milestone.due_on}T12:00:00Z`, "UTC", locale) })}
            </span>
          )}
          {!compact && !project.next_milestone && project.due_on && (
            <span className="prj-meta">
              <CalendarDays size={12} strokeWidth={2.4} aria-hidden /> {t("due", { date: dayMonth(`${project.due_on}T12:00:00Z`, member.timeZone, locale) })}
            </span>
          )}
        </span>
      </span>
    </CardButton>
  );
}
