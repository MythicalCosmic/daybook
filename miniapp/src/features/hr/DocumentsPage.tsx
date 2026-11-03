/**
 * My documents (the bot's `hr.documents` link, sent when one runs out): each with its number,
 * until when it is valid and whether HR has checked it; upload a renewed one.
 */
import { FolderOpen, Upload } from "lucide-react";

import { useNavigation } from "../../state/navigation";
import { useMember } from "../../state/session";
import { BottomBar, EmptyState, LoadError, PageHeader, Screen, ScreenSkeleton } from "../../ui";
import { useFeatureOpen } from "../useFeatureOpen";
import { useDocuments } from "./api";
import { needingAttention } from "./lib";
import { DocumentBanner, DocumentRow } from "./parts";
import { useHrT } from "./text";
import "./hr.css";

export default function DocumentsPage() {
  const t = useHrT();
  const member = useMember();
  const navigation = useNavigation();
  const go = useFeatureOpen("hr");
  const documents = useDocuments(member.companyId);
  const first = needingAttention(documents.data)[0];
  const upload = (kind?: string) => go.sheet("upload", kind ? { kind } : undefined);

  return (
    <>
      <Screen variant="detail">
        <PageHeader kicker={t("me.documents")} title={t("row.documents")} onBack={navigation.pop} />
        {documents.isPending ? (
          <ScreenSkeleton variant="list" delay={150} />
        ) : documents.isError ? (
          <LoadError error={documents.error} onRetry={() => void documents.refetch()} onBack={navigation.pop} />
        ) : documents.data.length === 0 ? (
          <EmptyState icon={FolderOpen} tone="sage" title={t("documents.empty")} body={t("documents.emptyBody")} />
        ) : (
          <>
            {first && <DocumentBanner document={first} onOpen={() => upload(first.kind)} />}
            {documents.data.map((document) => (
              <DocumentRow key={document.id} document={document} onOpen={() => go.sheet("document", { id: document.id })} />
            ))}
          </>
        )}
      </Screen>
      {(documents.data || !documents.isError) && (
        <BottomBar primary={{ text: t("documents.upload"), onClick: () => upload(), icon: Upload, disabled: documents.isPending }} />
      )}
    </>
  );
}
