import { Square, Timer } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";

import { useFeatureT } from "../../i18n/feature";
import { useNow } from "../../lib/useNow";
import { useNavigation } from "../../state/navigation";
import { useToast } from "../../state/toast";
import { haptic } from "../../telegram";
import { Button, Card, CardTitle } from "../../ui";
import type { SlotProps } from "../registry";
import { projectKeys, stopTimer, useMyProjects, useRefresh, useTimer } from "./api";
import { elapsed, hhmm } from "./lib";
import { messages } from "./messages";
import { ProjectRow } from "./ProjectRow";
import "./projects.css";

/** Home: the running timer, with Stop. Nothing when no timer runs. */
export function TimerCard({ member }: SlotProps) {
  const t = useFeatureT(messages);
  const toast = useToast();
  const client = useQueryClient();
  const refresh = useRefresh(member.companyId);
  const timer = useTimer(member.companyId);
  const now = useNow(1000);
  const running = timer.data;
  if (!running) return null;

  async function stop() {
    const entry = await stopTimer(member.companyId);
    haptic.notify("success");
    if (entry) toast(t("timerLogged", { time: hhmm(entry.minutes) }), { tone: "success" });
    await client.invalidateQueries({ queryKey: projectKeys.timer(member.companyId) });
    void refresh();
  }

  return (
    <Card tone="accent" className="prj-timer" layout="row" padding="flush">
      <span className="circle ui-row-icon ui-row-icon--accent" aria-hidden>
        <Timer size={20} strokeWidth={2.4} className="prj-pulse" />
      </span>
      <span className="row-main">
        <span className="prj-timer-clock">{elapsed(running.started_at, now.getTime())}</span>
        <span className="row-meta">
          {running.task && running.task_key
            ? t("timerOnCard", { key: running.task_key, title: running.task.name })
            : t("timerOnProject", { key: running.project_key ?? "" })}
        </span>
      </span>
      <Button variant="primary" icon={Square} onClick={() => void stop()}>
        {t("timerStop")}
      </Button>
    </Card>
  );
}

/** Home: my live projects (up to two), when I'm on any. */
export function ProjectsCard({ member }: SlotProps) {
  const t = useFeatureT(messages);
  const navigation = useNavigation();
  const projects = useMyProjects(member.companyId);
  const live = (projects.data ?? []).filter((p) => p.status === "active" || p.status === "planning");
  if (live.length === 0) return null;
  return (
    <>
      <CardTitle
        action={
          <button type="button" className="btn btn-ghost section-head-action" onClick={() => navigation.push({ feature: "projects", page: "list" })}>
            {t("homeAll")}
          </button>
        }
      >
        {t("home")}
      </CardTitle>
      {live.slice(0, 2).map((project) => (
        <ProjectRow key={project.id} project={project} compact onOpen={() => navigation.push({ feature: "projects", page: "board", params: { id: project.id } })} />
      ))}
    </>
  );
}
