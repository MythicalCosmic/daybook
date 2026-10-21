import { FolderKanban } from "lucide-react";

import { useNavigation } from "../../state/navigation";
import { useMember } from "../../state/session";
import { EmptyState, LoadError, PageHeader, PullToRefresh, ScreenSkeleton } from "../../ui";
import { useFeatureT } from "../../i18n/feature";
import { useMyProjects } from "./api";
import { messages } from "./messages";
import { ProjectRow } from "./ProjectRow";
import "./projects.css";

/** My projects: the ones I lead or work on, with progress, health and my open cards. */
export default function ProjectsPage() {
  const member = useMember();
  const t = useFeatureT(messages);
  const navigation = useNavigation();
  const query = useMyProjects(member.companyId);
  const projects = query.data ?? [];

  return (
    <PullToRefresh onRefresh={() => query.refetch()} className="screen screen--detail enter">
      <PageHeader kicker={member.company.name} title={t("title")} onBack={navigation.pop} />
      {query.isPending ? (
        <ScreenSkeleton variant="list" delay={150} />
      ) : query.isError && !query.data ? (
        <LoadError compact error={query.error} onRetry={() => void query.refetch()} />
      ) : projects.length === 0 ? (
        <EmptyState icon={FolderKanban} tone="sage" title={t("empty")} body={t("emptyBody")} />
      ) : (
        projects.map((project) => (
          <ProjectRow key={project.id} project={project} onOpen={() => navigation.push({ feature: "projects", page: "board", params: { id: project.id } })} />
        ))
      )}
    </PullToRefresh>
  );
}
