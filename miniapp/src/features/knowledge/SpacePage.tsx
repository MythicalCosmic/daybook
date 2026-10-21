import { FileText } from "lucide-react";

import type { PageProps } from "../registry";
import { useFeatureT } from "../../i18n/feature";
import { useNavigation } from "../../state/navigation";
import { useMember } from "../../state/session";
import { haptic } from "../../telegram";
import { Badge, EmptyState, ListCard, ListRow, LoadError, PageHeader, Screen, ScreenSkeleton } from "../../ui";
import { flattenTree, useKbSpace } from "./api";
import "./knowledge.css";
import { messages } from "./messages";

/** One space: its published pages as an indented list. */
export function SpacePage({ params }: PageProps) {
  const t = useFeatureT(messages);
  const member = useMember();
  const navigation = useNavigation();
  const id = Number(params.id);
  const space = useKbSpace(member.companyId, id);

  if (!space.data) {
    return (
      <Screen variant="detail">
        {space.isError ? (
          <LoadError error={space.error} onRetry={() => void space.refetch()} onBack={navigation.pop} />
        ) : (
          <ScreenSkeleton variant="list" delay={150} />
        )}
      </Screen>
    );
  }
  const rows = flattenTree(space.data.pages);
  const { space: info } = space.data;
  return (
    <Screen variant="detail">
      <PageHeader
        kicker={t("title")}
        title={`${info.icon ? `${info.icon} ` : ""}${info.name}`}
        subtitle={info.description || t("pages", { count: rows.length })}
        onBack={navigation.pop}
      />
      {rows.length === 0 ? (
        <EmptyState icon={FileText} tone="sage" compact title={t("space.empty")} />
      ) : (
        <ListCard>
          {rows.map(({ node, depth }) => (
            <ListRow
              key={node.id}
              className={`kbm-depth-${Math.min(depth, 3)}`}
              icon={<span className="kbm-emoji">{node.emoji || "📄"}</span>}
              title={node.title}
              value={node.require_ack ? <Badge tone="accent" size="small">{t("mustRead")}</Badge> : undefined}
              onClick={() => {
                haptic.select();
                navigation.push({ feature: "knowledge", page: "page", params: { id: node.id } });
              }}
            />
          ))}
        </ListCard>
      )}
    </Screen>
  );
}
