import { useFeatureT } from "../../i18n/feature";
import { useNavigation } from "../../state/navigation";
import { haptic } from "../../telegram";
import { CardTitle, ListCard, ListRow } from "../../ui";
import type { TaskSlotProps } from "../registry";
import { useTaskPages } from "./api";
import { messages } from "./messages";
import "./knowledge.css";

/**
 * On the task screen (`task.actions`): "How to do this", the knowledge pages linked to the task
 * or to the routine that made it, each opening in the reader. Nothing when there are none.
 */
export function HowTo({ member, task }: TaskSlotProps) {
  const t = useFeatureT(messages);
  const navigation = useNavigation();
  const pages = useTaskPages(member.companyId, task.id).data ?? [];
  if (!pages.length) return null;
  return (
    <ListCard className="kbm-howto">
      <CardTitle>{t("howTo")}</CardTitle>
      {pages.map((page) => (
        <ListRow
          key={page.id}
          icon={<span className="kbm-emoji">{page.emoji || "📄"}</span>}
          title={page.title}
          subtitle={`${page.space.icon} ${page.space.name}`.trim()}
          onClick={() => {
            haptic.select();
            navigation.push({ feature: "knowledge", page: "page", params: { id: page.id } });
          }}
        />
      ))}
    </ListCard>
  );
}
