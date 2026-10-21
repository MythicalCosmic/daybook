import { HeartPulse } from "lucide-react";

import { useI18n } from "../../i18n";
import { useFeatureT } from "../../i18n/feature";
import { dayMonth } from "../../lib/time";
import { useNavigation } from "../../state/navigation";
import { useMember } from "../../state/session";
import { Avatar, Badge, BottomBar, Card, EmptyState, PageHeader, PullToRefresh, ScreenSkeleton } from "../../ui";
import type { PageProps } from "../registry";
import { useBoard, useUpdates } from "./api";
import { healthTone } from "./lib";
import { messages } from "./messages";
import "./projects.css";

/** The project's updates feed: how it's going, in the lead's words, newest first. */
export default function UpdatesPage({ params }: PageProps) {
  const projectId = Number(params.id) || 0;
  const member = useMember();
  const t = useFeatureT(messages);
  const { locale } = useI18n();
  const navigation = useNavigation();
  const board = useBoard(member.companyId, projectId);
  const updates = useUpdates(member.companyId, projectId);
  const project = board.data?.project;
  const canPost = board.data?.capabilities.post_update ?? false;

  return (
    <PullToRefresh onRefresh={() => Promise.all([updates.refetch(), board.refetch()])} className="screen screen--detail enter">
      <PageHeader kicker={project ? `${project.key} · ${project.name}` : undefined} title={t("updates.title")} onBack={navigation.pop} />
      {updates.isPending ? (
        <ScreenSkeleton variant="list" delay={150} />
      ) : (updates.data ?? []).length === 0 ? (
        <EmptyState icon={HeartPulse} tone="sage" title={t("updates.empty")} body={t("updates.emptyBody")} />
      ) : (
        (updates.data ?? []).map((update) => {
          const tone = healthTone(update.health);
          return (
            <Card key={update.id} className="prj-update">
              <div className="prj-update-head">
                <Avatar name={update.author?.name ?? "?"} src={update.author?.photo_url} size="sm" />
                <span className="row-main">
                  <span className="row-title">{update.author?.name ?? "—"}</span>
                  <span className="row-meta">{dayMonth(update.created_at, member.timeZone, locale)}</span>
                </span>
                <Badge size="small" tone={tone === "neutral" ? "neutral" : tone}>
                  {t(`health.${update.health}`)}
                </Badge>
              </div>
              {update.text && <p className="prj-update-text">{update.text}</p>}
            </Card>
          );
        })
      )}
      {canPost && (
        <BottomBar
          primary={{
            text: t("updates.post"),
            onClick: () => navigation.openSheet({ kind: "feature", feature: "projects", sheet: "update", params: { id: projectId } }),
          }}
        />
      )}
    </PullToRefresh>
  );
}
