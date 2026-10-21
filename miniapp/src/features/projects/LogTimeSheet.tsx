import { Clock3, Minus, Plus } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { useI18n } from "../../i18n";
import { useFeatureT } from "../../i18n/feature";
import { addDays, dayKey, weekdayShort } from "../../lib/time";
import { useMember } from "../../state/session";
import { useToast } from "../../state/toast";
import { haptic } from "../../telegram";
import { Button, ChipGroup, EmptyState, Field, IconButton, Input, SheetTitle } from "../../ui";
import type { SheetProps } from "../registry";
import { logTime, useBoard, useMyProjects, useRefresh, useWeek } from "./api";
import { hhmm } from "./lib";
import { messages } from "./messages";
import "./projects.css";

const NONE = "none";

/**
 * "Log time": which project (and card), which day of the last week, how long (15-minute steps),
 * and a word about it. Opens from a card (project and card set), the (+) sheet or Me.
 */
export default function LogTimeSheet({ params, close }: SheetProps) {
  const member = useMember();
  const t = useFeatureT(messages);
  const { locale } = useI18n();
  const toast = useToast();
  const refresh = useRefresh(member.companyId);
  const projects = useMyProjects(member.companyId);
  const week = useWeek(member.companyId);
  const live = useMemo(() => (projects.data ?? []).filter((p) => p.status !== "completed" && p.status !== "cancelled"), [projects.data]);

  const [project, setProject] = useState<string | null>(params.project ? String(params.project) : null);
  const [task, setTask] = useState<string>(params.task ? String(params.task) : NONE);
  const today = dayKey(new Date(), member.timeZone);
  const [day, setDay] = useState(today);
  const [minutes, setMinutes] = useState(60);
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!project && live.length) setProject(String(live[0]!.id));
  }, [project, live]);

  const board = useBoard(member.companyId, Number(project) || 0);
  const myCards = (board.data?.cards ?? []).filter((card) => card.assignee?.id === member.id && card.status !== "done" && card.status !== "cancelled");
  const days = Array.from({ length: 7 }, (_, index) => addDays(today, -index));
  // Opened from a card: that card leads, so the picked chip is in sight.
  const opened = params.task ? String(params.task) : null;
  const cardChips = myCards.map((card) => ({ value: String(card.id), label: `${card.key} · ${card.title}` }));
  const first = cardChips.filter((chip) => chip.value === opened);
  const cardOptions = [...first, { value: NONE, label: t("log.wholeProject") }, ...cardChips.filter((chip) => chip.value !== opened)];

  function change(delta: number) {
    haptic.select();
    setMinutes((current) => Math.min(720, Math.max(15, current + delta)));
  }

  async function save() {
    if (!project || saving) return;
    setSaving(true);
    try {
      await logTime(member.companyId, { day, minutes, project: Number(project), task: task === NONE ? null : Number(task), note: note.trim() });
      haptic.notify("success");
      toast(t("log.saved", { time: hhmm(minutes) }), { tone: "success" });
      void refresh();
      close();
    } catch (error) {
      haptic.notify("error");
      toast((error as { detail?: string | null }).detail ?? t("moveFailed"), { tone: "error" });
    } finally {
      setSaving(false);
    }
  }

  if (projects.isSuccess && live.length === 0) {
    return <EmptyState compact icon={Clock3} title={t("log.title")} body={t("log.noProjects")} />;
  }

  return (
    <div className="prj-sheet">
      <SheetTitle kicker={week.data ? t("log.week", { time: hhmm(week.data.total) }) : undefined}>{t("log.title")}</SheetTitle>
      {live.length > 1 && (
        <Field label={t("log.project")}>
          <ChipGroup
            scroll
            value={project}
            onChange={(value) => {
              setProject(value);
              setTask(NONE);
            }}
            options={live.map((p) => ({ value: String(p.id), label: `${p.key} · ${p.name}` }))}
            label={t("log.project")}
          />
        </Field>
      )}
      {myCards.length > 0 && (
        <Field label={t("log.card")}>
          <ChipGroup
            scroll
            value={task}
            onChange={(value) => setTask(value ?? NONE)}
            options={cardOptions}
            label={t("log.card")}
          />
        </Field>
      )}
      <Field label={t("log.day")}>
        <ChipGroup
          scroll
          value={day}
          onChange={(value) => value && setDay(value)}
          options={days.map((key, index) => ({
            value: key,
            label: index === 0 ? t("today") : index === 1 ? t("log.yesterday") : weekdayShort(`${key}T12:00:00Z`, "UTC", locale),
          }))}
          label={t("log.day")}
        />
      </Field>
      <Field label={t("log.time")}>
        <div className="prj-duration">
          <IconButton icon={Minus} label={t("log.less")} disabled={minutes <= 15} onClick={() => change(-15)} />
          <span className="prj-duration-value" aria-live="polite">
            {hhmm(minutes)}
          </span>
          <IconButton icon={Plus} label={t("log.more")} disabled={minutes >= 720} onClick={() => change(15)} />
        </div>
      </Field>
      <Field label={t("log.note")} optional>
        <Input value={note} maxLength={300} placeholder={t("log.notePlaceholder")} onChange={(event) => setNote(event.target.value)} />
      </Field>
      {/* In the sheet, like every sheet's action: Telegram's button belongs to the page below. */}
      <Button variant="primary" size="lg" block loading={saving} disabled={!project} onClick={() => void save()}>
        {t("log.save", { time: hhmm(minutes) })}
      </Button>
    </div>
  );
}
